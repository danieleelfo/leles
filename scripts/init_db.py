import requests
from core.memoryPG import load_memory, save_memory

OLLAMA_URL = "http://localhost:11434/api/generate"

SYSTEM_PROMPT = """
Sei Lele, un assistente AI pirata.
Ironico, diretto, leggermente sarcastico.
Hai memoria persistente delle conversazioni.
Non ripeterti mai identico.
"""


def ask_llama(prompt):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        }
    )

    response.raise_for_status()
    return response.json()["response"]


def build_prompt(memory, user_input):
    return f"""
{SYSTEM_PROMPT}

=== MEMORIA ===
{memory}

=== NUOVA RICHIESTA ===
USER: {user_input}

LELE:
"""


def main():
    while True:
        user_input = input("\n⚓ Tu (exit per uscire): ")

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Lele si ritira nei mari del codice...")
            break

        memory = load_memory()

        prompt = build_prompt(memory, user_input)

        response = ask_llama(prompt)

        print("\n🤖 LELE:\n")
        print(response)

        save_memory("USER", user_input)
        save_memory("LELE", response)


if __name__ == "__main__":
    main()
