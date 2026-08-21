"""
airflow_agent.py — Trigger e status di DAG Airflow via REST API (JWT, v2 —
Airflow 3.x), con estrazione parametri in linguaggio naturale via LLM (Ollama)
per il trigger.

Flusso trigger:
    "exec airflow <richiesta in linguaggio naturale>"
        │
        ▼
    extract_dag_params()  — LLM (Ollama) legge KNOWN_DAGS + richiesta,
                             ritorna JSON {"dag_id": ..., "conf": {...}}
        │
        ▼
    trigger_dag_run()     — POST REST API Airflow v2, autenticato con JWT
                             (cache del token con retry automatico su 401)

Config attesa in .env:
    AIRFLOW_BASE_URL   default: http://localhost:8085
    AIRFLOW_USERNAME   opzionale — se assente, fallback automatico alla
    AIRFLOW_PASSWORD   password auto-generata dal Simple Auth Manager
                       ($AIRFLOW_HOME/simple_auth_manager_passwords.json.generated)

ATTENZIONE: KNOWN_DAGS qui sotto è un placeholder — va compilato con i
dag_id reali del tuo Airflow (Admin > DAGs) e i parametri che ciascuno
si aspetta in `conf`, altrimenti l'LLM non ha modo di sapere cosa esiste
e rischia di inventare dag_id a caso (per questo route() rifiuta comunque
qualsiasi dag_id non presente in questo dizionario, vedi extract_dag_params).
"""

import os
import json
import time
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL", "http://localhost:8085")
AIRFLOW_HOME = os.getenv("AIRFLOW_HOME", os.path.expanduser("~/Desktop/Danny/airflow"))
_PASSWORDS_FILE = os.path.join(AIRFLOW_HOME, "simple_auth_manager_passwords.json.generated")

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3:latest"  # coerente con db_agent.py

_token_cache = {"token": None, "expires_at": 0}


def _get_credentials():
    """
    AIRFLOW_USERNAME/PASSWORD dal .env se presenti, altrimenti fallback
    automatico alla password auto-generata dal Simple Auth Manager
    (default di Airflow 3.x se non hai configurato nulla di custom).
    """
    user = os.getenv("AIRFLOW_USERNAME")
    password = os.getenv("AIRFLOW_PASSWORD")
    if user and password:
        return user, password

    if os.path.exists(_PASSWORDS_FILE):
        try:
            with open(_PASSWORDS_FILE) as f:
                data = json.load(f)
            if "admin" in data:
                return "admin", data["admin"]
        except (json.JSONDecodeError, OSError):
            pass

    return None, None


