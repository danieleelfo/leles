"""
process_agent.py — Process Agent: controllo dinamico di processi ESTERNI
a Leles (bar_ai, lele_story_whisper, lele). Start/Stop/Restart generici
per qualsiasi progetto registrato in PROGETTI_CONFIG.

Leles stesso NON è gestibile da qui: non ha senso fargli fare "stop" di
se stesso (si spegnerebbe senza nessuno che lo riaccende), e il suo
restart richiede os.execv sul proprio processo — resta quindi come caso
speciale in leles_bot.py (Process Agent "self").

I processi qui sotto vengono lanciati detached (start_new_session=True):
sopravvivono sia al riavvio di Leles sia alla chiusura del terminale che
li ha lanciati.
"""

import os
import subprocess
import time

# ==============================================================================
# CONFIGURAZIONE PROGETTI
# ==============================================================================
# Mappa centralizzata: path, python del venv, e lista dei processi da
# gestire per ciascun progetto. I pattern di pkill includono sempre il
# path assoluto per evitare di uccidere per errore il processo di un
# altro progetto (es. un altro uvicorn su una porta diversa).
PROGETTI_CONFIG = {
    "bar_ai": {
        "path": "/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend",
        "python": "/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/venv/bin/python3",
        "processi": [
            {
                "tipo": "uvicorn",
                "pattern": "/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/venv/bin/uvicorn main:app",
                "args": ["/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/venv/bin/uvicorn", "main:app", "--reload", "--port", "8081"],
                "log": "uvicorn_restart.log",
                "info": "📥 API (porta 8081)",
            },
            {
                "tipo": "python",
                "pattern": "/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/telegram_bot.py",
                "args": ["/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/venv/bin/python3", "telegram_bot.py"],
                "log": "telegram_bot_restart.log",
                "info": "🤖 Bot Telegram bar_ai",
            },
        ],
    },
    "lele_story_whisper": {
        "path": "/Users/danny/Desktop/Danny/lele_story_whisper",
        "python": "/Users/danny/Desktop/Danny/lele_story_whisper/venv/bin/python3",
        "processi": [
            {
                "tipo": "uvicorn",
                "pattern": "/Users/danny/Desktop/Danny/lele_story_whisper/venv/bin/uvicorn main:app",
                "args": ["/Users/danny/Desktop/Danny/lele_story_whisper/venv/bin/uvicorn", "main:app", "--reload", "--port", "8088"],
                "log": "uvicorn_whisper.log",
                "info": "📥 API Story Whisper (porta 8088)",
            },
            {
                "tipo": "python",
                "pattern": "/Users/danny/Desktop/Danny/lele_story_whisper/main.py",
                "args": ["/Users/danny/Desktop/Danny/lele_story_whisper/venv/bin/python3", "main.py"],
                "log": "story_whisper_run.log",
                "info": "📖 Script Story Whisper",
            },
        ],
    },
    "lele": {
        "path": "/Users/danny/Desktop/Danny/lele",
        "python": "/Users/danny/Desktop/Danny/lele/venv/bin/python3",
        "processi": [
            {
                "tipo": "uvicorn",
                "pattern": "/Users/danny/Desktop/Danny/lele/venv/bin/uvicorn lele_api:app",
                "args": ["/Users/danny/Desktop/Danny/lele/venv/bin/uvicorn", "lele_api:app", "--reload", "--port", "8080"],
                "log": "uvicorn_lele.log",
                "info": "📥 API Lelé (porta 8080)",
            },
            {
                "tipo": "python",
                "pattern": "/Users/danny/Desktop/Danny/lele/lele_telegram_bot.py",
                "args": ["/Users/danny/Desktop/Danny/lele/venv/bin/python3", "lele_telegram_bot.py"],
                "log": "lele_bot_run.log",
                "info": "🤖 Bot Telegram Lelé (pirata)",
            },
        ],
    },
}


# ==============================================================================
# FUNZIONI GENERICHE DI CONTROLLO
# ==============================================================================

def stop_process(name: str) -> str:
    """Uccide tutti i processi associati al progetto specificato."""
    if name not in PROGETTI_CONFIG:
        return f"❌ Progetto '{name}' non configurato."

    config = PROGETTI_CONFIG[name]
    for proc in config["processi"]:
        subprocess.run(["pkill", "-f", proc["pattern"]], check=False)

    return f"🛑 [{name.upper()}] Tutti i processi associati sono stati arrestati."


def start_process(name: str) -> str:
    """Avvia in background (detached) tutti i processi del progetto specificato."""
    if name not in PROGETTI_CONFIG:
        return f"❌ Progetto '{name}' non configurato."

    config = PROGETTI_CONFIG[name]
    path_progetto = config["path"]
    python_progetto = config["python"]

    if not os.path.isdir(path_progetto):
        return f"❌ Path non trovato per {name}: {path_progetto}"
    if not os.path.exists(python_progetto):
        return f"❌ Venv/Python non trovato per {name}: {python_progetto}"

    steps = []
    for proc in config["processi"]:
        log_path = os.path.join(path_progetto, proc["log"])
        with open(log_path, "a") as logfile:
            subprocess.Popen(
                proc["args"],
                cwd=path_progetto,
                stdout=logfile,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        steps.append(f"{proc['info']} avviato. Log: {proc['log']}")

    return f"✅ [{name.upper()}] Avvio completato:\n\n" + "\n".join(steps)


def restart_process(name: str) -> str:
    """Stop + start del progetto richiesto. Pensato per i trigger Telegram."""
    if name not in PROGETTI_CONFIG:
        return f"❌ Progetto '{name}' non configurato."

    stop_process(name)
    time.sleep(1.5)  # pausa di sicurezza per il rilascio di porte/risorse

    risultato_start = start_process(name)
    return risultato_start.replace("Avvio completato", "Riavvio completato")
