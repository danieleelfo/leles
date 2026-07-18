"""
process_agent.py — Process Agent: riavvio di processi ESTERNI a Leles
(oggi: bar_ai). A differenza del restart di Leles stesso (che richiede
os.execv sul proprio processo bot, e resta in leles_bot.py), qui Leles
sta semplicemente uccidendo e rilanciando due processi indipendenti —
non deve riavviare se stesso per farlo.

bar_ai ha il suo venv separato da quello di Leles, quindi i binari
(python/uvicorn) vanno chiamati con il path assoluto dentro il suo
venv — un semplice 'uvicorn ...' userebbe l'interprete/venv sbagliato.
"""

import os
import subprocess
import time

BAR_AI_PATH = "/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend"
BAR_AI_VENV_PYTHON = os.path.join(BAR_AI_PATH, "venv", "bin", "python3")
BAR_AI_VENV_UVICORN = os.path.join(BAR_AI_PATH, "venv", "bin", "uvicorn")
BAR_AI_PORT = "8081"

# Pattern usati sia per pkill sia riconoscibili nel comando lanciato:
# includono il path completo del venv, così non rischiano di uccidere
# per errore l'uvicorn/bot di Leles (che vive in un altro path/venv).
_UVICORN_PKILL_PATTERN = f"{BAR_AI_VENV_UVICORN} main:app"
_BOT_PKILL_PATTERN = f"{BAR_AI_PATH}/telegram_bot.py"


def restart_bar_ai() -> str:
    """
    Kill + rilancio (detached, sopravvivono a Leles) di:
      1. uvicorn main:app --port 8081  (API bar_ai)
      2. telegram_bot.py                (bot Telegram bar_ai)
    Ritorna un report testuale per l'utente.
    """
    if not os.path.isdir(BAR_AI_PATH):
        return f"❌ Path bar_ai non trovato: {BAR_AI_PATH}"
    if not os.path.exists(BAR_AI_VENV_PYTHON):
        return f"❌ venv bar_ai non trovato: {BAR_AI_VENV_PYTHON}"

    steps = []

    # --- 1. Uvicorn (API) ---
    subprocess.run(["pkill", "-f", _UVICORN_PKILL_PATTERN], check=False)
    time.sleep(1)

    uvicorn_log = os.path.join(BAR_AI_PATH, "uvicorn_restart.log")
    with open(uvicorn_log, "a") as logfile:
        subprocess.Popen(
            [BAR_AI_VENV_UVICORN, "main:app", "--reload", "--port", BAR_AI_PORT],
            cwd=BAR_AI_PATH,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    steps.append(f"📥 API riavviata (porta {BAR_AI_PORT}), log: uvicorn_restart.log")

    # --- 2. Bot Telegram bar_ai ---
    subprocess.run(["pkill", "-f", _BOT_PKILL_PATTERN], check=False)
    time.sleep(1)

    bot_log = os.path.join(BAR_AI_PATH, "telegram_bot_restart.log")
    with open(bot_log, "a") as logfile:
        subprocess.Popen(
            [BAR_AI_VENV_PYTHON, "telegram_bot.py"],
            cwd=BAR_AI_PATH,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    steps.append("🤖 Bot Telegram bar_ai riavviato, log: telegram_bot_restart.log")

    return "✅ Restart Bar AI completato:\n\n" + "\n".join(steps)
