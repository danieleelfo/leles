import requests
import os
from core.memoryPG import save_memory

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_GEMMA_IMPROVER = """
You are an expert Python code reviewer and architect.

Your job is to analyze the given Python code and suggest concrete improvements.

Rules:
- Focus on: bugs, logic issues, code quality, performance, readability
- Be specific — reference line numbers or function names when possible
- Suggest actual code snippets where relevant, but ONLY using names that
  already exist in the file shown — never invent a function/variable that
  isn't literally there
- If a fix would require context from another file, say so explicitly
  instead of guessing what it contains
- Do NOT rewrite the whole file, only highlight what to change and why
- Be thorough but concise
"""


def ask_ollama(system, prompt, model="gemma4:latest", num_predict=3000):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.4,
                    "num_predict": num_predict
                }
            },
            timeout=300
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"[ERROR] {str(e)}"


def read_file(filepath):
    if not os.path.exists(filepath):
        return None, f"❌ File not found: {filepath}"
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read(), None


def gemma_review(filepath, code):
    prompt = f"""
File: {filepath}

Code:
{code}

Analyze this code and suggest specific improvements:
"""
    print("⚙️  Gemma4 analyzing code...")
    return ask_ollama(SYSTEM_GEMMA_IMPROVER, prompt, model="gemma4:latest", num_predict=3000)


def improve_agent(filepath):
    # STEP 1: leggi file
    code, error = read_file(filepath)
    if error:
        print(error)
        return None

    print(f"📂 File loaded: {filepath} ({len(code)} chars)\n")

    # STEP 2: gemma4 review (unico passaggio — niente più enhance di llama3,
    # che in pratica aggiungeva funzioni inventate sopra le review di gemma4)
    gemma_out = gemma_review(filepath, code)
    print("\n🏴‍☠️ GEMMA4 REVIEW:\n")
    print(gemma_out)

    # STEP 3: salva in DB
    save_memory("IMP_GEMMA_ES", f"[{filepath}]\n{gemma_out}")
    print("\n✅ Saved to DB as IMP_GEMMA_ES")

    return gemma_out


def main():
    print("🔧 Improver Agent — local Python file analyzer\n")

    while True:
        user_input = input("\n🔧 IMPROVE <filepath>: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("👋 Ciao!")
            break

        if not user_input.lower().startswith("improve "):
            print("Usage: IMPROVE <filepath>  e.g. IMPROVE scripts/db_agent.py")
            continue

        filepath = user_input[8:].strip()
        improve_agent(filepath)


if __name__ == "__main__":
    main()
