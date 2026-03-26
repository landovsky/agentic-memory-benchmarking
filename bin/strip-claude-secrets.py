#!/usr/bin/env python3
"""
Strip secrets from Claude Code local conversation history.

Claude Code stores all session output as plaintext JSONL files under
~/.claude/projects/. This script scans those files and redacts secrets
(API keys, passwords, tokens, private keys, database URLs, etc.).

Usage:
  # Dry run — show what would be redacted (default)
  python3 scripts/strip-claude-secrets.py

  # Actually redact secrets in-place
  python3 scripts/strip-claude-secrets.py --apply

  # Scan a specific project directory
  python3 scripts/strip-claude-secrets.py --path ~/.claude/projects/-Users-foo-myproject

  # Also scan ~/.claude.json for leaked metadata
  python3 scripts/strip-claude-secrets.py --include-config
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ── Secret patterns ──────────────────────────────────────────────────────────
# Each tuple: (name, compiled regex, replacement template)
# The replacement uses \\1 etc. to preserve structure where useful.

SECRET_PATTERNS = [
    # Private keys (PEM)
    (
        "Private Key",
        re.compile(
            r"-----BEGIN[ A-Z]*PRIVATE KEY-----[\s\S]*?-----END[ A-Z]*PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # Certificates (less sensitive, but can leak identity)
    (
        "Certificate",
        re.compile(
            r"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----"
        ),
        "[REDACTED_CERTIFICATE]",
    ),
    # AWS keys
    (
        "AWS Access Key",
        re.compile(r"(?<![A-Za-z0-9/+])(AKIA[0-9A-Z]{16})(?![A-Za-z0-9/+=])"),
        "[REDACTED_AWS_KEY]",
    ),
    (
        "AWS Secret Key",
        re.compile(
            r"""(?:aws_secret_access_key|secret_?key|AWS_SECRET)\s*[=:]\s*['"]?([A-Za-z0-9/+=]{40})['"]?""",
            re.IGNORECASE,
        ),
        "[REDACTED_AWS_SECRET]",
    ),
    # Generic API keys / tokens (common env-var patterns)
    (
        "API Key/Token (env assignment)",
        re.compile(
            r"""(?:API_KEY|API_SECRET|SECRET_KEY|AUTH_TOKEN|ACCESS_TOKEN|PRIVATE_KEY|ENCRYPTION_KEY|SIGNING_KEY|APP_SECRET|MASTER_KEY|RAILS_MASTER_KEY)\s*[=:]\s*['"]?(?!\[REDACTED)([A-Za-z0-9_.~+/=-]{16,})['"]?""",
            re.IGNORECASE,
        ),
        "[REDACTED_SECRET]",
    ),
    # OpenAI keys
    (
        "OpenAI Key",
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        "[REDACTED_OPENAI_KEY]",
    ),
    # Anthropic keys
    (
        "Anthropic Key",
        re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
        "[REDACTED_ANTHROPIC_KEY]",
    ),
    # GitHub tokens
    (
        "GitHub Token",
        re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    # Slack tokens
    (
        "Slack Token",
        re.compile(r"xox[bposa]-[A-Za-z0-9-]{10,}"),
        "[REDACTED_SLACK_TOKEN]",
    ),
    # Stripe keys
    (
        "Stripe Key",
        re.compile(r"(sk|pk|rk)_(test|live)_[A-Za-z0-9]{10,}"),
        "[REDACTED_STRIPE_KEY]",
    ),
    # Database URLs with credentials (skip already-redacted)
    (
        "Database URL",
        re.compile(
            r"(postgres(?:ql)?|mysql|mysql2|mongodb(?:\+srv)?|redis|amqp)://(?!\[REDACTED)[^\s'\"}{,\]]+@[^\s'\"}{,\]]+",
            re.IGNORECASE,
        ),
        "[REDACTED_DATABASE_URL]",
    ),
    # Generic connection strings with passwords (skip already-redacted)
    (
        "Connection String Password",
        re.compile(
            r"(://[^:@\s]+):(?!\[REDACTED)([^@\s]{8,})(@)", re.IGNORECASE
        ),
        r"\1:[REDACTED_PASSWORD]\3",
    ),
    # Bearer tokens
    (
        "Bearer Token",
        re.compile(
            r"(Bearer\s+)[A-Za-z0-9_.~+/=-]{20,}", re.IGNORECASE
        ),
        r"\1[REDACTED_BEARER_TOKEN]",
    ),
    # JWT tokens (three base64 segments separated by dots)
    (
        "JWT Token",
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
        "[REDACTED_JWT]",
    ),
    # Passwords in common formats (skip already-redacted values)
    (
        "Password Assignment",
        re.compile(
            r"""((?:password|passwd|pwd|pass)\s*[=:]\s*)['"]?(?!\[REDACTED)([^\s'"]{8,})['"]?""",
            re.IGNORECASE,
        ),
        r"\1[REDACTED_PASSWORD]",
    ),
    # Hex-encoded secrets (32+ chars, typically in env vars)
    (
        "Hex Secret",
        re.compile(
            r"""(?:SECRET|TOKEN|KEY|SALT|PEPPER)\s*[=:]\s*['"]?([0-9a-f]{32,})['"]?""",
            re.IGNORECASE,
        ),
        "[REDACTED_HEX_SECRET]",
    ),
    # SSH passwords in URLs
    (
        "SSH URL Credentials",
        re.compile(r"ssh://([^:@\s]+):(?!\[REDACTED)([^@\s]+)@"),
        r"ssh://\1:[REDACTED]@",
    ),
    # .env file style secrets (broad catch-all, only match value part)
    (
        "Env Secret Value",
        re.compile(
            r"""^(\s*(?:DATABASE_PASSWORD|DB_PASSWORD|REDIS_PASSWORD|SMTP_PASSWORD|MAIL_PASSWORD|SESSION_SECRET|DEVISE_SECRET|LOCKBOX_MASTER_KEY)\s*=\s*)(?!\[REDACTED)(.+)$""",
            re.IGNORECASE | re.MULTILINE,
        ),
        r"\1[REDACTED]",
    ),
]


