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


class Question(BaseModel):
    message: str


@app.post("/ask")
def ask_lele(q: Question):
    user_input = q.message.strip()

    print(f"INPUT = {user_input}")

    if not user_input:
        return {"answer": "⚓ Capitano, dimmi qualcosa!", "type": "empty"}

    memory = build_memory_block(load_memory_by_suffix("ES"))

    trigger_db = is_query_trigger(user_input)
    trigger_improve = user_input.lower().startswith("improve")
    trigger_export = user_input.lower().startswith("esporta")
    trigger_llama = any(word in user_input.lower() for word in ["edita", "review", "roast", "llama", "llama3", "critica"])
    
    print(
        f"EXPORT = {trigger_export} | "
        f"DB = {trigger_db} | "
        f"LLAMA = {trigger_llama} | "
        f"IMPROVE = {trigger_improve}"
    )

    # IMPROVE — disabilitato via Telegram per sicurezza (modifica file locali)
    if trigger_improve:
        save_memory("USER_ES", user_input)
        return {
            "answer": "🏴‍☠️ Il comando IMPROVE è disabilitato via Telegram per motivi di sicurezza (modifica file sul Mac).",
            "type": "improve_disabled"
        }

    elif trigger_db:
        formatted, lele_answer = db_agent(user_input)
        save_memory("USER_ES", user_input)
        save_memory("LELE_DB_ES", lele_answer)
        return {
            "answer": lele_answer,
            "data": formatted,
            "type": "db"
        }
        
    elif trigger_export:
        print("######## EXPORT AGENT ########")
        print(f"Comando: {user_input}")

        result = export_agent(user_input)

        save_memory("USER_ES", user_input)
        save_memory("LELE_EXPORT_ES", result)

        return {
            "answer": result,
            "type": "export"
        }

    elif trigger_llama:
        last_gemma = get_memory_by_role("GEMMA_ES")
        final = llama_reviewer(user_input, last_gemma)
        save_memory("USER_ES", user_input)
        save_memory("LELE_ES", final)
        return {
            "answer": final,
            "type": "llama_review"
        }

    else:
        gemma_out = gemma_agent(memory, user_input)
        save_memory("USER_ES", user_input)
        save_memory("GEMMA_ES", gemma_out)
        return {
            "answer": gemma_out,
            "type": "gemma"
        }

@app.get("/health")
def health():
    return {"status": "ok", "engine": "Lelé v9 ES"}
