"""
lele_api.py — Wrapper FastAPI per Lele Engine v9.

Esegui dalla cartella principale del progetto Lelé (stessa cartella di lele_engine9.py):
    uvicorn lele_api:app --reload --port 8001

Replica la logica del dispatcher di main() in lele_engine9.py,
ma esposta come endpoint HTTP /ask invece del loop input().
"""

from fastapi import FastAPI
from pydantic import BaseModel

from core.memoryPG import (
    load_memory_by_suffix,
    save_memory,
    get_memory_by_role
)

from scripts.db_agent import generate_sql, execute_sql, format_results, interpret_results
from scripts.improver_agent import improve_agent

from scripts.lele_engine9 import (
    gemma_agent,
    llama_reviewer,
    db_agent,
    build_memory_block,
    is_query_trigger,
)
app = FastAPI()

from scripts.export_agent import export_agent
from scripts.verify_agent import verify_agent

# Deve combaciare con ADMIN_IDS in scripts/leles_bot.py — query/esporta/improve
# sono comandi di debug/analisi, riservati al capitano.
ADMIN_IDS = [8733881519]


class Question(BaseModel):
    message: str
    chat_id: int | None = None


@app.post("/ask")
def ask_lele(q: Question):
    user_input = q.message.strip()

    print(f"INPUT = {user_input}")

    if not user_input:
        return {"answer": "⚓ Capitano, dimmi qualcosa!", "type": "empty"}

    memory = build_memory_block(load_memory_by_suffix("ES", chat_id=q.chat_id))

    is_admin = q.chat_id in ADMIN_IDS

    trigger_db = is_query_trigger(user_input)
    trigger_improve = user_input.lower().startswith("improve")
    trigger_verify = user_input.lower().startswith(("verifica", "verify"))
    trigger_export = user_input.lower().startswith(("esporta", "esport", "export"))
    trigger_llama = any(word in user_input.lower() for word in ["edita", "review", "roast", "llama", "llama3", "critica", "pirata"])
    trigger_gemma = not (trigger_improve or trigger_verify or trigger_export or trigger_db or trigger_llama)

    print(
        f"EXPORT = {trigger_export} | "
        f"DB = {trigger_db} | "
        f"LLAMA = {trigger_llama} | "
        f"IMPROVE = {trigger_improve} | "
        f"VERIFY = {trigger_verify} | "
        f"GEMMA = {trigger_gemma}"
    )

    # IMPROVE — riservato al capitano: legge un file e genera suggerimenti
    # (gemma review + llama enhance), non scrive/modifica mai nulla sul Mac.
    if trigger_improve:
        print("######## IMPROVE AGENT ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        if not is_admin:
            return {
                "answer": "🏴‍☠️ Comando riservato al capitano.",
                "type": "improve_disabled"
            }

        filepath = user_input[7:].strip()
        print(f"Filepath: {filepath}")
        result = improve_agent(filepath)
        save_memory("LELE_IMPROVE_ES", result or "Nessun suggerimento generato.", chat_id=q.chat_id)

        return {
            "answer": result or "Nessun suggerimento generato.",
            "type": "improve"
        }

    elif trigger_verify:
        print("######## VERIFY AGENT ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        if not is_admin:
            return {
                "answer": "🏴‍☠️ Comando riservato al capitano.",
                "type": "verify_disabled"
            }

        filepath = user_input[len("verifica"):].strip()
        print(f"Filepath: {filepath}")
        result = verify_agent(filepath)
        save_memory("LELE_VERIFY_ES", result, chat_id=q.chat_id)

        return {
            "answer": result,
            "type": "verify"
        }

    elif trigger_db:
        if not is_admin:
            return {
                "answer": "🏴‍☠️ Comando riservato al capitano.",
                "type": "db_disabled"
            }

        print("######## DB AGENT ########")
        print(f"Comando: {user_input}")
        formatted, lele_answer = db_agent(user_input)
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        save_memory("LELE_DB_ES", lele_answer, chat_id=q.chat_id)
        return {
            "answer": lele_answer,
            "data": formatted,
            "type": "db"
        }
        
    elif trigger_export:
        if not is_admin:
            return {
                "answer": "🏴‍☠️ Comando riservato al capitano.",
                "type": "export_disabled"
            }

        print("######## EXPORT AGENT ########")
        print(f"Comando: {user_input}")

        result = export_agent(user_input)

        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        save_memory("LELE_EXPORT_ES", result, chat_id=q.chat_id)

        return {
            "answer": result,
            "type": "export"
        }

    elif trigger_llama:
        print("######## LELÉ AGENT ########")
        print(f"Comando: {user_input}")
        last_gemma = get_memory_by_role("GEMMA_ES", chat_id=q.chat_id)
        final = llama_reviewer(user_input, last_gemma, chat_id=q.chat_id)
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        save_memory("LELE_ES", final, chat_id=q.chat_id)
        return {
            "answer": final,
            "type": "llama_review"
        }

    else:
        print("######## GEMMA AGENT ########")
        print(f"Comando: {user_input}")
        gemma_out = gemma_agent(memory, user_input, chat_id=q.chat_id)
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        save_memory("GEMMA_ES", gemma_out, chat_id=q.chat_id)
        return {
            "answer": gemma_out,
            "type": "gemma"
        }

@app.get("/health")
def health():
    return {"status": "ok", "engine": "Lelé v9 ES"}
