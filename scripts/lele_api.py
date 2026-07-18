"""
lele_api.py — Wrapper FastAPI per Lele Engine v9.

Esegui dalla cartella principale del progetto Lelé (stessa cartella di lele_engine9.py):
    uvicorn lele_api:app --reload --port 8001

Il routing (quale agente gestisce quale messaggio) è delegato al
Timoniere (scripts/timoniere.py) — qui restano solo l'esecuzione di
ogni agente e il salvataggio in memoria del risultato.
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
)

from scripts.export_agent import export_agent
from scripts.verify_agent import verify_agent
from scripts.git_agent import git_pull, git_status
from scripts.process_agent import restart_bar_ai

from scripts.timoniere import (
    route,
    extract_project,
    AGENT_RESTART_LELES,
    AGENT_RESTART_BAR_AI,
    AGENT_GIT_PULL,
    AGENT_GIT_STATUS,
    AGENT_IMPROVE,
    AGENT_VERIFY,
    AGENT_EXPORT,
    AGENT_QUERY,
    AGENT_LLAMA,
    AGENT_GEMMA,
)

app = FastAPI()

# Deve combaciare con ADMIN_IDS in scripts/leles_bot.py — query/esporta/improve/
# verifica/git sono comandi di debug/analisi, riservati al capitano.
ADMIN_IDS = [8733881519]

# Agenti che richiedono privilegi admin (tutti tranne llama/gemma, che
# restano aperti a tutti gli utenti Leles).
_ADMIN_ONLY_AGENTS = {
    AGENT_IMPROVE,
    AGENT_VERIFY,
    AGENT_EXPORT,
    AGENT_QUERY,
    AGENT_GIT_PULL,
    AGENT_GIT_STATUS,
    AGENT_RESTART_LELES,
    AGENT_RESTART_BAR_AI,
}


class Question(BaseModel):
    message: str
    chat_id: int | None = None


def _denied(agent_type: str) -> dict:
    return {
        "answer": "🏴‍☠️ Comando riservato al capitano.",
        "type": f"{agent_type}_disabled",
    }


@app.post("/ask")
def ask_lele(q: Question):
    user_input = q.message.strip()

    print(f"INPUT = {user_input}")

    if not user_input:
        return {"answer": "⚓ Capitano, dimmi qualcosa!", "type": "empty"}

    is_admin = q.chat_id in ADMIN_IDS
    agent = route(user_input)

    print(f"TIMONIERE → {agent} (admin={is_admin})")

    # I comandi riservati passano tutti dallo stesso check, un solo posto.
    if agent in _ADMIN_ONLY_AGENTS and not is_admin:
        return _denied(agent)

    # ---------------------------------------------------------------
    # PROCESS AGENT — restart Leles: non eseguibile qui, richiede di
    # agire sul processo del bot Telegram stesso (os.execv), quindi
    # vive in leles_bot.py e non dovrebbe mai arrivare fin qui (il bot
    # lo intercetta prima di chiamare /ask). Se ci arriva comunque, lo
    # segnaliamo invece di far crashare la richiesta.
    # ---------------------------------------------------------------
    if agent == AGENT_RESTART_LELES:
        return {
            "answer": "🔄 Il restart di Leles va lanciato direttamente da Telegram (comando 'restart Lelé'), non tramite /ask.",
            "type": "restart_unavailable",
        }

    # PROCESS AGENT — restart bar_ai: bar_ai è un processo ESTERNO a
    # Leles, quindi si può eseguire direttamente qui, senza bisogno di
    # riavviare Leles stesso.
    if agent == AGENT_RESTART_BAR_AI:
        print("######## PROCESS AGENT (restart bar_ai) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = restart_bar_ai()
        save_memory("LELE_PROCESS_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_RESTART_BAR_AI}

    if agent == AGENT_GIT_PULL:
        project = extract_project(user_input)
        print(f"######## GIT AGENT (pull, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = git_pull(project)
        save_memory("LELE_GIT_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_GIT_PULL}

    if agent == AGENT_GIT_STATUS:
        project = extract_project(user_input)
        print(f"######## GIT AGENT (status, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = git_status(project)
        save_memory("LELE_GIT_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_GIT_STATUS}

    if agent == AGENT_IMPROVE:
        print("######## IMPROVE AGENT ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        filepath = user_input[7:].strip()
        print(f"Filepath: {filepath}")
        result = improve_agent(filepath)
        save_memory("LELE_IMPROVE_ES", result or "Nessun suggerimento generato.", chat_id=q.chat_id)

        return {
            "answer": result or "Nessun suggerimento generato.",
            "type": AGENT_IMPROVE,
        }

    if agent == AGENT_VERIFY:
        print("######## VERIFY AGENT ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        filepath = user_input[len("verifica"):].strip()
        print(f"Filepath: {filepath}")
        result = verify_agent(filepath)
        save_memory("LELE_VERIFY_ES", result, chat_id=q.chat_id)

        return {"answer": result, "type": AGENT_VERIFY}

    if agent == AGENT_QUERY:
        print("######## QUERY AGENT ########")
        print(f"Comando: {user_input}")
        formatted, lele_answer = db_agent(user_input)
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        save_memory("LELE_DB_ES", lele_answer, chat_id=q.chat_id)
        return {
            "answer": lele_answer,
            "data": formatted,
            "type": AGENT_QUERY,
        }

    if agent == AGENT_EXPORT:
        print("######## EXPORT AGENT ########")
        print(f"Comando: {user_input}")

        result = export_agent(user_input)

        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        save_memory("LELE_EXPORT_ES", result, chat_id=q.chat_id)

        return {"answer": result, "type": AGENT_EXPORT}

    if agent == AGENT_LLAMA:
        print("######## OLLAMA AGENT (llama review) ########")
        print(f"Comando: {user_input}")
        last_gemma = get_memory_by_role("GEMMA_ES", chat_id=q.chat_id)
        final = llama_reviewer(user_input, last_gemma, chat_id=q.chat_id)
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        save_memory("LELE_ES", final, chat_id=q.chat_id)
        return {"answer": final, "type": AGENT_LLAMA}

    # AGENT_GEMMA — fallback finale
    print("######## OLLAMA AGENT (gemma) ########")
    print(f"Comando: {user_input}")
    memory = build_memory_block(load_memory_by_suffix("ES", chat_id=q.chat_id))
    gemma_out = gemma_agent(memory, user_input, chat_id=q.chat_id)
    save_memory("USER_ES", user_input, chat_id=q.chat_id)
    save_memory("GEMMA_ES", gemma_out, chat_id=q.chat_id)
    return {"answer": gemma_out, "type": AGENT_GEMMA}


@app.get("/health")
def health():
    return {"status": "ok", "engine": "Lelé v9 ES"}
