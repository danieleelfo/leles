"""
airflow_agent.py — Trigger di DAG Airflow via REST API, con estrazione
parametri in linguaggio naturale via LLM (Ollama).

Flusso:
    "exec airflow <richiesta in linguaggio naturale>"
        │
        ▼
    extract_dag_params()  — LLM (Ollama) legge KNOWN_DAGS + richiesta,
                             ritorna JSON {"dag_id": ..., "conf": {...}}
        │
        ▼
    trigger_dag_run()     — POST REST API Airflow, autenticato Basic Auth

Config attesa in .env:
    AIRFLOW_BASE_URL   default: http://localhost:8085
    AIRFLOW_USERNAME
    AIRFLOW_PASSWORD

ATTENZIONE: KNOWN_DAGS qui sotto è un placeholder — va compilato con i
dag_id reali del tuo Airflow (Admin > DAGs) e i parametri che ciascuno
si aspetta in `conf`, altrimenti l'LLM non ha modo di sapere cosa esiste
e rischia di inventare dag_id a caso (per questo route() rifiuta comunque
qualsiasi dag_id non presente in questo dizionario, vedi extract_dag_params).
"""

import os
import json
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL", "http://localhost:8085")
AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME", "airflow")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD", "airflow")

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3:latest"  # coerente con db_agent.py

# --- Registro DAG conosciuti -------------------------------------------------
# COMPILA QUESTO con i dag_id reali. Ogni voce aiuta l'LLM a:
#   1. scegliere il dag_id giusto invece di inventarlo
#   2. sapere quali chiavi mettere in "conf" e con che tipo
KNOWN_DAGS = {
    # "nome_dag_reale": {
    #     "description": "cosa fa, in una riga",
    #     "params": {"param1": "str", "param2": "int (opzionale)"},
    # },
    "test_dag": {
        "description": "DAG di test/smoke, nessun parametro richiesto",
        "params": {},
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

    if dag_id is not None and dag_id not in KNOWN_DAGS:
        return None, {}, f"DAG '{dag_id}' non riconosciuto (non in KNOWN_DAGS)"

    return dag_id, conf, None


def trigger_dag_run(dag_id: str, conf: dict):
    """
    POST /api/v1/dags/{dag_id}/dagRuns — Airflow REST API stabile (v1).
    dag_run_id generato lato client per poterlo riportare subito all'utente
    senza dover fare un secondo giro a leggere lo stato.
    """
    dag_run_id = f"leles_{uuid.uuid4().hex[:8]}"
    url = f"{AIRFLOW_BASE_URL}/api/v1/dags/{dag_id}/dagRuns"

    try:
        response = requests.post(
            url,
            json={"dag_run_id": dag_run_id, "conf": conf},
            auth=(AIRFLOW_USERNAME, AIRFLOW_PASSWORD),
            timeout=15,
        )
    except requests.exceptions.ConnectionError:
        return False, f"❌ Airflow non raggiungibile su {AIRFLOW_BASE_URL} (porta 8085 attiva?)"
    except Exception as e:
        return False, f"❌ Errore di rete verso Airflow: {e}"

    if response.status_code in (200, 201):
        return True, dag_run_id
    if response.status_code == 404:
        return False, f"❌ DAG '{dag_id}' non trovato su Airflow (controlla che sia unpaused/deployato)"
    if response.status_code == 401:
        return False, "❌ Autenticazione Airflow fallita (controlla AIRFLOW_USERNAME/AIRFLOW_PASSWORD nel .env)"
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
