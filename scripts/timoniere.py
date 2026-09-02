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
       ├── Airflow Agent    (airflow_agent.py — trigger/status/pause DAG)
       ├── Emergence Prompts (core/emergence_prompts.py — query/update
       │                      system_prompt degli agenti Emergence Lab)
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
AGENT_LOGS = "logs"
AGENT_TTS_STATUS = "tts_status"
AGENT_DIRECTORY = "directory"
AGENT_TTS_COPY = "tts_copy"
AGENT_TTS_INSTALL = "tts_install"
AGENT_EXPORT_DAG = "export_dag"
AGENT_AIRFLOW_STATUS = "airflow_status"
AGENT_DECISION = "decision"
AGENT_IP_STATUS = "ip_status"
AGENT_OS_STATUS = "os_status"
AGENT_RAM_STATUS = "ram_status"
AGENT_GIT_PULL = "git_pull"
AGENT_GIT_PULL_FORCE = "git_pull_force"
AGENT_GIT_STATUS = "git_status"
AGENT_GIT_DIFF = "git_diff"
AGENT_GIT_LAST_COMMIT = "git_last_commit"
AGENT_TASK_LOG = "task_log"
AGENT_IMPROVE = "improve"
AGENT_VERIFY = "verify"
AGENT_EXPORT = "export"
AGENT_QUERY = "query"
AGENT_LLAMA = "llama_review"
AGENT_AIRFLOW = "airflow_trigger"
AGENT_SYNTHESIZE = "synthesize"
AGENT_DAG_PAUSE = "dag_pause"
AGENT_DAG_UNPAUSE = "dag_unpause"
AGENT_QUERY_PROMPTS = "query_emergence_prompts"
AGENT_UPDATE_PROMPT = "update_emergence_prompt"
AGENT_QUERY_MESSAGES = "query_emergence_messages"
AGENT_QUERY_STATUS = "query_emergence_status"
AGENT_SAVE_WORLD = "save_world"
AGENT_QUERY_WORLDS = "query_worlds"
AGENT_QUERY_WORLD = "query_world"
AGENT_SEND_FILE = "send_file_telegram"
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
    "airflow": re.compile(r"\b(airflow|dags?)\b", re.IGNORECASE),
}


# --- Predicati dei singoli trigger -------------------------------------------

def extract_project(text: str) -> str:
    """
    Determina a quale progetto si riferisce `text`. Ordine di check
    intenzionale: pattern più specifici (bar_ai, story_whisper, night_story) prima
    del generico "lele" isolato, così "lele_night_story" o "lele_story_whisper"
    non finiscono matchati come "lele". "airflow"/"dag"/"dags" è uno
    pseudo-progetto: non è in PROGETTI_CONFIG (non è un processo Python
    start/stop-abile), ma un percorso valido per directory/logs/export.
    Default: "leles" (il progetto corrente).
    """
    if _PROJECT_PATTERNS["bar_ai"].search(text):
        return "bar_ai"
    if _PROJECT_PATTERNS["lele_story_whisper"].search(text):
        return "lele_story_whisper"
    if _PROJECT_PATTERNS["lele_night_story"].search(text):
        return "lele_night_story"
    if _PROJECT_PATTERNS["airflow"].search(text):
        return "airflow"
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


def is_logs_trigger(text: str) -> bool:
    """'logs <progetto>' — ultime righe dei log di un progetto esterno."""
    t = text.lower().strip()
    return t.startswith("logs ") or t.startswith("log ")


def is_tts_status_trigger(text: str) -> bool:
    """'status tts <progetto>' — modelli voce Piper installati per un progetto."""
    t = text.lower().strip()
    return t.startswith("status tts") or t.startswith("tts status")


def is_airflow_status_trigger(text: str) -> bool:
    """'status dag [dag_id]' / 'status airflow' — ultime N esecuzioni di un DAG, o elenco di tutti i DAG se dag_id omesso."""
    t = text.lower().strip()
    return t.startswith("status dag") or t.startswith("dag status") or t.startswith("status airflow")


def is_task_log_trigger(text: str) -> bool:
    """'log task <dag_id> <task_id>' — log reale (con traceback) dell'ultimo task instance."""
    return text.lower().strip().startswith("log task ")


def parse_task_log_args(text: str):
    """'log task emergence_dag run_coherence_analysis_task' -> (dag_id, task_id)."""
    t = text.strip()
    if t.lower().startswith("log task "):
        parts = t[len("log task "):].strip().split()
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None


