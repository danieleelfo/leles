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
       ├── Git Agent      (git_agent.py — pull/status)
       ├── Process Agent   (leles_bot.py — restart: deve girare nel
       │                    processo del bot stesso, via os.execv)
       ├── Verify Agent    (verify_agent.py)
       ├── Improve Agent   (improver_agent.py)
       ├── Export Agent    (export_agent.py)
       ├── Query Agent     (db_agent.py, ex "DB Agent")
       └── Ollama Agent    (lele_engine9.py — gemma4 + llama3 review)

Uso:
    from scripts.timoniere import route, AGENT_GEMMA, ...

    agent = route(user_input)
    if agent == AGENT_QUERY:
        ...

Nota sugli import: questo modulo evita import assoluti (scripts.*/core.*)
a livello di file, perché leles_bot.py gira come script standalone con
un sys.path diverso da quello di lele_api.py (uvicorn, root sul path) e
deve poter importare le funzioni predicate semplici (is_restart_trigger)
senza trascinarsi dietro l'intera catena core→scripts. L'unico punto che
ne ha davvero bisogno (is_query_trigger, per il Query Agent) lo importa
localmente dentro route().
"""

# --- Nomi agente (usati anche come valore del campo "type" in /ask) -------

AGENT_RESTART = "restart"
AGENT_GIT_PULL = "git_pull"
AGENT_GIT_STATUS = "git_status"
AGENT_IMPROVE = "improve"
AGENT_VERIFY = "verify"
AGENT_EXPORT = "export"
AGENT_QUERY = "query"
AGENT_LLAMA = "llama_review"
AGENT_GEMMA = "gemma"  # fallback finale, se nessun altro trigger matcha

_LLAMA_WORDS = ("edita", "review", "roast", "llama", "llama3", "critica", "pirata")


# --- Predicati dei singoli trigger (esposti anche singolarmente, per --------
# --- leles_bot.py che deve intercettare "restart" PRIMA di chiamare /ask) --

def is_restart_trigger(text: str) -> bool:
    return text.lower().strip().startswith("restart")


def is_git_pull_trigger(text: str) -> bool:
    return text.lower().strip().startswith("pull report")


def is_git_status_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("status leles") or t.startswith("status lele")


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

    if is_restart_trigger(text):
        return AGENT_RESTART
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
