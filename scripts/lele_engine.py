import requests
from core.memoryPG import load_memory, save_memory

OLLAMA_URL = "http://localhost:11434/api/generate"


# 🏴‍☠️ System prompts
SYSTEM_PROMPT_LLAMA = """
Sei Lele nella sua fase creativa.
Sei un pirata AI ironico, diretto, creativo.
Rispondi in modo utile e sintetico.
"""

SYSTEM_PROMPT_GEMMA = """
Sei il revisore critico di Lele.
Sei preciso e diretto.

Obiettivo:
- migliorare la risposta
- correggere errori
- mantenere tono pirata
- NON essere poetico
- rispondi sempre completamente
"""


# 📡 Ollama client robusto
def ask_model(model, prompt):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": 350
                }
            },
            timeout=120
        )

        response.raise_for_status()
        data = response.json()

        # 🔥 DEBUG IMPORTANTE
        if "error" in data:
            return f"[OLLAMA ERROR {model}] {data['error']}"

        if "response" not in data:
            return f"[NO RESPONSE FIELD {model}] {data}"

        return data["response"].strip()

    except Exception as e:
        return f"[REQUEST FAILED {model}] {str(e)}"


# 🧠 Llama agent (creativo)
def llama_agent(memory, user_input):
    prompt = f"""
{SYSTEM_PROMPT_LLAMA}

MEMORIA:
{memory}

USER:
{user_input}

RISPOSTA:
"""
    return ask_model("llama3", prompt)


# ⚔️ Gemma agent (critico)
def gemma_agent(memory, llama_output, user_input):

    if not llama_output:
        return "[Gemma skipped: empty input]"

    prompt = f"""
Sei un editor.

Migliora questa risposta.

DOMANDA:
{user_input}

RISPOSTA:
{llama_output}

RISPOSTA MIGLIORATA:
"""

    return ask_model("gemma4", prompt)


# 🧾 memory safe
def build_memory_block(memory, limit=6):
    if not memory:
        return "Nessuna memoria disponibile."

    lines = memory.split("\n")
    return "\n".join(lines[-limit:])


def main():
    print("🏴‍☠️ Lele Multi-Agent Engine avviato (llama3 + gemma4)\n")

    while True:
        user_input = input("\n⚓ Tu ⭐: ")

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Lele si ritira nei mari del codice...")
            break

        # 📥 memoria (limitata!)
        memory = build_memory_block(load_memory())

        # 🧠 Llama crea
        llama_out = llama_agent(memory, user_input)
        llama_out = llama_out[:800]   # 🔥 importantissimo

        print("\n🧠 LLAMA3 (bozza):\n")
        print(llama_out[:800])  # debug safe cut

        # ⚔️ Gemma rifinisce
        final_response = gemma_agent(memory, llama_out, user_input)

        print("\n🏴‍☠️ GEMMA4 (finale Lele):\n")
        print(final_response)

        # 💾 salva memoria
        save_memory("USER", user_input)
        save_memory("LLAMA", llama_out)
        save_memory("LELE", final_response)


if __name__ == "__main__":
    main()