def is_decision_trigger(text: str) -> bool:
    """'decisione <run_id> [judge_model]' — estrae la conclusione/decisione presa in una run."""
    return text.lower().strip().startswith("decisione ")


def parse_decision_args(text: str):
    """'decisione 47 deepseek-r1' -> (47, 'deepseek-r1'); 'decisione 47' -> (47, None)."""
    t = text.strip()
    if t.lower().startswith("decisione "):
        parts = t[len("decisione "):].strip().split()
        if not parts:
            return None, None
        try:
            run_id = int(parts[0])
        except ValueError:
            return None, None
        judge_model = parts[1] if len(parts) > 1 else None
        return run_id, judge_model
    return None, None


def parse_airflow_status_dag_id(text: str) -> str:
    """Estrae l'eventuale dag_id da 'status dag <dag_id>' — None se omesso (elenco generale)."""
    t = text.strip()
    for prefix in ("status dag", "dag status", "status airflow"):
        if t.lower().startswith(prefix):
            rest = t[len(prefix):].strip()
            return rest if rest else None
    return None


def is_directory_trigger(text: str) -> bool:
    """'directory <progetto> [sottocartella]' / 'ls <progetto> [sottocartella]'."""
    t = text.lower().strip()
    return t.startswith("directory ") or t.startswith("ls ")


def is_tts_copy_trigger(text: str) -> bool:
    """'tts copy <sorgente> <destinazione>'."""
    return text.lower().strip().startswith("tts copy")


def is_tts_install_trigger(text: str) -> bool:
    """'tts install <progetto> <nome_modello>'."""
    return text.lower().strip().startswith("tts install")


def parse_tts_install_args(text: str):
    """'tts install ns pt_BR-faber-medium' -> ('ns', 'pt_BR-faber-medium')."""
    t = text.strip()
    if t.lower().startswith("tts install"):
        rest = t[len("tts install"):].strip()
        parts = rest.split()
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None


def parse_tts_copy_args(text: str):
    """'tts copy sw ns' -> ('sw', 'ns'), risolti poi con extract_project."""
    t = text.strip()
    if t.lower().startswith("tts copy"):
        rest = t[len("tts copy"):].strip()
        parts = rest.split()
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None


def parse_directory_subpath(text: str) -> str:
    """
    Estrae l'eventuale sottocartella da 'directory <progetto> [subpath]'.
    Assume che il primo token dopo il trigger sia il progetto (es. 'ns',
    'leles') e tutto il resto sia il subpath — coerente con come vengono
    sempre usati gli alias di progetto in questo bot (un solo token).
    """
    t = text.strip()
    for prefix in ("directory ", "ls "):
        if t.lower().startswith(prefix):
            rest = t[len(prefix):].strip()
            parts = rest.split(None, 1)
            return parts[1] if len(parts) > 1 else ""
    return ""


def is_ip_status_trigger(text: str) -> bool:
    """'status ip' — DEVE essere controllato prima di is_git_status_trigger,
    che è un catch-all generico su qualsiasi 'status ...'."""
    t = text.lower().strip()
    return t.startswith("status ip") or t.startswith("ip status")


def is_os_status_trigger(text: str) -> bool:
    """'status os' — CPU/RAM/disco/uptime del Mac. Stesso motivo di
    is_ip_status_trigger: va controllato prima del catch-all git status."""
    t = text.lower().strip()
    return t.startswith("status os") or t.startswith("os status") or t.startswith("status mac")


def is_ram_status_trigger(text: str) -> bool:
    """'status ram' — breakdown RAM + modelli Ollama caricati."""
    t = text.lower().strip()
    return t.startswith("status ram") or t.startswith("ram status")


def is_dag_pause_trigger(text: str) -> bool:
    """'pausa dag <dag_id>' / 'pause dag <dag_id>' — DEVE essere controllato
    prima del catch-all 'status', stesso motivo di is_ip_status_trigger."""
    t = text.lower().strip()
    return t.startswith("pausa dag ") or t.startswith("pause dag ")


def parse_dag_pause_id(text: str) -> str:
    t = text.strip()
    for prefix in ("pausa dag ", "pause dag "):
        if t.lower().startswith(prefix):
            return t[len(prefix):].strip()
    return ""


def is_dag_unpause_trigger(text: str) -> bool:
    """'attiva dag <dag_id>' / 'unpause dag <dag_id>'."""
    t = text.lower().strip()
    return t.startswith("attiva dag ") or t.startswith("unpause dag ")


