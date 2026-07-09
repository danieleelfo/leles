"""
self_improver.py
================
Step 1 — Does a task using Ollama (llama3) locally.
Step 2 — Reads its own source code (__file__) and asks Claude
         to produce an enhanced version, saved as self_improver_v2.py

Requirements:
    pip install anthropic requests

Ollama must be running:
    ollama serve
    ollama pull llama3

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python self_improver.py
"""

import os
import re
import requests
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "llama3"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL    = "claude-sonnet-4-20250514"

# ── Step 1: Do something useful with Ollama ───────────────────────────────────

def run_ollama_task(prompt: str) -> str:
    """Send a prompt to Ollama and return the response."""
    print(f"\n🟡 Ollama ({OLLAMA_MODEL}) — running task...\n")
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=180,
    )
    response.raise_for_status()
    result = response.json()["response"].strip()
    print(result)
    return result


# ── Step 2: Read own source and ask Claude to enhance it ──────────────────────

def enhance_self():
    """Read this script's own source and ask Claude to produce a better version."""
    print("\n🔵 Claude — reading and enhancing this script...\n")

    # Read own source code
    script_path = os.path.abspath(__file__)
    with open(script_path, "r") as f:
        source_code = f.read()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=(
            "You are a senior Python engineer. "
            "You will receive a Python script that uses Ollama for local LLM inference. "
            "Your job is to produce a complete, enhanced version of it.\n\n"
            "Improvements to consider:\n"
            "- Add type hints and docstrings\n"
            "- Add proper error handling (network failures, missing env vars, timeouts)\n"
            "- Add logging instead of bare prints\n"
            "- Add argparse so the user can pass a custom prompt from CLI\n"
            "- Improve modularity and readability\n"
            "- Keep the self-enhancement step (Step 2) intact and working\n\n"
            "Return ONLY the improved Python code inside a ```python ... ``` block. "
            "No explanation outside the code block."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is the script to enhance:\n\n```python\n{source_code}\n```"
                ),
            }
        ],
    )

    full_response = message.content[0].text.strip()

    # Extract code block
    match = re.search(r"```(?:python)?\n(.*?)```", full_response, re.DOTALL)
    enhanced_code = match.group(1).strip() if match else full_response

    # Save next to original with _v2 suffix
    base, ext = os.path.splitext(script_path)
    output_path = f"{base}_v2{ext}"
    with open(output_path, "w") as f:
        f.write(enhanced_code)

    print(f"✅ Enhanced script saved → {output_path}")
    return output_path


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        print("⚠️  ANTHROPIC_API_KEY is not set.")
        print("   Export it first:  export ANTHROPIC_API_KEY=sk-ant-...")
        exit(1)

    # ── Step 1: your Ollama task (edit this prompt freely) ──
    task_prompt = (
        "Explain in 3 bullet points why Python is a good language for data engineering."
    )
    ollama_result = run_ollama_task(task_prompt)

    # ── Step 2: self-enhance via Claude ──
    print("\n" + "=" * 60)
    print("🔁 Now enhancing this script using Claude...")
    print("=" * 60)
    enhance_self()
