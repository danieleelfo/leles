"""
airflow_agent.py — Trigger e status di DAG Airflow via REST API (JWT, v2 —
Airflow 3.x), con estrazione parametri in linguaggio naturale via LLM (Ollama)
per il trigger.

Flusso trigger:
    "exec airflow <richiesta in linguaggio naturale>"
        │
    "exec airflow <richiesta>"
        │
        ├─► _parse_save_file_request()     — Bypass LLM per salvataggio file
        ├─► _parse_explicit_conf_request() — Bypass LLM se presente conf: {...}
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

ATTENZIONE: KNOWN_DAGS qui sotto va tenuto aggiornato con i dag_id reali
del tuo Airflow e i parametri che ciascuno si aspetta in `conf`, altrimenti
l'LLM non ha modo di sapere cosa esiste e rischia di inventare dag_id a
caso (per questo route() rifiuta comunque qualsiasi dag_id non presente
in questo dizionario, vedi extract_dag_params).
"""

import re
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
# Tipi/default presi dai rispettivi file DAG.
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
    "decisione_dag": {
        "description": "Estrae la decisione/conclusione presa in una run Emergence Lab già completata (analyze_decision, LLM-as-a-Judge)",
        "params": {
            "run_id": "int, obbligatorio — ID di una run già esistente e completata",
            "judge_model": "str, opzionale, default 'deepseek-r1'",
        },
    },
    "decisione_run_dag": {
        "description": "Analisi decisionale completa di una run Emergence Lab: analizza ogni iterazione singolarmente, ricostruisce l'evoluzione del processo decisionale e infine estrae/valida la decisione finale (pipeline TaskFlow multi-step con dynamic mapping — più approfondita e lenta del semplice decisione_dag).",
        "params": {
            "emergence_run_id": "int, obbligatorio — ID di una run già esistente e completata (ATTENZIONE: qui la chiave e' 'emergence_run_id', NON 'run_id' come negli altri DAG decisionali)",
            "judge_model": "str, opzionale, default 'mistral'",
            "judge_role": "str, opzionale, default 'CTO, Expert in data, Analista Decisionale ed Esperto di Dinamiche di Gruppo Multi-Agente'",
        },
    },
    "sintetizza_dag": {
        "description": "Sintetizza i risultati di una run Emergence Lab già completata: analizza tutti e 12 i ruoli individualmente + un'analisi globale (analyze_run, LLM-as-a-Judge)",
        "params": {
            "run_id": "int, obbligatorio — ID di una run già esistente e completata",
            "model": "str, opzionale, default 'deepseek-r1'",
            "pipeline_config": "str (JSON), opzionale — solo se serve passare contesto aggiuntivo",
        },
    },
    "save_file_dag": {
        "description": "Salva un file locale. Sintassi: 'salva file <path> con contenuto <<<CONTENUTO...CONTENUTO>>>'",
        "params": {
            "file_path": "str, path assoluto (es. /Users/danny/Desktop/Danny/Leles/AI_TMP/test.py)",
            "content": "str, contenuto del file (DEVE essere tra <<<CONTENUTO e CONTENUTO>>>)",
        },
    },
    "improve_dag": {
        "description": "Refactoring/aggiunta feature guidata da agenti multi-modello (Emergence Lab) su un singolo file .py esistente, con sintesi finale in AI_TMP (markdown riassuntivo, mode='resume' di default — non genera file di codice pronti a meno di modificare generate_final_artifacts per mode='code').",
        "params": {
            "target_file_path": "str, obbligatorio — path assoluto del file .py da migliorare",
            "feature_request": "str, opzionale — istruzioni su cosa migliorare (default generico se omesso)",
            "num_iterations": "int, opzionale, default 3",
            "temperature": "float, opzionale, default 0.7",
            "seed": "int, opzionale, default 42",
            "synthesizer_model": "str, opzionale, default 'qwen2.5'",
            "output_dir": "str, opzionale, default '/Users/danny/Desktop/Danny/AI_TMP'",
        },
    },
    "emergence_flow": {
        "description": "Pipeline completa in un unico DAG: lancia una nuova simulazione multi-agente e poi l'analisi finale (target_role), senza dipendere da trigger inter-DAG (sostituisce il vecchio emergence_full_pipeline).",
        "params": {
            "scenario": "str, default 'Design coordinamento agenti'",
            "num_iterations": "int, default 3",
            "judge_model": "str, default 'qwen2.5'",
            "target_role": "str, default 'ALL' (es. 'Planner', 'Critic', 'Sheriff', ecc.)",
            "temperature": "float, opzionale, default 0.7",
            "seed": "int, opzionale, default 42",
            "pipeline_config": "str (JSON), opzionale, default '{\"model_strategy\":\"fixed\"}'",
        },
    },
    "process_multiple_files": {
        "description": "Sposta MULTIPLI file, ognuno nella SUA destinazione. file_paths e target_paths devono avere la stessa lunghezza. Confermato funzionante in produzione (2026-09-09) per deployare file core via Telegram quando 'salva file' testuale non è praticabile per dimensione. IMPORTANTE: senza 'overwrite': true il comportamento osservato è 'successo' riportato ma NESSUNA copia reale se il file di destinazione esiste già — includerlo sempre esplicitamente.",
        "params": {
            "file_paths": "list, obbligatorio — lista di path assoluti dei file sorgente",
            "target_paths": "list, obbligatorio — lista di path di destinazione (uno per ogni file)",
            "overwrite": "bool, fortemente raccomandato = true — vedi nota sopra",
        },
    },
    "process_uploaded_file": {
        "description": "Sposta un file gia' presente sul filesystem da file_path a target_path (dentro le directory consentite: leles, airflow, AI_TMP). Usato per spostare file salvati manualmente prima del lancio.",
        "params": {
            "file_path": "str, obbligatorio — path assoluto del file sorgente",
            "target_path": "str, opzionale, default '/Users/danny/Desktop/Danny/leles/'",
        },
    },
    "memory_summary_dag": {
        "description": "Consolida il report di una run Emergence Lab nella tabella di memoria storica (emergence.memory_run_summary). Estrae la decisione con un giudice LLM e la salva in DB.",
        "params": {
            "run_id": "int, obbligatorio — ID di una run già esistente e completata",
            "judge_model": "str, opzionale, default 'llama3'",
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
                "options": {"temperature": 0.1, "num_predict": 1024},
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


_SAVE_FILE_RE = re.compile(
    r"salva\s+(?:il\s+)?file\s+(?P<path>\S+)\s+con\s+contenuto\s*:?\s*"
    r"<<<CONTENUTO\s*(?P<content>.*?)\s*CONTENUTO>>>",
    re.IGNORECASE | re.DOTALL,
)


def _parse_save_file_request(user_text: str):
    """
    Estrae (file_path, content) da 'salva file <path> con contenuto
    <<<CONTENUTO ... CONTENUTO>>>' SENZA passare dall'LLM.

    Bypass intenzionale di extract_dag_params(): un LLM che deve
    reincapsulare codice sorgente arbitrario (virgolette triple, newline,
    backslash) dentro JSON è strutturalmente inaffidabile — prima o poi
    rompe l'escaping (visto in pratica: un docstring con \"\"\" ha rotto
    il JSON generato dall'LLM). Qui il contenuto va dritto in `json_body`
    via requests, che gestisce l'escaping correttamente in automatico.

    Ritorna None se il testo non matcha il pattern (fallback normale a
    extract_dag_params, per gli altri DAG che non hanno questo problema).
    """
    match = _SAVE_FILE_RE.search(user_text)
    if not match:
        return None
    return match.group("path").strip(), match.group("content")



_EXPLICIT_CONF_RE = re.compile(
    r"lancia\s+(?P<dag_id>[a-zA-Z0-9_-]+)\s+conf\s*:\s*(?P<conf_json>\{.*\})",
    re.IGNORECASE | re.DOTALL,
)


def _parse_explicit_conf_request(user_text: str):
    """
    Se l'utente scrive esplicitamente 'lancia <dag_id> conf: {...}',
    estrae il JSON direttamente via codice ed evita di passare dall'LLM,
    prevenendo troncamenti dello scenario o allucinazioni del modello.
    """
    match = _EXPLICIT_CONF_RE.search(user_text.strip())
    if not match:
        return None, None, None

    dag_id = match.group("dag_id").strip()
    conf_raw = match.group("conf_json").strip()

    if dag_id not in KNOWN_DAGS:
        return None, None, f"DAG '{dag_id}' non riconosciuto (non in KNOWN_DAGS)"

    try:
        conf = json.loads(conf_raw)
        return dag_id, conf, None
    except json.JSONDecodeError as e:
        return None, None, f"JSON in 'conf' non valido: {e}"


def airflow_agent(user_text: str) -> str:
    """
    Entry point chiamato da lele_api.py. `user_text` è già ripulito del
    prefisso "exec airflow" — vedi parse_airflow_command in timoniere.py.
    """
    if not user_text.strip():
        known = ", ".join(KNOWN_DAGS.keys()) or "(nessuno registrato)"
        return f"🌬️ Dimmi quale DAG lanciare e con che parametri. DAG conosciuti: {known}"

    # 'salva file' bypassa l'LLM — vedi nota in _parse_save_file_request.
    save_request = _parse_save_file_request(user_text)
    if save_request:
        file_path, file_content = save_request
        conf = {"file_path": file_path, "file_content": file_content}
        ok, result = trigger_dag_run("save_file_dag", conf)
        if not ok:
            return result
        return f"🌀 DAG 'save_file_dag' lanciato — run_id: {result}\nfile_path: {file_path} ({len(file_content)} caratteri)"
        
        # Bypass LLM se l'utente fornisce direttamente un blocco 'conf: {...}'
    exp_dag_id, exp_conf, exp_error = _parse_explicit_conf_request(user_text)
    if exp_error:
        return f"❌ {exp_error}"
    if exp_dag_id:
        ok, result = trigger_dag_run(exp_dag_id, exp_conf)
        if not ok:
            return result
        conf_str = json.dumps(exp_conf, ensure_ascii=False)
        return f"🌀 DAG '{exp_dag_id}' lanciato (Bypass LLM OK) — run_id: {result}\nconf: {conf_str}"

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
    "success": "❇️🟢👌🥳",
    "failed": "❌",
    "running": "🔄🏴‍☠️🧜",
    "queued": "⏳😭",
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


def set_dag_paused(dag_id: str, paused: bool) -> str:
    """
    PATCH /api/v2/dags/{dag_id} — attiva/disattiva un DAG (pause/unpause).
    Un DAG appena salvato su disco parte sempre in pausa di default: senza
    questo comando andava attivato a mano dalla UI di Airflow sul Mac,
    impedendo di completare il ciclo "crea + testa DAG" interamente da
    Telegram.
    """
    try:
        response = _api_request(
            "PATCH",
            f"/api/v2/dags/{dag_id}?update_mask=is_paused",
            json_body={"is_paused": paused},
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

    stato = "attivato ▶️" if not paused else "messo in pausa ⏸️"
    return f"✅ DAG '{dag_id}' {stato}."


# --- Generazione automatica snippet di integrazione per un nuovo DAG -------
#
# Flusso 'crea dag <descrizione>':
#   LLM (Ollama) legge la descrizione + due esempi reali già presenti nel
#   codice (is_decision_run_trigger/parse_decision_run_args in timoniere.py,
#   e l'handler AGENT_DECISION_RUN in lele_api.py) e genera per analogia gli
#   snippet per il nuovo DAG. L'output NON tocca mai timoniere.py/lele_api.py
#   direttamente — viene scritto in AI_TMP/airflow_incoming/ per revisione
#   manuale e copia-incolla da parte di Danny, stesso principio di sicurezza
#   di IMPROVE (disabilitato via Telegram perché modifica file locali).

# Calcolato dinamicamente da __file__ (mai hardcoded — vedi memoria progetto):
# questo file vive in scripts/, la project root è la sua cartella genitrice.
_PROJECT_ROOT_FOR_SCAFFOLD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAG_SCAFFOLD_OUTPUT_DIR = os.path.join(_PROJECT_ROOT_FOR_SCAFFOLD, "AI_TMP", "airflow_incoming")

SYSTEM_CREA_DAG = """Sei un ingegnere software che estende un router deterministico Python
(pattern matching su stringhe, NIENTE LLM nel routing) per Lelé/Leles.

Riceverai la descrizione in linguaggio naturale di un nuovo comando che deve
lanciare un DAG Airflow via `trigger_dag_run(dag_id, conf)` (già esistente,
NON reimplementarla).

Genera ESATTAMENTE tre blocchi di codice Python, in quest'ordine, seguendo
alla lettera lo stile ed i pattern degli esempi:

1. Blocco per timoniere.py: una funzione `is_<nome>_trigger(text) -> bool`
   che riconosce il comando testuale, e una `parse_<nome>_args(text)` che ne
   estrae i parametri. Aggiungi anche la riga `AGENT_<NOME> = "<nome_dag>"`
   e la riga da inserire in route() (`if is_<nome>_trigger(text): return AGENT_<NOME>`).

2. Blocco per lele_api.py: l'handler `if agent == AGENT_<NOME>: ...` che
   costruisce `conf` dai parametri estratti e chiama
   `trigger_dag_run("<dag_id>", conf)`, ritornando subito il dag_run_id
   (il DAG è asincrono, NON attendere il completamento).

3. Blocco per airflow_agent.py: la voce da aggiungere a KNOWN_DAGS.

ESEMPIO REALE DI RIFERIMENTO (stesso identico pattern, adattalo, non copiarlo
se il nuovo comando ha parametri diversi):

--- timoniere.py ---
def is_decision_run_trigger(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("decisione run ") or t.startswith("decisione dag ")

def parse_decision_run_args(text: str):
    t = text.strip()
    low = t.lower()
    for prefix in ("decisione run ", "decisione dag "):
        if low.startswith(prefix):
            parts = t[len(prefix):].strip().split()
            if not parts:
                return None, None
            try:
                run_id = int(parts[0])
            except ValueError:
                return None, None
            judge_model = parts[1] if len(parts) > 1 else None
            return run_id, judge_model
    return None, None

--- lele_api.py ---
if agent == AGENT_DECISION_RUN:
    run_id, judge_model = parse_decision_run_args(user_input)
    if run_id is None:
        result = "Uso: 'decisione run <run_id> [judge_model]'"
    else:
        conf = {"emergence_run_id": run_id}
        if judge_model:
            conf["judge_model"] = judge_model
        ok, result_id = trigger_dag_run("decisione_run_dag", conf)
        result = f"DAG lanciato - run_id: {result_id}" if ok else result_id
    save_memory("USER", user_input)
    return {"answer": result, "type": AGENT_DECISION_RUN}

REGOLE TASSATIVE:
- Output SOLO codice Python nei tre blocchi, nessuna spiegazione fuori dai blocchi.
- Ogni blocco preceduto da un commento `# === BLOCCO N: <file> ===`.
- Non inventare funzioni che non esistono (trigger_dag_run, save_memory sono già disponibili).
- Nomi coerenti tra i tre blocchi (stesso AGENT_<NOME>, stesso dag_id).
"""


def generate_dag_integration_snippets(description: str) -> str:
    """
    Genera (via Ollama) gli snippet di integrazione timoniere.py + lele_api.py
    + KNOWN_DAGS per un nuovo comando/DAG, a partire da una descrizione in
    linguaggio naturale, e li salva in AI_TMP/airflow_incoming/ per revisione
    manuale. Non scrive MAI su timoniere.py o lele_api.py direttamente.
    """
    if not description.strip():
        return "🌬️ Dimmi cosa deve fare il nuovo comando/DAG (es. 'crea dag lancia memory_summary_dag per la run X')."

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_CREA_DAG},
                    {"role": "user", "content": description},
                ],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 2500},
            },
            timeout=180,
        )
        response.raise_for_status()
        snippets = response.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"❌ LLM non raggiungibile: {e}"

    if not snippets:
        return "❌ L'LLM ha prodotto una risposta vuota, riprova o riformula la descrizione."

    os.makedirs(DAG_SCAFFOLD_OUTPUT_DIR, exist_ok=True)
    filename = f"dag_scaffold_{uuid.uuid4().hex[:8]}.py"
    output_path = os.path.join(DAG_SCAFFOLD_OUTPUT_DIR, filename)

    header = (
        f'"""\n'
        f"Scaffold generato automaticamente da 'crea dag' — SOLO REVIEW, non live.\n"
        f"Descrizione richiesta:\n{description}\n\n"
        f"Copia manualmente i blocchi giusti in timoniere.py / lele_api.py /\n"
        f"airflow_agent.py (KNOWN_DAGS) dopo revisione.\n"
        f'"""\n\n'
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + snippets)

    return (
        f"🌀 Scaffold generato: {output_path}\n"
        f"Revisiona e copia i blocchi in timoniere.py / lele_api.py / "
        f"KNOWN_DAGS (airflow_agent.py) — nessun file live è stato toccato."
    )


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
