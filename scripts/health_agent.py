"""
health_agent.py — Health Agent: controlli di salute dei servizi condivisi
(Ollama, Postgres) e uptime del processo API. Distinto dal Process Agent
(process_agent.py), che controlla se i PROCESSI (uvicorn/bot) sono vivi
via pgrep — questo controlla se i SERVIZI dietro di loro rispondono
davvero (un processo può essere vivo ma con Ollama giù, ad esempio).

Pensato come base per:
  - GET /health (lele_api.py) — per monitoring esterno (es. futuri DAG Airflow)
  - comando Telegram "status sistema" — dashboard completa in una vista
"""

import socket
import time

import httpx

_START_TIME = time.time()

OLLAMA_URL = "http://localhost:11434/api/tags"


def check_ollama(timeout: float = 2.0) -> bool:
    """True se Ollama risponde sulla sua porta di default (11434)."""
    try:
        r = httpx.get(OLLAMA_URL, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def check_model_loaded(model_name: str, timeout: float = 2.0) -> bool:
    """
    True se `model_name` compare tra i modelli disponibili in Ollama
    (interroga /api/tags e cerca il nome, es. 'gemma4' matcha anche
    'gemma4:latest'). Se Ollama stesso non risponde, ritorna False.
    """
    try:
        r = httpx.get(OLLAMA_URL, timeout=timeout)
        if r.status_code != 200:
            return False
        models = r.json().get("models", [])
        return any(model_name in m.get("name", "") for m in models)
    except Exception:
        return False


def check_port(port: int, host: str = "localhost", timeout: float = 1.5) -> bool:
    """True se qualcosa sta ascoltando su `host:port` (usato per Airflow)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def check_postgres(timeout: float = 2.0) -> bool:
    """True se Postgres accetta connessioni e risponde a un SELECT 1."""
    try:
        from core.db import get_connection  # import locale: vedi nota in process_agent.py
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            return True
        finally:
            conn.close()
    except Exception:
        return False


def get_uptime() -> str:
    """Uptime del processo API corrente (da quando è partito questo uvicorn)."""
    seconds = int(time.time() - _START_TIME)
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"
