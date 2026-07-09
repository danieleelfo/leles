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
    load_memory,
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


class Question(BaseModel):
    message: str


@app.post("/ask")
def ask_lele(q: Question):
    user_input = q.message.strip()

    if not user_input:
        return {"answer": "⚓ Capitano, dimmi qualcosa!", "type": "empty"}

    memory = build_memory_block(load_memory())

    trigger_db = is_query_trigger(user_input)
    trigger_improve = user_input.lower().startswith("improve")
    trigger_llama = any(word in user_input.lower() for word in ["edita", "review", "roast", "llama", "llama3", "critica"])

    # IMPROVE — disabilitato via Telegram per sicurezza (modifica file locali)
    if trigger_improve:
        save_memory("USER", user_input)
        return {
            "answer": "🏴‍☠️ Il comando IMPROVE è disabilitato via Telegram per motivi di sicurezza (modifica file sul Mac).",
            "type": "improve_disabled"
        }

    elif trigger_db:
        formatted, lele_answer = db_agent(user_input)
        save_memory("USER", user_input)
        save_memory("LELE_DB", lele_answer)
        return {
            "answer": lele_answer,
            "data": formatted,
            "type": "db"
        }

    elif trigger_llama:
        last_gemma = get_memory_by_role("GEMMA")
        final = llama_reviewer(user_input, last_gemma)
        save_memory("USER", user_input)
        save_memory("LELE", final)
        return {
            "answer": final,
            "type": "llama_review"
        }

    else:
        gemma_out = gemma_agent(memory, user_input)
        save_memory("USER", user_input)
        save_memory("GEMMA", gemma_out)
        return {
            "answer": gemma_out,
            "type": "gemma"
        }


@app.get("/health")
def health():
    return {"status": "ok", "engine": "Lelé v9"}
