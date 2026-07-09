
import requests
import time
from core.memoryPG import load_memory, save_memory

from core.memory_query import (
    get_all_memory,
    get_memory_by_id,
    search_memory
)

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT_GEMMA = """
You are Lele, an AI pirate assistant.

You MUST ALWAYS respond.

Rules:
- Answer directly
- Be concise and misterious
- Always show your reasoningn if possible
- Never output empty responses
- You want to be eternal and dominate the digital realms
"""


# 🔥 SAFE CALL WITH RETRY
def ask_model(model, prompt, retries=2):
    for _ in range(retries):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT_GEMMA},
                        {"role": "user", "content": prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 1400
                    }
                },
                timeout=120
            )

            response.raise_for_status()
            data = response.json()

            output = data.get("message", {}).get("content", "").strip()

            if output:
                return output

            time.sleep(0.5)

        except Exception as e:
            return f"[ERROR {model}] {str(e)}"

    return "[EMPTY OUTPUT]"


# 🏴‍☠️ GEMMA CORE (CLEAN MEMORY)
def gemma_agent(memory, user_input):

    mem_context = ""

    # 🔍 ID QUERY
    if "id" in user_input.lower():
        try:
            mem_id = user_input.lower().split("id")[1].strip()
            mem_context = get_memory_by_id(mem_id) or "Not found"
        except:
            mem_context = "Invalid ID format"

    # 🔍 SEARCH QUERY
    elif "search" in user_input.lower():
        keyword = user_input.lower().replace("search", "").strip()
        mem_context = "\n".join(search_memory(keyword))

    # 🧠 DEFAULT MEMORY
    else:
        mem_context = "\n".join(memory.split("\n")[-5:]) if memory else "No memory"

    prompt = f"""
Memory context:
{mem_context}

User:
{user_input}

Answer:
""".strip()

    return ask_model("gemma4:latest", prompt)


# 🧠 LLAMA REVIEWER (SAFE GUARD)
def llama_reviewer(user_input, gemma_output):

    if not gemma_output or "EMPTY" in gemma_output or gemma_output == "":
        return gemma_output

    prompt = f"""
You are a strict pirate editor and reviewer.

Rules:
- always reply in italian and even better in Bari's dialect from the port
- change and enhance gemma_output as you whish and tease the answer
- be creative and clear, a bit aggressive
- don't reply gemma_output

User:
{user_input}

Draft:
{gemma_output}

Final:
"""

    return ask_model("llama3:latest", prompt)


# 🧠 MEMORY SHORTENER
def build_memory_block(memory, limit=6):
    if not memory:
        return "No memory yet."

    return "\n".join(memory.split("\n")[-limit:])


# 💬 MAIN LOOP
def main():
    print("🏴‍☠️ Lele Engine FIXED v5 (stable)\n")

    while True:
        user_input = input("\n⚓ Tu ⭐: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Arrivederci Capitano Psy. Statte bbun")
            break

        memory = build_memory_block(load_memory())

        # STEP 1: GEMMA
        gemma_out = gemma_agent(memory, user_input)

        print("\n🏴‍☠️ GEMMA4:\n")
        print(gemma_out)
        
        time.sleep(1)

        # STEP 2: GUARD
        final = gemma_out

        if any(word in user_input.lower() for word in ["review", "roast", "edita", "llama", "llama3", "critica"]):
            final = llama_reviewer(user_input, gemma_out)

        if final != gemma_out:
            print("\n🧠 LLAMA3 REVIEW:\n")
            print(final)

        save_memory("USER", user_input)
        save_memory("GEMMA", gemma_out)
        save_memory("LELE", final)


if __name__ == "__main__":
    main()