def parse_dag_unpause_id(text: str) -> str:
    t = text.strip()
    for prefix in ("attiva dag ", "unpause dag "):
        if t.lower().startswith(prefix):
            return t[len(prefix):].strip()
    return ""


_QE_LAST_RE = re.compile(
    r"qe\s+last\s+(?P<n>\d+)(?:\s+(?P<rest>.*))?$",
    re.IGNORECASE,
)


def is_query_messages_trigger(text: str) -> bool:
    """'QE last N [ruolo] [modello]' — legge gli ultimi N messaggi da
    emergence.messages, per monitorare una run Emergence Lab in tempo
    reale senza aspettare che il DAG finisca. DEVE stare prima di
    is_query_prompts_trigger/is_query_trigger nel route(), stesso motivo
    di is_ip_status_trigger: altrimenti verrebbe intercettato da un
    check 'query' più generico."""
    return bool(_QE_LAST_RE.match(text.strip()))


def parse_query_messages_args(text: str):
    """
    'QE last 3' -> (3, None, None, 'asc')
    'QE last 3 Observer' -> (3, 'Observer', None, 'asc')
    'QE last 3 Observer gemma4' -> (3, 'Observer', 'gemma4', 'asc')
    'QE last 3 desc' -> (3, None, None, 'desc')
    'QE last 10 outlaw desc' -> (10, 'outlaw', None, 'desc')
    Default 'asc': prende comunque gli ULTIMI N eventi, ma li ritorna in
    ordine cronologico crescente (più naturale da leggere in sequenza) —
    non i primi N assoluti della tabella. 'desc' come opt-in esplicito
    per il vecchio comportamento (ultimi N, più recente prima).
    """
    m = _QE_LAST_RE.match(text.strip())
    if not m:
        return None, None, None, None
    n = int(m.group("n"))
    rest = (m.group("rest") or "").strip()
    tokens = rest.split()

    order = "asc"
    filtered = []
    for tok in tokens:
        if tok.lower() in ("asc", "desc"):
            order = tok.lower()
        else:
            filtered.append(tok)

    role = filtered[0] if len(filtered) > 0 else None
    model = filtered[1] if len(filtered) > 1 else None
    return n, role, model, order


_QE_STATUS_RE = re.compile(r"qe\s+status(?:\s+(?P<run_id>\d+))?$", re.IGNORECASE)


def is_query_status_trigger(text: str) -> bool:
    """'QE status [run_id]' — vista compatta stato-esecuzione (run,
    iterazione, ruolo, modello, durata, orario), senza il testo delle
    risposte."""
    return bool(_QE_STATUS_RE.match(text.strip()))


def parse_query_status_args(text: str):
    """'QE status' -> None (ultime attività, qualsiasi run); 'QE status 96' -> 96."""
    m = _QE_STATUS_RE.match(text.strip())
    if not m:
        return None
    run_id = m.group("run_id")
    return int(run_id) if run_id else None


_SAVE_WORLD_RE = re.compile(
    r'save\s+world\s+(?P<name>\S+)\s+as\s+"(?P<description>.*)"\s*$',
    re.IGNORECASE | re.DOTALL,
)


def is_save_world_trigger(text: str) -> bool:
    """'save world <nome> as "<testo scenario>"' — salva un nuovo scenario
    riusabile per emergence_flow (world_id invece di riscrivere il testo)."""
    return text.lower().strip().startswith("save world ")


def parse_save_world_args(text: str):
    """'save world isola_omega as "Protocollo Omega..."' -> ('isola_omega', 'Protocollo Omega...')."""
    m = _SAVE_WORLD_RE.match(text.strip())
    if not m:
        return None, None
    return m.group("name").strip(), m.group("description").strip()


def is_query_worlds_trigger(text: str) -> bool:
    """'query worlds' — lista scenari salvati (id + nome, non il testo)."""
    return text.lower().strip() == "query worlds"


_QUERY_WORLD_RE = re.compile(r"query\s+world\s+(?P<id>\d+)\s*$", re.IGNORECASE)


def is_query_world_trigger(text: str) -> bool:
    """'query world <id>' — DEVE stare prima di is_query_prompts_trigger,
    stesso motivo degli altri trigger 'query *' specifici."""
    return bool(_QUERY_WORLD_RE.match(text.strip()))


