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
                "pattern": "port 8081",
                "args": ["/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/venv/bin/uvicorn", "main:app", "--reload", "--port", "8081"],
                "log": "uvicorn_restart.log",
                "info": "📥 API (porta 8081)",
            },
            {
                "tipo": "python",
                "pattern": "telegram_bot.py",
                "args": ["/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/venv/bin/python3", "/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend/telegram_bot.py"],
                "log": "telegram_bot_restart.log",
                "info": "🤖 Bot Telegram bar_ai",
            },
        ],
    },
    "lele_story_whisper": {
        "path": "/Users/danny/Desktop/Danny/lele_story_whisper",
        "python": "/Users/danny/Desktop/Danny/lele_story_whisper/.venv/bin/python3",
        "processi": [
            {
                "tipo": "uvicorn",
                "pattern": "port 8088",
                "args": ["/Users/danny/Desktop/Danny/lele_story_whisper/.venv/bin/uvicorn", "scripts.lele_api:app", "--reload", "--port", "8088"],
                "log": "uvicorn_whisper.log",
                "info": "📥 API Story Whisper (porta 8088)",
            },
            {
                "tipo": "python",
                "pattern": "scripts/lele_sw_bot.py",
                "args": [
                    "/Users/danny/Desktop/Danny/lele_story_whisper/.venv/bin/python3",
                    "/Users/danny/Desktop/Danny/lele_story_whisper/scripts/lele_sw_bot.py",

                ],

                "log": "story_whisper_run.log",

                "info": "🤖 Bot Telegram Story Whisper",

            },
            
        ],
    },
    "lele": {
        "path": "/Users/danny/Desktop/Danny/lele",
        "python": "/Users/danny/Desktop/Danny/lele/.venv/bin/python3",
        "processi": [
            {
                "tipo": "uvicorn",
                "pattern": "port 8080",
                "args": [
                    "/Users/danny/Desktop/Danny/lele/.venv/bin/uvicorn",
                    "scripts.lele_api:app",
                    "--reload",
                    "--port",
                    "8080",
                ],
                "log": "uvicorn_whisper.log",
                "info": "📥 API PIRATA 🏴‍☠️ (porta 8080)",
            },
            {
                "tipo": "python",
                "pattern": "scripts/lele_telegram_bot.py",
                "args": ["/Users/danny/Desktop/Danny/lele/.venv/bin/python3", "/Users/danny/Desktop/Danny/lele/scripts/lele_telegram_bot.py"],
                "log": "lele_bot_run.log",
                "info": "🤖 Bot Telegram Lelé (pirata)",
            },
        ],
    },
}

# Leles stessa: non è in PROGETTI_CONFIG (che è solo per start/stop di
# progetti ESTERNI), ma per l'health-check ha senso includerla — un
# pgrep su se stessa è innocuo e utile per avere un quadro completo in
# un solo comando invece di controllare Leles a parte.
LELES_HEALTH = {
    "label": "Leles",
    "processi": [
        {
            "tipo": "uvicorn",
            "pattern": "port 8082",
            "info": "📥 API Leles (porta 8082)",
        },
        {
            "tipo": "python",
            "pattern": "scripts/leles_bot.py",
            "info": "🤖 Bot Telegram Leles",
        },
    ],
}

# ==============================================================================
# FUNZIONI GENERICHE DI CONTROLLO
# ==============================================================================

def _health_report(tipo_filtro: str) -> str:
    """
    Controlla, per Leles + tutti i progetti in PROGETTI_CONFIG, quali
    processi del tipo richiesto ('uvicorn' o 'python') risultano vivi
    in questo momento (via pgrep), indipendentemente da git/branch.
    """
    lines = []

    all_projects = [LELES_HEALTH] + [
        {"label": name.upper(), "processi": cfg["processi"]}
        for name, cfg in PROGETTI_CONFIG.items()
    ]

    for project in all_projects:
        for proc in project["processi"]:
            if proc["tipo"] != tipo_filtro:
                continue
                
            print(f"DEBUG project = {project['label']}")
            print(f"DEBUG pattern = {repr(proc['pattern'])}")
            alive = _is_running(proc["pattern"])
            print(f"DEBUG alive = {alive}")
            icon = "✅" if alive else "❌"
            lines.append(f"{icon} [{project['label']}] {proc['info']}")

    label = "Uvicorn/API" if tipo_filtro == "uvicorn" else "Bot Telegram"
    return f"🔍 Status {label}:\n\n" + "\n".join(lines)



def uvicorn_status() -> str:
    """Controlla se le API (uvicorn) di Leles + tutti i progetti esterni sono vive."""
    return _health_report("uvicorn")


def telegram_status() -> str:
    """Controlla se i bot Telegram di Leles + tutti i progetti esterni sono vivi."""
    return _health_report("python")


def stop_process(name: str) -> str:
    """Uccide tutti i processi associati al progetto specificato."""
    if name not in PROGETTI_CONFIG:
        return f"❌ Progetto '{name}' non configurato."

    config = PROGETTI_CONFIG[name]
    steps = []
    for proc in config["processi"]:
        was_running = _is_running(proc["pattern"])
        subprocess.run(["pkill", "-f", proc["pattern"]], check=False)
        if was_running:
            steps.append(f"🛑 {proc['info']} arrestato.")
        else:
            steps.append(f"⏸️ {proc['info']} non risultava già in esecuzione.")

    return f"[{name.upper()}]\n\n" + "\n".join(steps)


def _is_running(pattern: str) -> bool:
    """
    True se esiste già un processo il cui comando contiene `pattern`.

    NOTA: niente '--' prima del pattern — su Linux è il terminatore di
    opzioni standard, ma il pgrep BSD di macOS non lo supporta e la
    ricerca fallisce silenziosamente (0 risultati anche quando il
    processo esiste davvero). Bug reale, trovato confrontando un test
    manuale (funzionante) con l'esecuzione da dentro Python (sempre ❌).
    """
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() != ""


def start_process(name: str) -> str:
    """
    Avvia in background (detached) tutti i processi del progetto specificato.
    Prima di lanciare ciascun processo controlla che non ne sia già attivo
    uno con lo stesso pattern — protezione extra contro doppie istanze
    (es. un bot Telegram lanciato a mano fuori da questo sistema, o un
    pkill fallito silenziosamente): due istanze dello stesso bot in
    polling causano un 409 Conflict lato Telegram, quindi meglio saltare
    l'avvio e segnalarlo piuttosto che duplicare.
    """
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
        if _is_running(proc["pattern"]):
            steps.append(f"⚠️ {proc['info']} già in esecuzione, salto (evito doppia istanza).")
            continue

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
