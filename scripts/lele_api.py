"""
lele_api.py — Wrapper FastAPI per Lele Engine v9.

Esegui dalla cartella principale del progetto Lelé (stessa cartella di lele_engine9.py):
    uvicorn lele_api:app --reload --port 8082

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
from scripts.git_agent import git_pull, git_pull_force, git_status
from scripts.process_agent import start_process, stop_process, restart_process, uvicorn_status, telegram_status, system_status, get_logs, get_tts_status, get_directory_listing, copy_tts_voices, install_tts_voice
from scripts.health_agent import check_ollama, check_postgres, get_uptime, get_public_ip, get_os_status, get_ram_breakdown
from scripts.airflow_agent import airflow_agent
from core.artifact_synthesizer import generate_final_artifacts

from scripts.timoniere import (
    route,
    extract_project,
    parse_directory_subpath,
    parse_tts_copy_args,
    parse_tts_install_args,
    parse_airflow_command,
    parse_synthesize_args,
    AGENT_AIRFLOW,
    AGENT_SYNTHESIZE,
    AGENT_RESTART_LELES,
    AGENT_START,
    AGENT_STOP,
    AGENT_RESTART_EXTERNAL,
    AGENT_UVICORN_STATUS,
    AGENT_TELEGRAM_STATUS,
    AGENT_SYSTEM_STATUS,
    AGENT_IP_STATUS,
    AGENT_OS_STATUS,
    AGENT_RAM_STATUS,
    AGENT_TTS_STATUS,
    AGENT_DIRECTORY,
    AGENT_TTS_COPY,
    AGENT_TTS_INSTALL,
    AGENT_GIT_PULL,
    AGENT_GIT_PULL_FORCE,
    AGENT_GIT_STATUS,
    AGENT_IMPROVE,
    AGENT_VERIFY,
    AGENT_EXPORT,
    AGENT_QUERY,
    AGENT_LLAMA,
    AGENT_GEMMA,
    AGENT_LOGS,
)

app = FastAPI()

# Deve combaciare con ADMIN_IDS in scripts/leles_bot.py — query/esporta/improve/
# verifica/git sono comandi di debug/analisi, riservati al capitano.
ADMIN_IDS = [8733881519, 8249666123]

# Agenti che richiedono privilegi admin (tutti tranne llama/gemma, che
# restano aperti a tutti gli utenti Leles).
_ADMIN_ONLY_AGENTS = {
    AGENT_AIRFLOW,
    AGENT_SYNTHESIZE,
    AGENT_IMPROVE,
    AGENT_VERIFY,
    AGENT_EXPORT,
    AGENT_QUERY,
    AGENT_GIT_PULL,
    AGENT_GIT_PULL_FORCE,
    AGENT_GIT_STATUS,
    AGENT_RESTART_LELES,
    AGENT_START,
    AGENT_STOP,
    AGENT_RESTART_EXTERNAL,
    AGENT_UVICORN_STATUS,
    AGENT_TELEGRAM_STATUS,
    AGENT_SYSTEM_STATUS,
    AGENT_LOGS,
    AGENT_TTS_COPY,
    AGENT_TTS_INSTALL,
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
    print(f"DEBUG chat_id raw = {q.chat_id!r} (type={type(q.chat_id).__name__}) — ADMIN_IDS={ADMIN_IDS} — is_admin={is_admin}")
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

    # PROCESS AGENT — start/stop/restart di progetti ESTERNI (bar_ai,
    # lele, lele_story_whisper): sono processi indipendenti da Leles,
    # si possono eseguire direttamente qui senza toccare Leles stesso.
    if agent == AGENT_START:
        project = extract_project(user_input)
        print(f"######## PROCESS AGENT (start, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = start_process(project)
        save_memory("LELE_P_START_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_START}

    if agent == AGENT_STOP:
        project = extract_project(user_input)
        print(f"######## PROCESS AGENT (stop, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = stop_process(project)
        save_memory("LELE_P_STOP_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_STOP}

    if agent == AGENT_RESTART_EXTERNAL:
        project = extract_project(user_input)
        print(f"######## PROCESS AGENT (restart, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = restart_process(project)
        save_memory("LELE_P_RESTART_EXT_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_RESTART_EXTERNAL}

    if agent == AGENT_AIRFLOW:
        dag_request = parse_airflow_command(user_input)
        print(f"######## AIRFLOW AGENT (richiesta='{dag_request}') ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = airflow_agent(dag_request)
        save_memory("LELE_AIRFLOW_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_AIRFLOW}

    if agent == AGENT_UVICORN_STATUS:
        print("######## PROCESS AGENT (uvicorn health-check) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = uvicorn_status()
        save_memory("LELE_P_UV_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_UVICORN_STATUS}

    if agent == AGENT_TELEGRAM_STATUS:
        print("######## PROCESS AGENT (telegram health-check) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = telegram_status()
        save_memory("LELE_P_TEL_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_TELEGRAM_STATUS}

    if agent == AGENT_SYSTEM_STATUS:
        print("######## HEALTH AGENT (system status) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = system_status()
        save_memory("LELE_P_SYS_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_SYSTEM_STATUS}

    if agent == AGENT_LOGS:
        project = extract_project(user_input)
        print(f"######## PROCESS AGENT (logs, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = get_logs(project)
        save_memory("LELE_P_LOGS_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_LOGS}

    if agent == AGENT_IP_STATUS:
        print("######## HEALTH AGENT (public ip) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        ip = get_public_ip()
        result = f"🌐 IP pubblico attuale: {ip}\n\n(rete di casa: cambia nel tempo, non salvarlo come fisso)"
        save_memory("LELE_P_IP_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_IP_STATUS}

    if agent == AGENT_OS_STATUS:
        print("######## HEALTH AGENT (os status) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = get_os_status()
        save_memory("LELE_P_OS_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_OS_STATUS}

    if agent == AGENT_RAM_STATUS:
        print("######## HEALTH AGENT (ram breakdown) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = get_ram_breakdown()
        save_memory("LELE_P_RAM_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_RAM_STATUS}

    if agent == AGENT_TTS_STATUS:
        project = extract_project(user_input)
        print(f"######## HEALTH AGENT (tts status, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = get_tts_status(project)
        save_memory("LELE_P_TTS_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_TTS_STATUS}

    if agent == AGENT_DIRECTORY:
        project = extract_project(user_input)
        subpath = parse_directory_subpath(user_input)
        print(f"######## PROCESS AGENT (directory, project={project}, subpath={subpath}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = get_directory_listing(project, subpath)
        save_memory("LELE_P_DIR_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_DIRECTORY}

    if agent == AGENT_TTS_COPY:
        raw_source, raw_dest = parse_tts_copy_args(user_input)
        source = extract_project(raw_source) if raw_source else None
        dest = extract_project(raw_dest) if raw_dest else None
        print(f"######## PROCESS AGENT (tts copy, {source} -> {dest}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        if not source or not dest:
            result = "❌ Uso: 'tts copy <sorgente> <destinazione>' (es. 'tts copy sw ns')"
        else:
            result = copy_tts_voices(source, dest)

        save_memory("LELE_P_TTSCOPY_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_TTS_COPY}

    if agent == AGENT_TTS_INSTALL:
        raw_project, model_name = parse_tts_install_args(user_input)
        project = extract_project(raw_project) if raw_project else None
        print(f"######## PROCESS AGENT (tts install, project={project}, model={model_name}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        if not project or not model_name:
            result = "❌ Uso: 'tts install <progetto> <nome_modello>' (es. 'tts install ns pt_BR-faber-medium')"
        else:
            result = install_tts_voice(project, model_name)

        save_memory("LELE_P_TTSINST_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_TTS_INSTALL}

    if agent == AGENT_GIT_PULL:
        project = extract_project(user_input)
        print(f"######## GIT AGENT (pull, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = git_pull(project)
        save_memory("LELE_GIT_PULL_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_GIT_PULL}

    if agent == AGENT_GIT_PULL_FORCE:
        project = extract_project(user_input)
        print(f"######## GIT AGENT (pull FORCE, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = git_pull_force(project)
        save_memory("LELE_GIT_PULLF_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_GIT_PULL_FORCE}

    if agent == AGENT_GIT_STATUS:
        project = extract_project(user_input)
        print(f"######## GIT AGENT (status, project={project}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)
        result = git_status(project)
        save_memory("LELE_GIT_S_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_GIT_STATUS}

    if agent == AGENT_IMPROVE:
        print("######## IMPROVE AGENT ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        filepath = user_input[7:].strip()
        print(f"Filepath: {filepath}")
        result = improve_agent(filepath, chat_id=q.chat_id)
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

    if agent == AGENT_SYNTHESIZE:
        run_id, mode = parse_synthesize_args(user_input)
        print(f"######## ARTIFACT SYNTHESIZER (run_id={run_id}, mode={mode}) ########")
        save_memory("USER_ES", user_input, chat_id=q.chat_id)

        if not run_id:
            result = "❌ Uso: 'sintetizza <run_id>' per un documento riassuntivo, o 'sintetizza codice <run_id>' per i file di codice finali."
        else:
            try:
                result = generate_final_artifacts(run_id=run_id, mode=mode)
            except ValueError as e:
                result = f"❌ {e}"

        save_memory("LELE_SYNTH_ES", result, chat_id=q.chat_id)
        return {"answer": result, "type": AGENT_SYNTHESIZE}

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


VERSION = "1.1.0"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": VERSION,
        "ollama": check_ollama(),
        "postgres": check_postgres(),
        "uptime": get_uptime(),
    }