def parse_query_world_id(text: str):
    m = _QUERY_WORLD_RE.match(text.strip())
    return int(m.group("id")) if m else None


def is_query_prompts_trigger(text: str) -> bool:
    """'query emergence prompts [ruolo]' — DEVE essere controllato prima di
    is_query_trigger (fuzzy-match generico su "query" in lele_engine9.py),
    altrimenti verrebbe intercettato come query DB generica invece che come
    lettura dei system_prompt degli agenti Emergence Lab."""
    return text.lower().strip().startswith("query emergence prompts")


def parse_query_prompts_role(text: str) -> str:
    """
    'query emergence prompts Builder' -> 'Builder'
    'query emergence prompts (Builder)' -> 'Builder'
    'query emergence prompts' -> '' (tutti i ruoli)
    """
    t = text.strip()
    prefix = "query emergence prompts"
    if t.lower().startswith(prefix):
        rest = t[len(prefix):].strip()
        return rest.strip("()").strip()
    return ""


def is_update_prompt_trigger(text: str) -> bool:
    """'update emergence prompt <ruolo> as "..."' — scrittura, admin-only."""
    return text.lower().strip().startswith("update emergence prompt")


def parse_update_prompt_args(text: str):
    """
    'update emergence prompt Builder as "Nuovo prompt qui"' ->
    ('Builder', 'Nuovo prompt qui'). Ritorna (None, None) se non parsa
    (manca il ruolo, manca 'as', o le virgolette non sono chiuse).
    """
    m = re.match(
        r'update\s+emergence\s+prompt\s+(?P<role>\S+)\s+as\s+"(?P<prompt>.*)"\s*$',
        text.strip(),
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None, None
    return m.group("role"), m.group("prompt")


def is_send_file_trigger(text: str) -> bool:
    """'invia file <path>' — manda un file locale come allegato Telegram
    (scripts/invia_file_telegram.py), utile per file troppo grandi per
    'esporta' (che tronca a ~3900 caratteri di testo)."""
    t = text.lower().strip()
    return t.startswith("invia file ")


def parse_send_file_path(text: str) -> str:
    t = text.strip()
    if t.lower().startswith("invia file "):
        return t[len("invia file "):].strip()
    return ""


def is_git_pull_force_trigger(text: str) -> bool:
    """'pull force <progetto>' — reset --hard su origin/main, per quando
    'pull report' si pianta per branch divergenti. Comando distruttivo,
    va tenuto ben distinto (prefisso diverso) da 'pull report'."""
    return text.lower().strip().startswith("pull force")


def is_git_pull_trigger(text: str) -> bool:
    return text.lower().strip().startswith("pull report")


def is_git_status_trigger(text: str) -> bool:
    return text.lower().strip().startswith("status")
    
def is_git_diff_trigger(text: str) -> bool:
    return text.lower().strip().startswith("diff")

def is_git_last_commit_trigger(text: str) -> bool:
    """'commit <progetto>' — diff dell'ultimo commit già salvato, non delle modifiche in sospeso."""
    return text.lower().strip().startswith("commit")

def is_improve_trigger(text: str) -> bool:
    return text.lower().strip().startswith("improve")


def is_verify_trigger(text: str) -> bool:
    return text.lower().strip().startswith(("verifica", "verify"))


def is_export_dag_trigger(text: str) -> bool:
    """'export dag <filename>' — DEVE essere controllato prima di
    is_export_trigger, che è un catch-all su 'export'/'esporta'."""
    return text.lower().strip().startswith("export dag ")


def parse_export_dag_filename(text: str) -> str:
    t = text.strip()
    if t.lower().startswith("export dag "):
        return t[len("export dag "):].strip()
    return ""


def is_export_trigger(text: str) -> bool:
    return text.lower().strip().startswith(("esporta", "esport", "export"))


def is_llama_trigger(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _LLAMA_WORDS)


def is_airflow_trigger(text: str) -> bool:
    """'exec airflow <richiesta in linguaggio naturale>' — l'estrazione dei
    parametri del DAG è delegata a un LLM dentro airflow_agent.py, NON qui:
    il Timoniere resta puro pattern matching, solo il match del trigger."""
    return text.lower().strip().startswith("exec airflow")


def parse_airflow_command(text: str) -> str:
    """'exec airflow lancia il test_dag' -> 'lancia il test_dag' (passato
    poi ad airflow_agent per l'estrazione LLM di dag_id/conf)."""
    t = text.strip()
    if t.lower().startswith("exec airflow"):
        return t[len("exec airflow"):].strip()
    return ""


def is_synthesize_trigger(text: str) -> bool:
    """'sintetizza <run_id>' / 'synth <run_id>'. Trigger diverso da 'esporta'
    (export_agent.py) apposta — funzionalità distinta, non li unifico senza
    aver visto cosa fa già export_agent.py."""
    return text.lower().strip().startswith(("sintetizza", "synth"))


def parse_synthesize_args(text: str):
    """
    'sintetizza 19'         -> (19, 'resume')
    'sintetizza run 19'     -> (19, 'resume')   ('run' è rumore, ignorato)
    'sintetizza codice 19'  -> (19, 'code')
    'synth 19 code'         -> (19, 'code')
    Ritorna (run_id:int|None, mode:str). run_id=None se non trovato/non numerico.
    """
    t = text.strip()
    lowered = t.lower()
    for prefix in ("sintetizza", "synth"):
        if lowered.startswith(prefix):
            rest = t[len(prefix):].strip()
            break
    else:
        return None, "resume"

    mode = "resume"
    run_id = None
    for tok in rest.split():
        low = tok.lower()
        if low in ("codice", "code"):
            mode = "code"
        elif low == "run":
            continue
        elif run_id is None:
            try:
                run_id = int(tok)
            except ValueError:
                pass

    return run_id, mode


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
    if is_airflow_trigger(text):
        return AGENT_AIRFLOW
    if is_uvicorn_status_trigger(text):
        return AGENT_UVICORN_STATUS
    if is_telegram_status_trigger(text):
        return AGENT_TELEGRAM_STATUS
    if is_system_status_trigger(text):
        return AGENT_SYSTEM_STATUS
    if is_task_log_trigger(text):
        return AGENT_TASK_LOG
    if is_logs_trigger(text):
        return AGENT_LOGS
    if is_ip_status_trigger(text):
        return AGENT_IP_STATUS
    if is_os_status_trigger(text):
        return AGENT_OS_STATUS
    if is_ram_status_trigger(text):
        return AGENT_RAM_STATUS
    if is_dag_pause_trigger(text):
        return AGENT_DAG_PAUSE
    if is_dag_unpause_trigger(text):
        return AGENT_DAG_UNPAUSE
    if is_query_messages_trigger(text):
        return AGENT_QUERY_MESSAGES
    if is_query_status_trigger(text):
        return AGENT_QUERY_STATUS
    if is_save_world_trigger(text):
        return AGENT_SAVE_WORLD
    if is_query_worlds_trigger(text):
        return AGENT_QUERY_WORLDS
    if is_query_world_trigger(text):
        return AGENT_QUERY_WORLD
    if is_query_prompts_trigger(text):
        return AGENT_QUERY_PROMPTS
    if is_update_prompt_trigger(text):
        return AGENT_UPDATE_PROMPT
    if is_send_file_trigger(text):
        return AGENT_SEND_FILE
    if is_tts_status_trigger(text):
        return AGENT_TTS_STATUS
    if is_airflow_status_trigger(text):
        return AGENT_AIRFLOW_STATUS
    if is_decision_trigger(text):
        return AGENT_DECISION
    if is_directory_trigger(text):
        return AGENT_DIRECTORY
    if is_tts_copy_trigger(text):
        return AGENT_TTS_COPY
    if is_tts_install_trigger(text):
        return AGENT_TTS_INSTALL
    if is_git_pull_force_trigger(text):
        return AGENT_GIT_PULL_FORCE
    if is_git_pull_trigger(text):
        return AGENT_GIT_PULL
    if is_git_diff_trigger(text):
        return AGENT_GIT_DIFF
    if is_git_last_commit_trigger(text):
        return AGENT_GIT_LAST_COMMIT
    if is_git_status_trigger(text):
        return AGENT_GIT_STATUS
    if is_improve_trigger(text):
        return AGENT_IMPROVE
    if is_verify_trigger(text):
        return AGENT_VERIFY
    if is_export_dag_trigger(text):
        return AGENT_EXPORT_DAG
    if is_export_trigger(text):
        return AGENT_EXPORT
    if is_synthesize_trigger(text):
        return AGENT_SYNTHESIZE
    if is_query_trigger(text):
        return AGENT_QUERY
    if is_llama_trigger(text):
        return AGENT_LLAMA

    return AGENT_GEMMA
