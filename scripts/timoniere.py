"""
timoniere.py — Router deterministico per Lelé/Leles.

Sostituisce la lunga catena di if/elif che viveva sparsa in lele_api.py
(e in parte in leles_bot.py). Nessun LLM decide QUALE agente chiamare:
il routing è puro pattern matching su stringhe, deterministico e
testabile in isolamento. L'LLM entra in gioco SOLO dentro l'agente già
scelto (es. gemma4 dentro l'Ollama Agent, o dentro il Verify Agent).

    Utente
       │
       ▼
    Timoniere (questo file)
       │
       ├── Git Agent       (git_agent.py — pull/status, multi-progetto:
       │                     leles, bar_ai, lele, lele_story_whisper, lele_night_story)
       ├── Process Agent    (start/stop/restart di progetti ESTERNI —
       │                     bar_ai, lele, lele_story_whisper, lele_night_story — in
       │                     process_agent.py. Il restart di Leles
       │                     stesso resta un caso speciale a parte in
       │                     leles_bot.py: richiede os.execv sul
       │                     proprio processo, non è delegabile)
       ├── Verify Agent     (verify_agent.py)
       ├── Improve Agent    (improver_agent.py)
       ├── Export Agent     (export_agent.py)
       ├── Query Agent      (db_agent.py, ex "DB Agent")
       ├── Health Agent     (health_agent.py)
       └── Ollama Agent     (lele_engine9.py — gemma4 + llama3 review)
"""

import re

# --- Nomi agente (usati anche come valore del campo "type" in /ask) -------

AGENT_RESTART_LELES = "restart_leles"
AGENT_START = "start_process"
AGENT_STOP = "stop_process"
AGENT_RESTART_EXTERNAL = "restart_process"
AGENT_UVICORN_STATUS = "uvicorn_status"
AGENT_TELEGRAM_STATUS = "telegram_status"
AGENT_SYSTEM_STATUS = "system_status"
AGENT_GIT_PULL = "git_pull"
AGENT_GIT_STATUS = "git_status"
AGENT_IMPROVE = "improve"
AGENT_VERIFY = "verify"
AGENT_EXPORT = "export"
AGENT_QUERY = "query"
AGENT_LLAMA = "llama_review"
AGENT_GEMMA = "gemma"  # fallback finale, se nessun altro trigger matcha

_LLAMA_WORDS = ("edita", "review", "roast", "llama", "llama3", "critica", "pirata")

# Progetti esterni gestibili da Leles (start/stop/restart, pull/status).
# "leles" NON è qui: è il progetto corrente, gestito a parte (self-restart
# via os.execv, niente start/stop di se stesso).
EXTERNAL_PROJECTS = ("bar_ai", "lele_story_whisper", "lele_night_story", "lele")

_PROJECT_PATTERNS = {
    "bar_ai": re.compile(r"bar[_\s-]?ai", re.IGNORECASE),
    "lele_story_whisper": re.compile(r"(lele[_\s]?)?(story[_\s]?whisper|sw)\b", re.IGNORECASE),
    "lele_night_story": re.compile(r"(lele[_\s]?)?(night[_\s]?story|ns)\b", re.IGNORECASE),
    "lele": re.compile(r"\blele\b", re.IGNORECASE),
}


# --- Predicati dei singoli trigger -------------------------------------------

def extract_project(text: str) -> str:
    """
    Determina a quale progetto si riferisce `text`. Ordine di check
    intenzionale: pattern più specifici (bar_ai, story_whisper, night_story) prima
    del generico "lele" isolato, così "lele_night_story" o "lele_story_whisper"
    non finiscono matchati come "lele". Default: "leles" (il progetto corrente).
    """
    if _PROJECT_PATTERNS["bar_ai"].search(text):
        return "bar_ai"
    if _PROJECT_PATTERNS["lele_story_whisper"].search(text):
        return "lele_story_whisper"
    if _PROJECT_PATTERNS["lele_night_story"].search(text):
        return "lele_night_story"
    if _PROJECT_PATTERNS["lele"].search(text):
        return "lele"
    return "leles"


def _mentions_external_project(text: str) -> bool:
    return extract_project(text) != "leles"


def is_restart_leles_trigger(text: str) -> bool:
    """'restartleles', 'restart leles', 'restart lele_es' — mai se il messaggio menziona un progetto esterno."""
    t = text.lower().strip()
    return t.startswith("restart") and not _mentions_external_project(t)


def is_restart_external_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("restart") and _mentions_external_project(t)


def is_start_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("start") and _mentions_external_project(t)


def is_stop_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("stop") and _mentions_external_project(t)


def is_uvicorn_status_trigger(text: str) -> bool:
    return text.lower().strip().startswith("uvicorn status")


def is_telegram_status_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("telegram status") or t.startswith("bot status")


def is_system_status_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("status sistema") or t.startswith("system status") or t.startswith("lair status")


def is_git_pull_trigger(text: str) -> bool:
    return text.lower().strip().startswith("pull report")


def is_git_status_trigger(text: str) -> bool:
    return text.lower().strip().startswith("status")


def is_improve_trigger(text: str) -> bool:
    return text.lower().strip().startswith("improve")


def is_verify_trigger(text: str) -> bool:
    return text.lower().strip().startswith(("verifica", "verify"))


def is_export_trigger(text: str) -> bool:
    return text.lower().strip().startswith(("esporta", "esport", "export"))


def is_llama_trigger(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _LLAMA_WORDS)


# --- Router vero e proprio ---------------------------------------------------

def route(user_input: str) -> str:
    """
    Determina quale agente deve gestire `user_input`. Ordine dei check
    intenzionale: i comandi più specifici/espliciti vengono prima del
    fallback generico a gemma. Ritorna una delle costanti AGENT_*.
    """
    from scripts.lele_engine9 import is_query_trigger  # import locale, vedi nota in cima al file

    text = user_input.strip()

    if is_restart_external_trigger(text):
        return AGENT_RESTART_EXTERNAL
    if is_restart_leles_trigger(text):
        return AGENT_RESTART_LELES
    if is_start_trigger(text):
        return AGENT_START
    if is_stop_trigger(text):
        return AGENT_STOP
    if is_uvicorn_status_trigger(text):
        return AGENT_UVICORN_STATUS
    if is_telegram_status_trigger(text):
        return AGENT_TELEGRAM_STATUS
    if is_system_status_trigger(text):
        return AGENT_SYSTEM_STATUS
    if is_git_pull_trigger(text):
        return AGENT_GIT_PULL
    if is_git_status_trigger(text):
        return AGENT_GIT_STATUS
    if is_improve_trigger(text):
        return AGENT_IMPROVE
    if is_verify_trigger(text):
        return AGENT_VERIFY
    if is_export_trigger(text):
        return AGENT_EXPORT
    if is_query_trigger(text):
        return AGENT_QUERY
    if is_llama_trigger(text):
        return AGENT_LLAMA

    return AGENT_GEMMA
