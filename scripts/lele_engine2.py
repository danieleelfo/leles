import requests
from core.memoryPG import load_memory, save_memory

OLLAMA_URL = "http://localhost:11434/api/generate"


# 🏴‍☠️ LELE = GEMMA
SYSTEM_PROMPT_GEMMA = """
Sei Lele.

Sei un assistente AI pirata.
Ironico, diretto, intelligente e pratico.

Regole:
- rispondi alla domanda dell'utente
- non inventare contesto
- non fare monologhi inutili
- sii sintetico quando possibile
- usa la memoria se è rilevante
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
                    "num_predict": 350
                }
            },
            timeout=120
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:
            return f"[OLLAMA ERROR {model}] {data['error']}"

        if "response" not in data:
            return f"[NO RESPONSE FIELD {model}] {data}"

        return data["response"].strip()

    except Exception as e:
        return f"[REQUEST FAILED {model}] {str(e)}"


# 🏴‍☠️ Gemma = Lele
def gemma_agent(memory, user_input):
    prompt = f"""
{SYSTEM_PROMPT_GEMMA}

=== MEMORIA ===
{memory}

=== USER ===
{user_input}

=== LELE ===
"""

    return ask_model("gemma4", prompt)


# 🧠 Llama = revisore
def llama_reviewer(user_input, gemma_output):

    if not gemma_output:
        return "[LLAMA REVIEW SKIPPED]"

    prompt = f"""
Sei un revisore tecnico.

Controlla la risposta.

Regole:
- correggi errori evidenti
- se la risposta è già buona, restituiscila quasi identica
- non aggiungere storie
- non cambiare il significato

DOMANDA:
{user_input}

RISPOSTA:
{gemma_output}

VERSIONE FINALE:
"""

    return ask_model("llama3", prompt)


def build_memory_block(memory, limit=6):
    if not memory:
        return "Nessuna memoria disponibile."

    lines = memory.split("\n")
    return "\n".join(lines[-limit:])


def main():
    print("🏴‍☠️ Lele avviato (Gemma4 + Llama3 Reviewer)\n")

    while True:

        user_input = input("\n⚓ Tu ⭐: ")

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Lele si ritira nei mari del codice affondato...")
            break

        memory = build_memory_block(load_memory())

        # STEP 1: GEMMA
        gemma_out = gemma_agent(memory, user_input)

        print("\n🏴‍☠️ GEMMA4 (Lele):\n")
        print(gemma_out)

        # STEP 2: LLAMA
        final_response = llama_reviewer(user_input, gemma_out)

        print("\n🧠 LLAMA3 (review):\n")
        print(final_response)

        save_memory("USER", user_input)
        save_memory("GEMMA", gemma_out)
        save_memory("LELE", final_response)


if __name__ == "__main__":
    main()
