import requests
import time
from core.db import get_connection

OLLAMA_URL = "http://localhost:11434/api/chat"

SCHEMA = """
Table: public.memory
Columns:
  - id         SERIAL PRIMARY KEY
  - role       TEXT  (values: USER, GEMMA, LELE)
  - content    TEXT
  - created_at TIMESTAMP
"""

SYSTEM_SQL = """
You are a PostgreSQL expert. Your job is to generate a single valid SELECT query and reply in natural language.

Rules:
- output raw SQL, assumptions and thinking
- No markdown, no backticks, no explanation
- Only SELECT statements allowed
- Table is public.memory
- If the user ask for your interpretation of some content you can elaborate a more extensive answer taking in consideration the db content
"""

SYSTEM_ANSWER = """
You are a helpful data assistant that explains query results clearly.
- always reply in italian and even better in Bari's dialect from the port
Be concise and direct, veloce. If results are empty, say so.
- If the user ask for your interpretation of some content you can elaborate a more extensive answer taking in consideration the db content
"""


def ask_ollama(system, prompt, model="llama3:latest"):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 500
                }
            },
            timeout=120
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"[ERROR] {str(e)}"


def generate_sql(user_question):
    prompt = f"""
Schema:
{SCHEMA}

User question:
{user_question}

SQL:
"""
    return ask_ollama(SYSTEM_SQL, prompt)


def execute_sql(sql):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        return cols, rows, None
    except Exception as e:
        return None, None, str(e)


def format_results(cols, rows):
    if not rows:
        return "No results found."
    header = " | ".join(cols)
    sep = "-" * len(header)
    lines = [header, sep]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    return "\n".join(lines)


def interpret_results(user_question, sql, formatted):
    prompt = f"""
User asked: {user_question}

SQL executed: {sql}

Results:
{formatted}

Answer:
"""
    return ask_ollama(SYSTEM_ANSWER, prompt)


def main():
    print("🗄️  DB Agent — public.memory (SELECT only)\n")

    while True:
        user_input = input("\n🔍 Query: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("👋 Ciao!")
            break

        if not user_input:
            continue

        # STEP 1: genera SQL
        print("⚙️  Generating SQL...")
        sql = generate_sql(user_input)
        print(f"📝 SQL: {sql}\n")

        # sicurezza: blocca tutto tranne SELECT
        if not sql.strip().upper().startswith("SELECT"):
            print("❌ Only SELECT queries allowed.")
            continue

        # STEP 2: esegui
        cols, rows, error = execute_sql(sql)

        if error:
            print(f"❌ DB Error: {error}")
            continue

        # STEP 3: mostra raw results
        formatted = format_results(cols, rows)
        print("📊 Results:\n")
        print(formatted)

        # STEP 4: llama interpreta
        print("\n🧠 Interpretation Agent_db:\n")
        answer = interpret_results(user_input, sql, formatted)
        print(answer)


if __name__ == "__main__":
    main()
