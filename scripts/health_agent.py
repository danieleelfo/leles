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
import psutil

_START_TIME = time.time()

OLLAMA_URL = "http://localhost:11434/api/tags"
OLLAMA_PS_URL = "http://localhost:11434/api/ps"
_IP_SERVICES = ("https://api.ipify.org", "https://icanhazip.com")


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


def get_public_ip(timeout: float = 5.0) -> str:
    """
    IP pubblico attuale del Mac, utile perché su rete domestica è dinamico
    e cambia nel tempo (a differenza di quello locale via socket, che non
    aiuta per raggiungere il Mac da fuori casa). Prova due servizi in
    sequenza, così un solo servizio giù non blocca il comando.
    """
    for url in _IP_SERVICES:
        try:
            r = httpx.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.text.strip()
        except Exception:
            continue
    return "impossibile recuperare l'IP pubblico (nessun servizio ha risposto)"


def get_os_status() -> str:
    """
    Stato del Mac stesso (non del processo API): CPU%, RAM, disco, uptime
    di sistema. Diverso da get_uptime(), che misura da quanto gira questo
    specifico processo uvicorn — qui è da quanto è acceso il Mac.
    """
    cpu_percent = psutil.cpu_percent(interval=0.5)

    mem = psutil.virtual_memory()
    # mem.used e mem.percent sono calcolati diversamente su macOS (nota
    # limitazione psutil): usiamo total-available per i GB, coerente con
    # come psutil calcola percent, altrimenti i due numeri si contraddicono.
    mem_used_gb = (mem.total - mem.available) / (1024 ** 3)
    mem_total_gb = mem.total / (1024 ** 3)

    # Su macOS (APFS) "/" spesso punta al volume System (piccolo, quasi
    # vuoto) invece del volume Data dove vivono davvero i file — leggere
    # "/" dà numeri fuorvianti tipo "460GB liberi" su un disco quasi pieno.
    try:
        disk = psutil.disk_usage("/System/Volumes/Data")
    except FileNotFoundError:
        disk = psutil.disk_usage("/")  # fallback, es. se mai gira su Linux
    disk_used_gb = disk.used / (1024 ** 3)
    disk_total_gb = disk.total / (1024 ** 3)

    boot_seconds = int(time.time() - psutil.boot_time())
    days, remainder = divmod(boot_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_str = f"{days}g {hours}h {minutes}m" if days else f"{hours}h {minutes}m"

    return (
        f"🖥️ CPU: {cpu_percent:.0f}%\n"
        f"🧠 RAM: {mem_used_gb:.1f} / {mem_total_gb:.1f} GB ({mem.percent:.0f}%)\n"
        f"💾 Disco: {disk_used_gb:.1f} / {disk_total_gb:.1f} GB ({disk.percent:.0f}%)\n"
        f"⏱️ Uptime Mac: {uptime_str}"
    )


def get_ram_breakdown(timeout: float = 3.0) -> str:
    """
    RAM totale del Mac + quali modelli Ollama sono caricati in questo
    momento e quanto pesano — il colpevole più probabile quando 'status
    os' mostra RAM alta, dato che gemma4/llama3 insieme superano i 14GB.

    Nota: non include i modelli Piper (TTS) — quella cache vive nel
    processo del bot Telegram, non in questo processo API, quindi non è
    leggibile da qui senza costruire un canale apposta tra i due processi.
    """
    mem = psutil.virtual_memory()
    # mem.used e mem.percent sono calcolati diversamente su macOS (nota
    # limitazione psutil): usiamo total-available per i GB, coerente con
    # come psutil calcola percent, altrimenti i due numeri si contraddicono.
    mem_used_gb = (mem.total - mem.available) / (1024 ** 3)
    mem_total_gb = mem.total / (1024 ** 3)

    lines = [
        f"🧠 RAM totale: {mem_used_gb:.1f} / {mem_total_gb:.1f} GB ({mem.percent:.0f}%)",
        "",
    ]

    try:
        r = httpx.get(OLLAMA_PS_URL, timeout=timeout)
        r.raise_for_status()
        models = r.json().get("models", [])

        if not models:
            lines.append("🦙 Ollama: nessun modello caricato in RAM al momento.")
        else:
            lines.append("🦙 Modelli Ollama in RAM ora:")
            total_ollama_gb = 0.0
            for m in models:
                size_gb = m.get("size", 0) / (1024 ** 3)
                total_ollama_gb += size_gb
                lines.append(f"  • {m.get('name', '?')}: {size_gb:.1f} GB")
            lines.append(f"  Totale Ollama: {total_ollama_gb:.1f} GB")
    except Exception as e:
        lines.append(f"🦙 Ollama: impossibile leggere i modelli caricati ({e})")

    lines.append("")
    lines.append("(Piper/TTS non incluso: vive nel processo del bot, non in questo)")

    return "\n".join(lines)