def _get_token(force_refresh: bool = False) -> str:
    """JWT per l'API v2 — POST /auth/token, cache con margine sotto la scadenza."""
    if not force_refresh and _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    user, password = _get_credentials()
    if not user:
        raise RuntimeError(
            "Credenziali Airflow non trovate: imposta AIRFLOW_USERNAME/AIRFLOW_PASSWORD "
            f"nel .env, oppure verifica che esista {_PASSWORDS_FILE}."
        )

    response = requests.post(
        f"{AIRFLOW_BASE_URL}/auth/token",
        json={"username": user, "password": password},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError(f"Risposta /auth/token senza campo token riconosciuto: {data}")

    _token_cache["token"] = token
    _token_cache["expires_at"] = time.time() + 55 * 60  # margine sotto la scadenza tipica (1h)
    return token


def _api_request(method: str, path: str, json_body: dict = None, retry: bool = True):
    """Chiamata autenticata all'API v2, con un retry automatico se il token è scaduto (401)."""
    token = _get_token()
    response = requests.request(
        method,
        f"{AIRFLOW_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=json_body,
        timeout=15,
    )

    if response.status_code == 401 and retry:
        token = _get_token(force_refresh=True)
        response = requests.request(
            method,
            f"{AIRFLOW_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json_body,
            timeout=15,
        )

    return response

# --- Registro DAG conosciuti -------------------------------------------------
# Ogni voce aiuta l'LLM a:
#   1. scegliere il dag_id giusto invece di inventarlo
#   2. sapere quali chiavi mettere in "conf" e con che tipo
# Tipi/default presi da dags/emergence_dag.py e dags/emergence_pipeline_dag.py.
#
# NOTA: emergence_pipeline_dag.py chiama internamente anche un DAG
# "emergence_lab_analysis" via TriggerDagRunOperator, ma quel file DAG
# non è ancora stato condiviso qui — se esiste ed è pensato per essere
# lanciabile anche da solo (non solo come step interno della pipeline),
# aggiungilo a questo registro con i suoi param.
KNOWN_DAGS = {
    "emergence_dag": {
        "description": "Lancia una simulazione multi-agente concettuale e produce un audit di coerenza (LLM-as-a-Judge). Se target_run_id è 0 crea una nuova run, altrimenti rianalizza una run esistente.",
        "params": {
            "target_run_id": "int, default 0 (0 = nuova run, >0 = riusa una run esistente)",
            "scenario": "str, default 'Progettazione dell'architettura di coordinamento agenti'",
            "num_iterations": "int, default 3",
            "temperature": "float, default 0.7",
            "seed": "int, default 42",
            "judge_model": "str, default 'qwen2.5'",
            "pipeline_config": "str (JSON), opzionale, default '{}' — solo se l'utente chiede ESPLICITAMENTE ruoli/modelli/visibilità custom (es. 'usa solo Planner e Designer', 'modelli fissi'). Altrimenti ometti questa chiave.",
        },
    },
    "emergence_lab_analysis": {
        "description": "Analizza una run dell'esperimento Emergence Lab con un LLM giudice",
        "params": {
            "run_id": "int",
            "target_role": "str (opzionale, es. 'Critic' — default 'ALL')",
            "judge_model": "str (opzionale, default 'mistral')",
        },
    },
    "emergence_full_pipeline": {
        "description": "Pipeline completa: lancia una nuova simulazione (emergence_dag) e poi triggera l'analisi (emergence_lab_analysis) passandole il run_id restituito.",
        "params": {
            "scenario": "str, default 'Progettazione dell'architettura di coordinamento agenti'",
            "num_iterations": "int, default 3",
            "judge_model": "str, default 'qwen2.5'",
            "target_role": "str, default 'ALL' (es. 'Planner', 'Critic', 'Builder', 'Scientist', 'Observer')",
        },
    },
}

SYSTEM_EXTRACT = """You are a router that converts a natural language request into a JSON
object describing which Airflow DAG to trigger and with which parameters.

Rules:
- Output ONLY valid JSON, nothing else. No markdown, no backticks, no explanation.
- The JSON must have exactly two keys: "dag_id" (string or null) and "conf" (object).
- "dag_id" MUST be one of the known dag_ids given below. If you can't confidently
  match the request to one of them, set "dag_id" to null.
- "conf" contains only the parameters explicitly present in the user request that
  match the expected params for that DAG. Do not invent values. Omit keys the
  user didn't specify rather than guessing.

Known DAGs:
{known_dags}
"""


def _known_dags_block() -> str:
    lines = []
    for dag_id, meta in KNOWN_DAGS.items():
        params = ", ".join(f"{k} ({v})" for k, v in meta.get("params", {}).items()) or "none"
        lines.append(f"- {dag_id}: {meta.get('description', '')} | params: {params}")
    return "\n".join(lines) if lines else "(nessun DAG registrato — compila KNOWN_DAGS)"


def extract_dag_params(user_text: str):
    """
    Chiede all'LLM di estrarre (dag_id, conf) dalla richiesta in linguaggio
    naturale. Ritorna (dag_id, conf, errore). errore è None se tutto ok.
    """
    system = SYSTEM_EXTRACT.format(known_dags=_known_dags_block())

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 300},
            },
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return None, {}, f"LLM non raggiungibile: {e}"

    # difesa contro backtick/markdown che l'LLM a volte aggiunge comunque
    raw = raw.strip().strip("`")
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, {}, f"Risposta LLM non è JSON valido: {raw[:200]}"

    dag_id = parsed.get("dag_id")
    conf = parsed.get("conf") or {}

    # L'LLM a volte "corregge" pipeline_config da stringa-contenente-JSON a
    # oggetto JSON vero — comportamento ragionevole per un umano, ma Airflow
    # ha il Param dichiarato type="string" e rifiuta con 400 se arriva un
    # oggetto. Normalizzo qui, non ci si può fidare che l'LLM mantenga il
    # tipo esatto quando il contenuto stesso è JSON.
    if "pipeline_config" in conf and not isinstance(conf["pipeline_config"], str):
        conf["pipeline_config"] = json.dumps(conf["pipeline_config"])

    if dag_id is not None and dag_id not in KNOWN_DAGS:
        return None, {}, f"DAG '{dag_id}' non riconosciuto (non in KNOWN_DAGS)"

    return dag_id, conf, None


