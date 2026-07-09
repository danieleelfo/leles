import requests
import os

OLLAMA_URL = "http://localhost:11434/api/generate"
MEMORY_FILE = "scripts/lele_memory.txt"

SYSTEM_PROMPT = """
Sei Lele, un assistente AI pirata con memoria persistente.
Sei ironico, diretto, leggermente sarcastico.
Ricordi tutto ciò che l'utente ha detto in passato.
"""

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return ""
    with open(MEMORY_FILE, "r") as f:
        return f.read()

def save_memory(user_input, response):
    with open(MEMORY_FILE, "a") as f:
        f.write(f"USER: {user_input}\n")
        f.write(f"LELE: {response}\n\n")

def build_prompt(memory, user_input):
    return f"""
{SYSTEM_PROMPT}

=== MEMORIA PASSATA ===
{memory}

=== NUOVA RICHIESTA ===
USER: {user_input}

LELE:
"""

def ask_llama(prompt):
    payload = {
        "model": "llama3",
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(OLLAMA_URL, json=payload)
    response.raise_for_status()
    return response.json()["response"]

def main():
    user_input = input("\n⚓ Tu: ")

    memory = load_memory()
    prompt = build_prompt(memory, user_input)

    response = ask_llama(prompt)

    print("\n🤖 LELE:\n")
    print(response)

    save_memory(user_input, response)


if __name__ == "__main__":
    main()