def find_jsonl_files(base_path: Path) -> list[Path]:
    """Find all .jsonl files recursively."""
    return sorted(base_path.rglob("*.jsonl"))


def scan_text(text: str) -> list[tuple[str, str]]:
    """Return list of (pattern_name, matched_text) for all secrets found."""
    findings = []
    for name, pattern, _ in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append((name, match.group(0)[:80]))
    return findings


def redact_text(text: str) -> tuple[str, int]:
    """Apply all redaction patterns. Returns (redacted_text, count)."""
    total = 0
    for _, pattern, replacement in SECRET_PATTERNS:
        text, n = pattern.subn(replacement, text)
        total += n
    return text, total


def process_jsonl_file(filepath: Path, apply: bool) -> tuple[int, int]:
    """Process a single JSONL file. Returns (lines_changed, secrets_found)."""
    lines_changed = 0
    secrets_found = 0
    new_lines = []

    try:
        raw = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError) as e:
        print(f"  SKIP {filepath}: {e}", file=sys.stderr)
        return 0, 0

    for lineno, line in enumerate(raw.splitlines(keepends=True), 1):
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue

        # Scan the raw JSON line for secrets
        findings = scan_text(stripped)
        if findings:
            secrets_found += len(findings)
            for name, snippet in findings:
                truncated = snippet if len(snippet) < 80 else snippet[:77] + "..."
                print(f"  L{lineno} [{name}]: {truncated}")
            redacted, _ = redact_text(line)
            new_lines.append(redacted)
            lines_changed += 1
        else:
            new_lines.append(line)

    if apply and lines_changed > 0:
        filepath.write_text("".join(new_lines), encoding="utf-8")

    return lines_changed, secrets_found


def process_json_file(filepath: Path, apply: bool) -> int:
    """Process a plain JSON file (e.g. ~/.claude.json). Returns secrets found."""
    if not filepath.exists():
        return 0

    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError) as e:
        print(f"  SKIP {filepath}: {e}", file=sys.stderr)
        return 0

    findings = scan_text(text)
    if findings:
        print(f"\n{'=' * 60}")
        print(f"FILE: {filepath}")
        print(f"{'=' * 60}")
        for name, snippet in findings:
            truncated = snippet if len(snippet) < 80 else snippet[:77] + "..."
            print(f"  [{name}]: {truncated}")

        if apply:
            redacted, count = redact_text(text)
            filepath.write_text(redacted, encoding="utf-8")
            print(f"  -> Redacted {count} secret(s)")

    return len(findings)


def main():
    parser = argparse.ArgumentParser(
        description="Strip secrets from Claude Code local history"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually redact secrets in-place (default is dry-run)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.home() / ".claude" / "projects",
        help="Path to scan (default: ~/.claude/projects)",
    )
    parser.add_argument(
        "--include-config",
        action="store_true",
        help="Also scan ~/.claude.json",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    mode = "REDACTING" if args.apply else "DRY RUN (use --apply to redact)"
    print(f"Mode: {mode}")
    print(f"Scanning: {args.path}")
    print()

    jsonl_files = find_jsonl_files(args.path)
    print(f"Found {len(jsonl_files)} session file(s)\n")

    total_files_with_secrets = 0
    total_secrets = 0

    for filepath in jsonl_files:
        findings_before = total_secrets
        lines_changed, secrets = process_jsonl_file(filepath, args.apply)
        total_secrets += secrets

        if secrets > 0:
            total_files_with_secrets += 1
            rel = filepath.relative_to(args.path)
            action = "Redacted" if args.apply else "Found"
            print(f"\n{'=' * 60}")
            print(f"FILE: {rel}")
            print(f"  {action} {secrets} secret(s) across {lines_changed} line(s)")
            print(f"{'=' * 60}\n")

    if args.include_config:
        config_path = Path.home() / ".claude.json"
        config_secrets = process_json_file(config_path, args.apply)
        total_secrets += config_secrets
        if config_secrets > 0:
            total_files_with_secrets += 1

    # Summary
    print(f"\n{'─' * 60}")
    print(f"SUMMARY")
    print(f"{'─' * 60}")
    print(f"  Files scanned:      {len(jsonl_files)}")
    print(f"  Files with secrets: {total_files_with_secrets}")
    print(f"  Total secrets:      {total_secrets}")
    if total_secrets > 0 and not args.apply:
        print(f"\n  Run with --apply to redact these secrets in-place.")
    elif total_secrets > 0 and args.apply:
        print(f"\n  All secrets have been redacted.")
    else:
        print(f"\n  No secrets detected. You're clean!")
    print()


if __name__ == "__main__":
    main()