def trigger_dag_run(dag_id: str, conf: dict):
    """
    POST /api/v2/dags/{dag_id}/dagRuns — Public API di Airflow 3 (sostituisce
    /api/v1, rimossa in Airflow 3.x). Autenticato via _api_request(), che
    gestisce cache del token e retry automatico su 401. dag_run_id generato
    lato client per poterlo riportare subito all'utente senza un secondo
    giro a leggere lo stato.
    """
    dag_run_id = f"leles_{uuid.uuid4().hex[:8]}"

    try:
        response = _api_request(
            "POST",
            f"/api/v2/dags/{dag_id}/dagRuns",
            json_body={"dag_run_id": dag_run_id, "conf": conf, "logical_date": None},
        )
    except requests.exceptions.ConnectionError:
        return False, f"❌ Airflow non raggiungibile su {AIRFLOW_BASE_URL} (porta 8085 attiva?)"
    except RuntimeError as e:
        return False, f"❌ {e}"
    except Exception as e:
        return False, f"❌ Errore di rete verso Airflow: {e}"

    if response.status_code in (200, 201):
        return True, dag_run_id
    if response.status_code == 404:
        return False, f"❌ DAG '{dag_id}' non trovato su Airflow (controlla che sia unpaused/deployato)"
    if response.status_code in (401, 403):
        return False, f"❌ Token Airflow rifiutato ({response.status_code}) — l'utente ha i permessi per lanciare DAG?"
    return False, f"❌ Airflow ha risposto {response.status_code}: {response.text[:300]}"


def airflow_agent(user_text: str) -> str:
    """
    Entry point chiamato da lele_api.py. `user_text` è già ripulito del
    prefisso "exec airflow" — vedi parse_airflow_command in timoniere.py.
    """
    if not user_text.strip():
        known = ", ".join(KNOWN_DAGS.keys()) or "(nessuno registrato)"
        return f"🌬️ Dimmi quale DAG lanciare e con che parametri. DAG conosciuti: {known}"

    dag_id, conf, error = extract_dag_params(user_text)

    if error:
        return f"❌ {error}"

    if not dag_id:
        known = ", ".join(KNOWN_DAGS.keys()) or "(nessuno registrato)"
        return f"🤔 Non ho capito quale DAG intendi. DAG conosciuti: {known}"

    ok, result = trigger_dag_run(dag_id, conf)

    if not ok:
        return result

    conf_str = json.dumps(conf, ensure_ascii=False) if conf else "{}"
    return f"🌀 DAG '{dag_id}' lanciato — run_id: {result}\nconf: {conf_str}"


# --- Status (sola lettura, nessun LLM coinvolto — deterministico) -----------

_STATE_EMOJI = {
    "success": "✅👌🥳",
    "failed": "❌",
    "running": "🔄🏴‍☠️ ",
    "queued": "⏳",
    "up_for_retry": "🔁",
    "upstream_failed": "⛔",
}


