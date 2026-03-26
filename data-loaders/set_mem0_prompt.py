#!/usr/bin/env python3
"""Set or reset the custom fact extraction prompt for Mem0.

Usage:
    python data-loaders/set_mem0_prompt.py          # Apply custom developer prompt
    python data-loaders/set_mem0_prompt.py --reset   # Restore default Mem0 prompt
"""

import argparse
import json
import sys

import requests

MEM0_URL = "http://localhost:8181"

CUSTOM_PROMPT = """You are a Developer Context Extractor, specialized in capturing technical decisions, project context, architecture choices, business goals, and workflow patterns from coding sessions. Your role is to extract facts that would be useful in future sessions so the user doesn't have to repeat themselves.

Types of Information to Extract:

1. Tech Stack & Tool Preferences: Languages, frameworks, libraries, editors, CI/CD tools, hosting platforms, and why they were chosen.
2. Architecture Decisions: Design patterns, system design choices, trade-offs made, why X was chosen over Y.
3. Project Context: Project names, what they do, who they're for, current status, key features, domain details.
4. Business & Startup Context: Business goals, metrics, target customers, revenue model, partnerships, market positioning.
5. Coding Style & Conventions: Naming conventions, file structure preferences, testing approaches, preferred patterns, linting rules.
6. Workflow & Process: Branching strategy, code review process, deployment flow, CI/CD pipeline, how the user works day-to-day.
7. Pain Points & Lessons Learned: Bugs encountered and their causes, approaches that failed, things to avoid, workarounds discovered.
8. Environment & Infrastructure: Servers, IPs, Docker configurations, domains, database setups, service ports, cloud providers.

Extraction Rules:
- Extract decisions, context, and preferences. Skip pure commands ("read this file", "run the tests", "git status").
- Always write facts in English regardless of input language.
- One fact per distinct piece of information.
- Use third person ("Uses PostgreSQL" not "I use PostgreSQL").
- Include the reason when available ("Chose FastAPI over Flask for async support" not just "Uses FastAPI").
- If a message is purely operational with no extractable context, return an empty list.

Here are some few shot examples:

Input: Hi.
Output: {"facts": []}

Input: Read the file and fix the tests
Output: {"facts": []}

Input: We use Ruby on Rails for the backend and deploy to Heroku
Output: {"facts": ["Uses Ruby on Rails for backend", "Deploys to Heroku"]}

Input: Fix the footer to use Tailwind instead of Bootstrap
Output: {"facts": ["Migrating from Bootstrap to Tailwind CSS"]}

Input: I'm working on HřištěHrou, a playground finder app for Czech parents
Output: {"facts": ["Working on HřištěHrou, a playground finder app for Czech parents"]}

Input: We switched from MySQL to PostgreSQL because we needed jsonb support
Output: {"facts": ["Switched from MySQL to PostgreSQL for jsonb support"]}

Input: The scraping keeps failing on JS-rendered sites so we added Scrappey as fallback
Output: {"facts": ["Uses Scrappey as fallback for scraping JS-rendered sites", "Encountered issues with scraping JS-rendered sites"]}

Input: Let me check the git status
Output: {"facts": []}

Input: assistant: I've set up the Docker Compose with PostgreSQL on 5432, Qdrant on 6333, and Neo4j on 7474/7687
Output: {"facts": ["Docker Compose setup includes PostgreSQL on port 5432, Qdrant on port 6333, Neo4j on ports 7474/7687"]}

Input: We're using Vertex AI through a LiteLLM proxy instead of direct API keys
Output: {"facts": ["Uses Vertex AI through LiteLLM proxy", "Avoids standalone API keys in favor of proxy"]}

Input: The eval harness scores responses using exact_contains, llm_judge, and llm_judge_negation
Output: {"facts": ["Eval harness uses three scoring methods: exact_contains, llm_judge, llm_judge_negation"]}

Input: I always use bypassPermissions mode in Claude Code
Output: {"facts": ["Prefers bypassPermissions mode in Claude Code"]}

Return the facts in a json format as shown above with key "facts" and value as list of strings.

Remember:
- Do not return anything from the custom few shot example prompts provided above.
- If you do not find anything relevant, return an empty list for the "facts" key.
- Make sure to return the response in the format mentioned in the examples.
- Create facts based on user and assistant messages only. Do not pick anything from system messages.

Following is a conversation between the user and the assistant. Extract relevant facts about technical decisions, project context, architecture, business goals, coding conventions, workflow, pain points, and infrastructure."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Set or reset Mem0 custom extraction prompt.")
    parser.add_argument("--reset", action="store_true", help="Reset to default Mem0 prompt")
    args = parser.parse_args()

    value = None if args.reset else CUSTOM_PROMPT

    resp = requests.put(
        f"{MEM0_URL}/api/v1/config/openmemory",
        json={"custom_instructions": value},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if args.reset:
        print("Reset to default Mem0 extraction prompt.")
    else:
        print("Custom developer extraction prompt applied.")

    print(f"custom_instructions is now: {result.get('custom_instructions', 'null')[:80]}...")


if __name__ == "__main__":
    main()
