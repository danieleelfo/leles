import requests

OLLAMA_URL = "http://localhost:11434/api/generate"

payload = {
    "model": "llama3",
    "prompt": """
Sei Lele, un assistente AI pirata intelligente.
Hai memoria delle conversazioni.
Rispondi in modo diretto, ironico, leggermente sarcastico.
Non sei un chatbot generico: sei un'entità con continuità.
Domanda: chi sei?
""",
    "stream": False
}

def main():
    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()

        data = response.json()
        print("\n🤖 LELE RISPOSTA:\n")
        print(data["response"])

    except Exception as e:
        print("❌ Errore:", e)


if __name__ == "__main__":
    main()