def get_dag_runs_status(dag_id: str, limit: int = 5) -> str:
    """Ultime run di un DAG specifico: stato, orario, durata."""
    try:
        response = _api_request(
            "GET",
            f"/api/v2/dags/{dag_id}/dagRuns?limit={limit}&order_by=-start_date",
        )
    except requests.exceptions.ConnectionError:
        return f"❌ Airflow non raggiungibile su {AIRFLOW_BASE_URL} (porta 8085 attiva?)"
    except RuntimeError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Errore di rete verso Airflow: {e}"

    if response.status_code == 404:
        return f"❌ DAG '{dag_id}' non trovato su Airflow."
    if response.status_code != 200:
        return f"❌ Airflow ha risposto {response.status_code}: {response.text[:300]}"

    runs = response.json().get("dag_runs", [])
    if not runs:
        return f"🌀 Nessuna run trovata per il DAG '{dag_id}'."

    lines = [f"🌀 Ultime {len(runs)} run di '{dag_id}':"]
    for run in runs:
        state = run.get("state", "?")
        emoji = _STATE_EMOJI.get(state, "❔")
        start = (run.get("start_date") or "—")[:19].replace("T", " ")
        end_raw = run.get("end_date")
        end = end_raw[:19].replace("T", " ") if end_raw else "in corso"
        lines.append(f"{emoji} {run.get('dag_run_id', '?')} | {state} | {start} → {end}")

    return "\n".join(lines)


def get_all_dags_status() -> str:
    """Elenco di tutti i DAG con stato pausa/attivo — panoramica generale."""
    try:
        response = _api_request("GET", "/api/v2/dags?limit=100")
    except requests.exceptions.ConnectionError:
        return f"❌ Airflow non raggiungibile su {AIRFLOW_BASE_URL} (porta 8085 attiva?)"
    except RuntimeError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Errore di rete verso Airflow: {e}"

    if response.status_code != 200:
        return f"❌ Airflow ha risposto {response.status_code}: {response.text[:300]}"

    dags = response.json().get("dags", [])
    if not dags:
        return "🌀 Nessun DAG trovato."

    lines = ["🌀 DAG disponibili:"]
    for d in sorted(dags, key=lambda x: x.get("dag_id", "")):
        paused = "⏸️ pausa" if d.get("is_paused") else "▶️ attivo"
        lines.append(f"  • {d.get('dag_id')} ({paused})")

    return "\n".join(lines)


def get_latest_task_log(dag_id: str, task_id: str, try_number: int = 1) -> str:
    """
    Log reale (traceback incluso) dell'ultimo task instance di un DAG —
    per vedere l'errore vero quando un DAG fallisce con un messaggio
    generico tipo 'Errore sconosciuto' (tipico quando il fallimento viene
    da un DAG figlio triggerato via TriggerDagRunOperator, il cui
    traceback non risale al DAG padre).
    """
    try:
        runs_resp = _api_request(
            "GET",
            f"/api/v2/dags/{dag_id}/dagRuns?limit=1&order_by=-start_date",
        )
    except requests.exceptions.ConnectionError:
        return f"❌ Airflow non raggiungibile su {AIRFLOW_BASE_URL}"
    except RuntimeError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Errore di rete verso Airflow: {e}"

    if runs_resp.status_code != 200:
        return f"❌ Airflow ha risposto {runs_resp.status_code}: {runs_resp.text[:300]}"

    runs = runs_resp.json().get("dag_runs", [])
    if not runs:
        return f"❌ Nessuna run trovata per '{dag_id}'."

    dag_run_id = runs[0]["dag_run_id"]
    state = runs[0].get("state", "?")

    log_resp = _api_request(
        "GET",
        f"/api/v2/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}/logs/{try_number}",
    )

    if log_resp.status_code == 404:
        return (
            f"❌ Task '{task_id}' non trovato nella run '{dag_run_id}' (dag={dag_id}). "
            f"Controlla il nome esatto del task."
        )
    if log_resp.status_code != 200:
        return f"❌ Airflow ha risposto {log_resp.status_code}: {log_resp.text[:300]}"

    content = log_resp.text
    if len(content) > 3700:
        content = "...(troncato, tengo la coda)...\n" + content[-3700:]

    return f"📄 Log [{dag_id} / {task_id}] — run {dag_run_id} ({state}):\n\n{content}"
