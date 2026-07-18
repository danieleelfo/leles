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
       │                     leles, bar_ai)
       ├── Process Agent    (restart: leles resta in leles_bot.py —
       │                     deve girare nel processo del bot stesso,
       │                     via os.execv — bar_ai vive invece in
       │                     process_agent.py, processo esterno)
       ├── Verify Agent     (verify_agent.py)
       ├── Improve Agent    (improver_agent.py)
       ├── Export Agent     (export_agent.py)
       ├── Query Agent      (db_agent.py, ex "DB Agent")
       └── Ollama Agent     (lele_engine9.py — gemma4 + llama3 review)

Uso:
    from scripts.timoniere import route, extract_project, AGENT_GEMMA, ...

    agent = route(user_input)
    if agent == AGENT_GIT_PULL:
        project = extract_project(user_input)
        ...

Nota sugli import: questo modulo evita import assoluti (scripts.*/core.*)
a livello di file, perché leles_bot.py gira come script standalone con
un sys.path diverso da quello di lele_api.py (uvicorn, root sul path) e
deve poter importare le funzioni predicate semplici (is_restart_leles_trigger)
senza trascinarsi dietro l'intera catena core→scripts. L'unico punto che
ne ha davvero bisogno (is_query_trigger, per il Query Agent) lo importa
localmente dentro route().
"""

# --- Nomi agente (usati anche come valore del campo "type" in /ask) -------

AGENT_RESTART_LELES = "restart_leles"
AGENT_RESTART_BAR_AI = "restart_bar_ai"
AGENT_GIT_PULL = "git_pull"
AGENT_GIT_STATUS = "git_status"
AGENT_IMPROVE = "improve"
AGENT_VERIFY = "verify"
AGENT_EXPORT = "export"
AGENT_QUERY = "query"
AGENT_LLAMA = "llama_review"
AGENT_GEMMA = "gemma"  # fallback finale, se nessun altro trigger matcha

_LLAMA_WORDS = ("edita", "review", "roast", "llama", "llama3", "critica", "pirata")
_BAR_AI_WORDS = ("bar_ai", "bar ai", "bar-ai")


# --- Predicati dei singoli trigger -------------------------------------------

def _mentions_bar_ai(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _BAR_AI_WORDS)


def extract_project(text: str) -> str:
    """
    'pull report bar_ai' -> 'bar_ai'; 'pull report leles' o 'pull report'
    da solo -> 'leles' (default, per retrocompatibilità con i trigger
    esistenti che non specificavano progetto).
    """
    return "bar_ai" if _mentions_bar_ai(text) else "leles"


def is_restart_leles_trigger(text: str) -> bool:
    """
    'restart', 'restart leles', 'restart lelé' — MAI se il messaggio
    menziona bar_ai, altrimenti "restart bar_ai" verrebbe intercettato
    qui per errore (riavvierebbe Leles invece di bar_ai).
    """
    t = text.lower().strip()
    return t.startswith("restart") and not _mentions_bar_ai(t)


def is_restart_bar_ai_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("restart") and _mentions_bar_ai(t)


def is_git_pull_trigger(text: str) -> bool:
    return text.lower().strip().startswith("pull report")


def is_git_status_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("status leles") or t.startswith("status lele") or (
        t.startswith("status") and _mentions_bar_ai(t)
    )


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

    if is_restart_bar_ai_trigger(text):
        return AGENT_RESTART_BAR_AI
    if is_restart_leles_trigger(text):
        return AGENT_RESTART_LELES
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
