import difflib
import requests
import time
from core.memoryPG import (
    load_memory,
    save_memory,
    get_memory_by_role
)

from core.memory_query import (
    get_all_memory,
    get_memory_by_id,
    search_memory
)

from scripts.db_agent import generate_sql, execute_sql, format_results, interpret_results
from scripts.improver_agent import improve_agent

OLLAMA_URL = "http://localhost:11434/api/chat"

# Quanto deve essere simile la prima parola a "query" per contare come trigger.
# 0.75 prende "queri"/"kuery"/"cuery" (mishearing tipici di Whisper) senza
# scattare su parole italiane comuni tipo "quello"/"questa" (che stanno ~0.55).
QUERY_TRIGGER_SIMILARITY = 0.75


def is_query_trigger(text: str) -> bool:
    """
    True se la prima parola del messaggio assomiglia abbastanza a "query".
    Serve a tollerare i piccoli errori di trascrizione vocale (Whisper a
    volte sente "queri" invece di "query" e il retrieve non partiva più).
    """
    if not text:
        return False

    first_word = "".join(ch for ch in text.strip().split(" ")[0].lower() if ch.isalnum())
    if not first_word:
        return False

    ratio = difflib.SequenceMatcher(None, first_word, "query").ratio()
    return ratio >= QUERY_TRIGGER_SIMILARITY


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


# 🏴‍☠️ GEMMA CORE
def gemma_agent(memory, user_input):

    mem_context = ""

    if "id" in user_input.lower():
        try:
            mem_id = user_input.lower().split("id")[1].strip()
            mem_context = get_memory_by_id(mem_id) or "Not found"
        except:
            mem_context = "Invalid ID format"

    elif "search" in user_input.lower():
        keyword = user_input.lower().replace("search", "").strip()
        mem_context = "\n".join(search_memory(keyword))

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


# 🧠 LLAMA REVIEWER
def llama_reviewer(user_input, gemma_output):

    if not gemma_output or "EMPTY" in gemma_output or gemma_output == "":
        return gemma_output

    prompt = f"""
You are a strict pirate editor and reviewer.

Rules:
- always reply in italian and even better in Bari's dialect from the port
- change and enhance gemma_output as you whish and tease the answer
- be creative and clear, a bit aggressive and misterious
- don't repeat gemma_output

User:
{user_input}

Draft:
{gemma_output}

Final:
"""

    return ask_model("llama3:latest", prompt)


# 🗄️ DB AGENT
def db_agent(user_input):
    if is_query_trigger(user_input):
        parts = user_input.split(" ", 1)
        question = parts[1].strip() if len(parts) > 1 else ""
    else:
        question = user_input

    print("⚙️  Generating SQL capitano...")
    sql = generate_sql(question)
    print(f"📝 SQL: {sql}\n")

    if not sql.strip().upper().startswith("SELECT"):
        return None, "❌ Only SELECT queries allowed."

    cols, rows, error = execute_sql(sql)

    if error:
        return None, f"❌ DB Error: {error}"

    formatted = format_results(cols, rows)
    print("📊 📖 Results:\n")
    print(formatted)

    lele_answer = interpret_results(question, sql, formatted)
    return formatted, lele_answer


# 🧠 MEMORY SHORTENER
def build_memory_block(memory, limit=6):
    if not memory:
        return "No memory yet."

    return "\n".join(memory.split("\n")[-limit:])


# 💬 MAIN LOOP
def main():
    print("🏴‍☠️ Lele Engine v9 (+ DB Agent + Improver)\n")
    print("Commands:")
    print("  QUERY <question>     → db_agent reads postgres")
    print("  IMPROVE <filepath>   → improver_agent analyzes a .py file")
    print("  edita/review/llama   → llama3 reviews last gemma output")
    print("  exit/quit            → bye\n")

    while True:
        user_input = input("\n⚓ Tu ⭐: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Arrivederci Capitano Psy. Statte bbun")
            break

        memory = build_memory_block(load_memory())

        trigger_db      = is_query_trigger(user_input)
        trigger_improve = user_input.lower().startswith("improve")
        trigger_llama   = any(word in user_input.lower() for word in ["edita", "review", "roast", "llama", "llama3", "critica"])

        if trigger_improve:
            filepath = user_input[7:].strip()
            save_memory("USER", user_input)
            improve_agent(filepath)

        elif trigger_db:
            _, lele_answer = db_agent(user_input)
            print("\n🗄️ LELE (DB):\n")
            print(lele_answer)
            save_memory("USER", user_input)
            save_memory("LELE_DB", lele_answer)

        elif trigger_llama:
            last_gemma = get_memory_by_role("GEMMA")
            final = llama_reviewer(user_input, last_gemma)
            print("\n🧠 LLAMA3 REVIEW (Lelé):\n")
            print(final)
            save_memory("USER", user_input)
            save_memory("LELE", final)

        else:
            gemma_out = gemma_agent(memory, user_input)
            print("\n🏴‍☠️ GEMMA4:\n")
            print(gemma_out)
            save_memory("USER", user_input)
            save_memory("GEMMA", gemma_out)


if __name__ == "__main__":
    main()
