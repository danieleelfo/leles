import requests
from core.memoryPG import load_memory, save_memory

OLLAMA_URL = "http://localhost:11434/api/generate"


# 🏴‍☠️ GEMMA SYSTEM PROMPT (FORTIFICATO)
SYSTEM_PROMPT_GEMMA = """
You are Lele, an AI pirate assistant.

You MUST ALWAYS respond.

Rules:
- Answer the user directly
- Never think out loud
- Never show reasoning steps
- Never say "Thinking..."
- Be concise and useful
- Use memory only if relevant
- If unsure, guess reasonably but stay consistent
"""


def ask_model(model, prompt):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": 300
                }
            },
            timeout=120
        )

        response.raise_for_status()
        data = response.json()

        # 🔥 debug serio
        if "error" in data:
            return f"[OLLAMA ERROR {model}] {data['error']}"

        if "response" not in data or not data["response"]:
            return f"[EMPTY RESPONSE {model}] {data}"

        return data["response"].strip()

    except Exception as e:
        return f"[REQUEST FAILED {model}] {str(e)}"


# 🏴‍☠️ GEMMA CORE
def gemma_agent(memory, user_input):

    prompt = f"""
{SYSTEM_PROMPT_GEMMA}

### MEMORY (context)
{memory}

### USER QUESTION
{user_input}

### ANSWER (Lele):
"""

    return ask_model("gemma4:latest", prompt)   # 🔥 IMPORTANT FIX


# 🧠 LLAMA REVIEWER (soft)
def llama_reviewer(user_input, gemma_output):

    if not gemma_output or "EMPTY" in gemma_output:
        return gemma_output

    prompt = f"""
You are a strict editor.

Task:
- improve clarity
- fix grammar
- DO NOT add new ideas
- keep pirate tone

USER:
{user_input}

DRAFT:
{gemma_output}

FINAL:
"""

    return ask_model("llama3:latest", prompt)


# 🧠 memory formatter
def build_memory_block(memory, limit=6):
    if not memory:
        return "No memory yet."

    lines = memory.split("\n")
    return "\n".join(lines[-limit:])


# 💬 MAIN LOOP
def main():
    print("🏴‍☠️ Lele Engine FIXED (Gemma4 stable + Llama3 review)\n")

    while True:
        user_input = input("\n⚓ Tu ⭐: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Arrivederci Capitano")
            break

        memory = build_memory_block(load_memory())

        # STEP 1: GEMMA
        gemma_out = gemma_agent(memory, user_input)

        print("\n🏴‍☠️ GEMMA4:\n")
        print(gemma_out)

        # STEP 2: LLAMA
        final = llama_reviewer(user_input, gemma_out)

        print("\n🧠 LLAMA3 REVIEW:\n")
        print(final)

        save_memory("USER", user_input)
        save_memory("GEMMA", gemma_out)
        save_memory("LELE", final)


if __name__ == "__main__":
    main()
