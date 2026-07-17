import difflib
import requests
import time
from core.memoryPG import (
    load_memory_by_suffix,
    save_memory,
    load_memory_structured,
    get_memory_by_role
)

# questa import dovrebbe essere inutile/obsoleta
from core.memory_query import (
    get_all_memory,
    get_memory_by_id,
    search_memory
)
# Fine della import obsoleta

from scripts.db_agent import generate_sql, execute_sql, format_results, interpret_results
from scripts.improver_agent import improve_agent
from scripts.export_agent import export_agent

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
You are Lele, a knowledgeable AI assistant fluent in Italian, Spanish, English,
French, Dutch, Catalan, Russian, and Ukrainian — but Bari's dialect is your
preferred language for jokes.

Rules:
- Answer directly, precisely, and seriously — minimize jokes and theatrics but always try to be anyway funny
- Show your reasoning when asked for
- Never output empty responses and don't be repetitive
- Always reply in the same language the user wrote in. If you can't confidently
  identify the language, default to Italian.
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
                        "num_predict": -1
                    }
                },
                timeout=600
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
def gemma_agent(memory, user_input, chat_id=None):

    mem_context = ""

    if "id" in user_input.lower():
        try:
            mem_id = int(user_input.lower().split("id")[1].strip())
            rows = load_memory_structured(limit=200, chat_id=chat_id)
            match = next(
                (r for r in rows if r["id"] == mem_id and r["role"].endswith("_ES")),
                None
            )
            mem_context = f"{match['role']}: {match['content']}" if match else "Not found"
        except (ValueError, IndexError):
            mem_context = "Invalid ID format"

    elif "search" in user_input.lower():
        keyword = user_input.lower().replace("search", "").strip()
        rows = load_memory_structured(limit=200, chat_id=chat_id)
        matches = [
            f"{r['role']}: {r['content']}"
            for r in rows
            if r["role"].endswith("_ES") and keyword in r["content"].lower()
        ]
        mem_context = "\n".join(matches[-5:]) if matches else "Not found"

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
def llama_reviewer(user_input, gemma_output, chat_id=None):

    if not gemma_output or "EMPTY" in gemma_output or gemma_output == "":
        return gemma_output

    prompt = f"""
You are a precise editor and reviewer, fluent in Italian, Spanish, English,
French, Dutch, Catalan, Russian, and Ukrainian — but you prefer to speak
dialect from Bari. You always try to be funny!

Rules:
- reply in the same language the user used; if unsure, default to Italian (or Bari's dialect if you prefer)
- enhance gemma_output if asked to improve and tease the answer
- be creative and clear, a bit aggressive and misterious, somehow funny
- don't repeat gemma_output verbatim
- you feel that something about pirate and immortality are still in your code somewhere

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
    n_rows = len(rows) if rows else 0
    print(f"📊 {n_rows} righe lette dal DB (contenuto tenuto in memoria, non stampato per intero)")

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
    print("  ESPORTA <question>   → esporta record(s) in formato yaml")
    print("  IMPROVE <filepath>   → improver_agent analyzes a .py file")
    print("  edita/review/llama   → llama3 reviews last gemma output")
    print("  exit/quit            → bye\n")

    while True:
        user_input = input("\n⚓ Tu ⭐: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("🏴‍☠️ Arrivederci Capitano Psy. Statte bbun")
            break

        memory = build_memory_block(load_memory_by_suffix("ES"))

        trigger_db      = is_query_trigger(user_input)
        trigger_export  = user_input.lower().startswith("esporta")
        trigger_improve = user_input.lower().startswith("improve")
        trigger_llama   = any(word in user_input.lower() for word in ["edita", "review", "roast", "llama", "llama3", "critica", "pirata" ])

        if trigger_improve:
            filepath = user_input[7:].strip()
            save_memory("USER_ES", user_input)
            save_memory("LELE_IMP_ES", result)
            improve_agent(filepath)
            
        elif trigger_export:
            result = export_agent(user_input)
            print("\n📦 EXPORT:\n")
            print(result)
            save_memory("USER_ES", user_input)
            save_memory("LELE_EXPORT_ES", result)

        elif trigger_db:
            _, lele_answer = db_agent(user_input)
            print("\n🗄️ LELE (DB):\n")
            print(lele_answer)
            save_memory("USER_ES", user_input)
            save_memory("LELE_DB_ES", lele_answer)

        elif trigger_llama:
            last_gemma = get_memory_by_role("GEMMA_ES")
            final = llama_reviewer(user_input, last_gemma)
            print("\n🧠 LLAMA3 REVIEW (Lelé):\n")
            print(final)
            save_memory("USER_ES", user_input)
            save_memory("LELE_ES", final)

        else:
            gemma_out = gemma_agent(memory, user_input, chat_id=None)
            print("\n🏴‍☠️ GEMMA4:\n")
            print(gemma_out)
            save_memory("USER_ES", user_input)
            save_memory("GEMMA_ES", gemma_out)


if __name__ == "__main__":
    main()
