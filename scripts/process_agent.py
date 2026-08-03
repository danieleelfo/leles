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
import re
import shutil
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
                "pattern": "bar_ai_demo/backend/telegram_bot.py",
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
    "lele_night_story": {
        "path": "/Users/danny/Desktop/Danny/lele_night_story",
        "python": "/Users/danny/Desktop/Danny/lele_night_story/.venv/bin/python3",
        "processi": [
            {
                "tipo": "uvicorn",
                "pattern": "port 8666",
                "args": [
                    "/Users/danny/Desktop/Danny/lele_night_story/.venv/bin/uvicorn",
                    "scripts.lele_api:app",
                    "--reload",
                    "--port",
                    "8666",
                ],
                "log": "uvicorn_ns.log",
                "info": "📥 API Night Story 🌙 (porta 8666)",
            },
            {
                "tipo": "python",
                "pattern": "Danny/lele_night_story/scripts/lele_ns_bot.py",
                "args": [
                    "/Users/danny/Desktop/Danny/lele_night_story/.venv/bin/python3",
                    "/Users/danny/Desktop/Danny/lele_night_story/scripts/lele_ns_bot.py",
                ],
                "log": "lele_ns_bot.log",
                "info": "🤖 Bot Telegram Lelé (Night Story)",
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
                "log": "uvicorn_lele.log",
                "info": "📥 API PIRATA 🏴‍☠️ (porta 8080)",
            },
            {
                "tipo": "python",
                "pattern": "Danny/lele/scripts/lele_telegram_bot.py",
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
    "self": True,  # è il processo che sta rispondendo a questa richiesta:
                   # tautologicamente vivo, non serve pgrep (che su se
                   # stesso ha sempre dato falsi negativi, causa mai
                   # isolata con certezza — non vale più la pena
                   # rincorrerla, qui basta sapere che è "sempre su").
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

            alive = True if project.get("self") else _is_running(proc["pattern"])
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


def system_status() -> str:
    """
    Dashboard completa in stile "LELES PLATFORM": un'icona per progetto
    (uvicorn+bot combinati), servizi condivisi (Postgres/Ollama/Airflow),
    modelli Ollama effettivamente caricati, e stato git di Leles.

    Import locali (health_agent, git_agent) per lo stesso motivo spiegato
    altrove in questo file: system_status() gira sempre in contesto
    "assoluto" (chiamata solo da lele_api.py via uvicorn), quindi qui
    vanno bene gli import assoluti scripts.*.
    """
    from scripts.health_agent import check_ollama, check_postgres, check_port, check_model_loaded

    lines = ["🖥️ LELES PLATFORM\n"]

    # --- Projects: un'icona per progetto, combinando uvicorn+bot ---
    lines.append("Projects")
    lines.append("──────────────")
    all_projects = [LELES_HEALTH] + [
        {"label": name.upper(), "processi": cfg["processi"], "self": False}
        for name, cfg in PROGETTI_CONFIG.items()
    ]
    for project in all_projects:
        if project.get("self"):
            alive = True
        else:
            alive = all(_is_running(proc["pattern"]) for proc in project["processi"])
        icon = "✅" if alive else "❌"
        lines.append(f"{icon} {project['label']}")

    # --- Shared Services ---
    lines.append("\nShared Services")
    lines.append("──────────────")
    lines.append(f"{'✅' if check_postgres() else '❌'} PostgreSQL")
    lines.append(f"{'✅' if check_ollama() else '❌'} Ollama")
    lines.append(f"{'✅' if check_port(8085) else '❌'} Apache Airflow")

    # --- Models: caricati per davvero in Ollama, non solo "Ollama vivo" ---
    lines.append("\nModels")
    lines.append("──────────────")
    lines.append(f"{'🟢' if check_model_loaded('gemma4') else '⚪️'} Gemma4")
    lines.append(f"{'🟢' if check_model_loaded('llama3') else '⚪️'} Llama3")

    # --- Git (Leles stessa) ---
    lines.append("\nGit")
    lines.append("──────────────")
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=LELES_PATH, capture_output=True, text=True,
    )
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=LELES_PATH, capture_output=True, text=True,
    )
    branch = branch_result.stdout.strip() or "?"
    dirty_files = status_result.stdout.strip()
    is_clean = status_result.returncode == 0 and dirty_files == ""
    lines.append(f"Branch: {branch}")

    if is_clean:
        lines.append("Status: Clean ✅")
    else:
        file_lines = dirty_files.splitlines()
        lines.append(f"Status: ⚠️ {len(file_lines)} file modificati")
        max_shown = 8
        for f in file_lines[:max_shown]:
            lines.append(f"  {f}")
        if len(file_lines) > max_shown:
            lines.append(f"  ... e altri {len(file_lines) - max_shown}")

    return "\n".join(lines)


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
    
def restart_all() -> dict[str, str]:
    """
    Riavvia tutti i progetti registrati in PROGETTI_CONFIG.

    Ritorna un dizionario:
        {
            "bar_ai": "...",
            "lele_story_whisper": "...",
            "lele": "..."
        }
    """
    results = {}

    for name in PROGETTI_CONFIG:
        results[name] = restart_process(name)

    return results
    
# ==============================================================================
# LELES — caso speciale (non è in PROGETTI_CONFIG)
# ==============================================================================
# A differenza dei progetti in PROGETTI_CONFIG, Leles non ha un blocco di
# config con path/python/processi perché normalmente si riavvia da solo
# via os.execv (vedi handle_restart in leles_bot.py). Questa funzione
# replica lo stesso risultato ma dall'ESTERNO (es. da un DAG Airflow),
# dove non esiste un processo bot "vivo" da cui fare execv su se stesso:
# semplicemente killa e rilancia detached, sia uvicorn che il bot.
#
# ATTENZIONE: verifica LELES_PYTHON e il path dell'eseguibile uvicorn
# qui sotto — sono stati dedotti per analogia con lo schema usato dagli
# altri progetti in PROGETTI_CONFIG (.venv/bin/python3, .venv/bin/uvicorn),
# ma non sono stati confermati contro la struttura reale della cartella
# leles/.

LELES_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LELES_PYTHON = "/Users/danny/Desktop/Danny/leles/.venv/bin/python3"
LELES_UVICORN = "/Users/danny/Desktop/Danny/leles/.venv/bin/uvicorn"
LELES_API_PORT = "8082"


def restart_leles() -> str:
    """
    Riavvia Leles dall'esterno: kill + relaunch di uvicorn (porta 8082)
    e del bot Telegram (leles_bot.py), entrambi detached.

    Pensata per essere chiamata da un contesto esterno al bot stesso
    (es. task Airflow), dove os.execv non è applicabile perché non
    c'è un processo bot "in ascolto" da sostituire.
    """
    if not os.path.isdir(LELES_PATH):
        return f"❌ Path non trovato per Leles: {LELES_PATH}"
    if not os.path.exists(LELES_PYTHON):
        return f"❌ Venv/Python non trovato per Leles: {LELES_PYTHON}"

    steps = []

    # --- 1. Uvicorn (API Leles, porta 8082) ---
    was_running = _is_running("port 8082")
    subprocess.run(["pkill", "-f", "port 8082"], check=False)
    time.sleep(1.5)

    log_path = os.path.join(LELES_PATH, "uvicorn_restart.log")
    with open(log_path, "a") as logfile:
        subprocess.Popen(
            [LELES_UVICORN, "scripts.lele_api:app", "--reload", "--port", LELES_API_PORT],
            cwd=LELES_PATH,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    steps.append(
        f"📥 API Leles (porta 8082) {'riavviato' if was_running else 'avviato'}. "
        "Log: uvicorn_restart.log"
    )

    # --- 2. Bot Telegram (leles_bot.py) ---
    was_running = _is_running("scripts/leles_bot.py")
    subprocess.run(["pkill", "-f", "scripts/leles_bot.py"], check=False)
    time.sleep(1.5)

    bot_log_path = os.path.join(LELES_PATH, "leles_bot_restart.log")
    with open(bot_log_path, "a") as logfile:
        subprocess.Popen(
            [LELES_PYTHON, os.path.join(LELES_PATH, "scripts", "leles_bot.py")],
            cwd=LELES_PATH,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    steps.append(
        f"🤖 Bot Telegram Leles {'riavviato' if was_running else 'avviato'}. "
        "Log: leles_bot_restart.log"
    )

    return "✅ [LELES] Riavvio completato:\n\n" + "\n".join(steps)


def get_logs(name: str, n_lines: int = 40) -> str:
    """
    Ultime n_lines di ogni file di log configurato per il progetto — utile
    quando un processo 'parte' (start_process non verifica che resti vivo,
    solo che il comando di lancio sia partito) ma poi crasha subito dopo,
    e non sei al Mac per leggere il log a mano.
    """
    # Leles non è in PROGETTI_CONFIG (non gestisce se stessa con
    # start/stop), ma i log sono sola lettura — nessun motivo di escluderli.
    if name == "leles":
        leles_logs = [
            ("📥 API Leles", "uvicorn_restart.log"),
            ("🤖 Bot Telegram Leles", "leles_bot_restart.log"),
        ]
        sections = []
        for label, log_file in leles_logs:
            log_path = os.path.join(LELES_PATH, log_file)
            if not os.path.exists(log_path):
                sections.append(f"📄 {label} ({log_file}): file non ancora creato.")
                continue
            with open(log_path, "r", errors="replace") as f:
                lines = f.readlines()[-n_lines:]
            content = "".join(lines).strip() or "(vuoto)"
            sections.append(f"📄 {label} ({log_file}):\n{content}")

        result = f"🪵 Log [LELES] — ultime {n_lines} righe per file:\n\n" + "\n\n".join(sections)
        if len(result) > 3900:
            result = "...(troncato)...\n" + result[-3900:]
        return result

    if name not in PROGETTI_CONFIG:
        return f"❌ Progetto '{name}' non configurato."

    config = PROGETTI_CONFIG[name]
    path_progetto = config["path"]

    sections = []
    for proc in config["processi"]:
        log_path = os.path.join(path_progetto, proc["log"])

        if not os.path.exists(log_path):
            sections.append(f"📄 {proc['info']} ({proc['log']}): file non ancora creato.")
            continue

        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()[-n_lines:]

        content = "".join(lines).strip() or "(vuoto)"
        sections.append(f"📄 {proc['info']} ({proc['log']}):\n{content}")

    result = f"🪵 Log [{name.upper()}] — ultime {n_lines} righe per file:\n\n" + "\n\n".join(sections)

    # Telegram taglia a 4096 caratteri: se troppo lungo, tieni la coda
    # (le righe più recenti, quelle utili per un crash appena successo).
    if len(result) > 3900:
        result = "...(troncato)...\n" + result[-3900:]

    return result


def get_tts_status(name: str) -> str:
    """
    Elenca i modelli voce Piper (.onnx) realmente presenti in voices/ per
    un progetto — utile perché ogni progetto ha una sua cartella voices/
    separata (non tracciata da git), quindi un modello scaricato per uno
    non è automaticamente disponibile per gli altri.
    """
    if name == "leles":
        path_progetto = LELES_PATH
    elif name in PROGETTI_CONFIG:
        path_progetto = PROGETTI_CONFIG[name]["path"]
    else:
        return f"❌ Progetto '{name}' non configurato."

    voices_dir = os.path.join(path_progetto, "voices")
    alt_voices_dir = os.path.join(path_progetto, "scripts", "voices")

    onnx_files = []
    found_in = None

    if os.path.isdir(voices_dir):
        onnx_files = sorted(f for f in os.listdir(voices_dir) if f.endswith(".onnx"))
        found_in = "voices/"

    if not onnx_files and os.path.isdir(alt_voices_dir):
        onnx_files = sorted(f for f in os.listdir(alt_voices_dir) if f.endswith(".onnx"))
        if onnx_files:
            found_in = "scripts/voices/ ⚠️ POSIZIONE SBAGLIATA — il codice cerca in voices/ dalla root, non qui"

    if not onnx_files:
        return (
            f"🔊 [{name.upper()}]: nessun modello Piper trovato né in 'voices/' "
            f"né in 'scripts/voices/'."
        )

    lines = [f"🔊 Voci Piper installate [{name.upper()}] ({len(onnx_files)}) — trovate in {found_in}:"]
    for f in onnx_files:
        lines.append(f"  • {f}")

    return "\n".join(lines)


_DIR_EXCLUDE = {".git", ".venv", "__pycache__", "node_modules", ".DS_Store"}


def get_directory_listing(name: str, subpath: str = "", max_depth: int = 1) -> str:
    """
    ls-like: elenca file e sottocartelle (2 livelli di profondità) di un
    progetto, o di una sua sottocartella specifica — per verificare a
    colpo d'occhio se dei file esistono davvero, senza aspettare di
    essere al Mac (nato dal caso 'voices/ non trovata' di stasera).
    """
    if name == "leles":
        base = LELES_PATH
    elif name in PROGETTI_CONFIG:
        base = PROGETTI_CONFIG[name]["path"]
    else:
        return f"❌ Progetto '{name}' non configurato."

    target = os.path.normpath(os.path.join(base, subpath) if subpath else base)
    base_norm = os.path.normpath(base)

    # Sicurezza: impedisce di uscire dalla cartella del progetto con ../..
    if not (target == base_norm or target.startswith(base_norm + os.sep)):
        return "❌ Path non valido (fuori dalla cartella del progetto)."

    if not os.path.exists(target):
        return f"❌ [{name.upper()}] Percorso non trovato: {subpath or '(root)'}"

    if not os.path.isdir(target):
        size = os.path.getsize(target)
        return f"📄 [{name.upper()}] {subpath} — file singolo, {size / 1024:.0f}KB"

    lines = [f"📁 [{name.upper()}]{'/' + subpath if subpath else ''}"]

    def _list(path, prefix, depth):
        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            lines.append(f"{prefix}⛔ permesso negato")
            return
        for entry in entries:
            if entry in _DIR_EXCLUDE:
                continue
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                lines.append(f"{prefix}📁 {entry}/")
                if depth < max_depth:
                    _list(full, prefix + "  ", depth + 1)
            else:
                size = os.path.getsize(full)
                size_str = f"{size / 1024:.0f}KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f}MB"
                lines.append(f"{prefix}📄 {entry} ({size_str})")

    _list(target, "  ", 0)

    result = "\n".join(lines)
    if len(result) > 3900:
        result = result[:3900] + "\n...(troncato — prova con una sottocartella più specifica)"
    return result


def _resolve_project_path(name: str):
    if name == "leles":
        return LELES_PATH
    if name in PROGETTI_CONFIG:
        return PROGETTI_CONFIG[name]["path"]
    return None


def copy_tts_voices(source: str, dest: str) -> str:
    """
    Copia tutti i modelli voce Piper (.onnx + .onnx.json) da voices/ di
    un progetto a voices/ di un altro, creando la cartella di destinazione
    se non esiste. Non sovrascrive file già presenti — idempotente, si
    può rilanciare senza rischi.
    """
    source_base = _resolve_project_path(source)
    dest_base = _resolve_project_path(dest)

    if not source_base:
        return f"❌ Progetto sorgente '{source}' non configurato."
    if not dest_base:
        return f"❌ Progetto destinazione '{dest}' non configurato."

    source_voices = os.path.join(source_base, "voices")
    dest_voices = os.path.join(dest_base, "voices")

    if not os.path.isdir(source_voices):
        return f"❌ '{source}' non ha una cartella voices/ da cui copiare."

    os.makedirs(dest_voices, exist_ok=True)

    copied, skipped = [], []

    for fname in sorted(os.listdir(source_voices)):
        if not (fname.endswith(".onnx") or fname.endswith(".onnx.json")):
            continue
        src_file = os.path.join(source_voices, fname)
        dst_file = os.path.join(dest_voices, fname)
        if os.path.exists(dst_file):
            skipped.append(fname)
            continue
        shutil.copy2(src_file, dst_file)
        copied.append(fname)

    lines = [f"🔊 Copia voci {source.upper()} → {dest.upper()}:"]

    if copied:
        lines.append(f"✅ Copiati ({len(copied)}):")
        lines.extend(f"  • {f}" for f in copied)
    else:
        lines.append("Nessun file nuovo da copiare.")

    if skipped:
        base_names = sorted({f.replace(".onnx.json", "").replace(".onnx", "") for f in skipped})
        lines.append(f"⏭️ Già presenti in {dest.upper()}, saltati ({len(base_names)}): " + ", ".join(base_names))

    return "\n".join(lines)


def _get_allowed_voice_models(project: str) -> set:
    """
    Legge scripts/tts_engine.py del progetto ed estrae i nomi dei modelli
    voce configurati (i default dentro os.getenv(...)) — whitelist dinamica
    per install_tts_voice, letta dal codice reale invece che hardcoded qui
    (così resta sempre allineata a quello che il progetto usa davvero).
    """
    base = _resolve_project_path(project)
    if not base:
        return set()

    tts_engine_path = os.path.join(base, "scripts", "tts_engine.py")
    if not os.path.exists(tts_engine_path):
        return set()

    with open(tts_engine_path, "r", errors="replace") as f:
        content = f.read()

    matches = re.findall(r'os\.getenv\("TTS_VOICE_MODEL_[A-Z]{2}",\s*"([^"]+)"\)', content)
    return set(matches)


def install_tts_voice(project: str, model_name: str) -> str:
    """
    Scarica un modello voce Piper per un progetto — SOLO se model_name è
    tra le voci effettivamente configurate in quel progetto (whitelist
    letta da tts_engine.py, non testo libero passato al downloader).
    """
    base = _resolve_project_path(project)
    if not base:
        return f"❌ Progetto '{project}' non configurato."

    allowed = _get_allowed_voice_models(project)
    if not allowed:
        return f"❌ Non riesco a leggere le voci configurate per '{project}' (tts_engine.py mancante o non leggibile)."

    if model_name not in allowed:
        return (
            f"❌ '{model_name}' non è tra le voci configurate per {project.upper()}.\n"
            f"Voci valide: {', '.join(sorted(allowed))}"
        )

    voices_dir = os.path.join(base, "voices")
    os.makedirs(voices_dir, exist_ok=True)

    if project == "leles":
        python_bin = os.path.join(LELES_PATH, ".venv", "bin", "python3")
    elif project in PROGETTI_CONFIG:
        python_bin = PROGETTI_CONFIG[project]["python"]
    else:
        python_bin = os.path.join(base, ".venv", "bin", "python3")

    result = subprocess.run(
        [python_bin, "-m", "piper.download_voices", "--download-dir", "voices", model_name],
        cwd=base,
        capture_output=True,
        text=True,
        timeout=180,
    )

    output = (result.stdout + result.stderr).strip() or "(nessun output)"
    if len(output) > 3500:
        output = output[-3500:]

    prefix = "✅" if result.returncode == 0 else "❌"
    return f"{prefix} Download voce '{model_name}' per {project.upper()}:\n\n{output}"
