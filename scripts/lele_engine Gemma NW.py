import requests
from core.memoryPG import load_memory, save_memory

OLLAMA_URL = "http://localhost:11434/api/generate"

# 🏴‍☠️ System prompts per ruolo
SYSTEM_PROMPT_LLAMA = """
Sei Lele nella sua fase creativa.
Sei un pirata AI ironico, diretto, creativo.
Il tuo compito è generare una prima bozza di risposta.
Non essere troppo lungo, ma creativo e utile.
"""

SYSTEM_PROMPT_GEMMA = """
Sei il revisore critico di Lele.
Sei un pirata AI ma molto preciso.

Il tuo compito è:
- migliorare la risposta
- correggere errori
- renderla più chiara e utile
- mantenere tono ironico/pirata
- NON ripetere la bozza, ma riscriverla meglio
"""


# 📡 client Ollama generico
def ask_model(model, prompt):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }
    )

    response.raise_for_status()
    return response.json()["response"]


# 🧠 agente creativo (llama3)
def llama_agent(memory, user_input):
    prompt = f"""
{SYSTEM_PROMPT_LLAMA}

=== MEMORIA ===
{memory}

=== USER ===
{user_input}

=== BOZZA RISPOSTA ===
"""
    return ask_model("llama3", prompt)


# ⚔️ agente critico (gemma4)
def gemma_agent(memory, llama_output, user_input):
    prompt = f"""
{SYSTEM_PROMPT_GEMMA}

=== MEMORIA ===
{memory}

=== DOMANDA ORIGINALE ===
{user_input}

=== BOZZA DA MIGLIORARE ===
{llama_output}

=== RISPOSTA FINALE ===
"""
    return ask_model("gemma4", prompt)


# 🧾 costruzione memoria leggibile
def build_memory_block(memory):
    return memory if memory else "Nessuna memoria disponibile."


def main():
    print("🏴‍☠️ Lele Multi-Agent Engine avviato (llama3 + gemma4)\n")

    while True:
        user_input = input("\n⚓ Tu ⭐: ")

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Lele si ritira nei mari del codice...")
            break

        # 📥 memoria
        memory = build_memory_block(load_memory())

        # 🧠 Fase 1: Llama crea
        llama_out = llama_agent(memory, user_input)
        print("\n🧠 LLAMA3 (bozza):\n")
        print(llama_out)

        # ⚔️ Fase 2: Gemma migliora
        final_response = gemma_agent(memory, llama_out, user_input)
        print("\n🏴‍☠️ GEMMA4 (finale Lele):\n")
        print(final_response)

        # 💾 salvataggio memoria
        save_memory("USER", user_input)
        save_memory("LLAMA", llama_out)
        save_memory("LELE", final_response)


if __name__ == "__main__":
    main()
