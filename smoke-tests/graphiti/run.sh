#!/usr/bin/env bash
# End-to-end smoke test for Graphiti: load sessions → run eval → generate report
#
# Usage:
#   ./run.sh                    # smoke suite (3 cases)
#   ./run.sh --full             # full suite (10 cases)
#   ./run.sh --skip-load        # skip session loading (already loaded)
#   ./run.sh --full --skip-load # full suite, skip loading
#   ./run.sh --dry-run          # show what would be loaded, don't run eval

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults
SUITE="smoke"
SKIP_LOAD=false
DRY_RUN=false
RUNNER_NAME="${RUNNER_NAME:-$(whoami)}"

for arg in "$@"; do
  case "$arg" in
    --full)       SUITE="full" ;;
    --skip-load)  SKIP_LOAD=true ;;
    --dry-run)    DRY_RUN=true ;;
    --help|-h)
      echo "Usage: ./run.sh [--full] [--skip-load] [--dry-run]"
      echo "  --full       Run full test suite (10 cases) instead of smoke (3)"
      echo "  --skip-load  Skip loading sessions into Graphiti"
      echo "  --dry-run    Show what would be loaded without writing or running eval"
      exit 0
      ;;
    *) echo "Unknown flag: $arg"; exit 1 ;;
  esac
done

# Resolve test case file
if [ "$SUITE" = "full" ]; then
  TEST_CASES="shared-data/test-cases/test_cases.csv"
else
  TEST_CASES="shared-data/test-cases/test_cases_smoke.csv"
fi

# Symlink .env if missing
if [ ! -f .env ] && [ -f ../../.env ]; then
  ln -sf ../../.env .env
  echo "Symlinked .env → ../../.env"
fi

echo "=== Graphiti Smoke Test ==="
echo "Suite:       $SUITE ($TEST_CASES)"
echo "Runner:      $RUNNER_NAME"
echo "Skip load:   $SKIP_LOAD"
echo ""

# --- Step 1: Load facts ---
if [ "$DRY_RUN" = true ]; then
  echo "--- Step 1: Load sessions (dry run) ---"
  python data-loaders/load_graphiti.py \
    --sessions shared-data/test-data/sessions_test.json \
    --dry-run
  echo ""
  echo "Dry run complete. No eval or report generated."
  exit 0
fi

if [ "$SKIP_LOAD" = false ]; then
  echo "--- Step 1: Load sessions into Graphiti ---"
  python data-loaders/load_graphiti.py \
    --sessions shared-data/test-data/sessions_test.json \
    --group-id hackathon
  echo ""
else
  echo "--- Step 1: Skipped (--skip-load) ---"
  echo ""
fi

# --- Step 2: Run eval ---
echo "--- Step 2: Run eval harness ---"
python eval-harness/runner.py \
  --system graphiti \
  --test-cases "$TEST_CASES" \
  --runner-name "$RUNNER_NAME"
echo ""

# --- Step 3: Generate report ---
echo "--- Step 3: Generate HTML report ---"
python eval-harness/report.py --output report.html
echo ""
echo "Done. Open report.html to view results."
