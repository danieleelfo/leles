"""
git_agent.py — Git Agent: operazioni di sola lettura/aggiornamento sul
repo (pull, status). Riservato all'admin, invocato dal Timoniere.

Multi-progetto: da Leles si può fare pull/status non solo del proprio
repo, ma anche di altri progetti fratelli (bar_ai, ecc.), definiti nel
registro PROJECTS qui sotto.

Il restart NON vive qui: quello di Leles richiede di agire sul processo
del bot stesso (os.execv) e resta nel Process Agent dentro leles_bot.py;
quello di bar_ai (processo esterno) vive in process_agent.py.
"""

import os
import subprocess

LELES_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Registro dei progetti gestibili da qui. Aggiungere una entry per
# abilitare pull/status su un nuovo progetto fratello.
PROJECTS = {
    "leles": {
        "path": LELES_ROOT,
        "label": "Leles",
    },
    "bar_ai": {
        "path": "/Users/danny/Desktop/Danny/Work/bar_ai_demo/backend",
        "label": "Bar AI",
    },
    "lele": {
        "path": "/Users/danny/Desktop/Danny/lele",
        "label": "Lelé",
    },
    "lele_story_whisper": {
        "path": "/Users/danny/Desktop/Danny/lele_story_whisper",
        "label": "Story Whisper",
    },
    "lele_night_story": {
        "path": "/Users/danny/Desktop/Danny/lele_night_story",
        "label": "Night Story Whisper ❤️‍🔥",
    },
}


def _project_path(project: str) -> str | None:
    entry = PROJECTS.get(project)
    return entry["path"] if entry else None


def git_pull(project: str = "leles") -> str:
    """Esegue 'git pull' sulla root del progetto indicato."""
    path = _project_path(project)
    if not path:
        return f"❌ Progetto sconosciuto: '{project}'. Disponibili: {', '.join(PROJECTS)}"

    result = subprocess.run(
        ["git", "pull"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = (result.stdout + result.stderr).strip() or "(nessun output)"
    prefix = "✅" if result.returncode == 0 else "❌"
    label = PROJECTS[project]["label"]
    return f"{prefix} Pull {label} terminato:\n\n{output}"


def git_pull_force(project: str = "leles") -> str:
    """
    fetch + reset --hard origin/main — per quando 'pull report' si pianta
    per branch divergenti (es. history riscritta altrove) e non sei al
    Mac per risolverlo a mano. ATTENZIONE: distruttivo, butta via
    qualsiasi modifica locale non pushata sul progetto indicato.
    """
    path = _project_path(project)
    if not path:
        return f"❌ Progetto sconosciuto: '{project}'. Disponibili: {', '.join(PROJECTS)}"

    fetch_result = subprocess.run(
        ["git", "fetch", "origin"],
        cwd=path, capture_output=True, text=True, timeout=30,
    )
    if fetch_result.returncode != 0:
        return f"❌ Fetch fallito:\n\n{fetch_result.stderr.strip()}"

    reset_result = subprocess.run(
        ["git", "reset", "--hard", "origin/main"],
        cwd=path, capture_output=True, text=True, timeout=15,
    )

    output = (reset_result.stdout + reset_result.stderr).strip() or "(nessun output)"
    prefix = "✅" if reset_result.returncode == 0 else "❌"
    label = PROJECTS[project]["label"]
    return f"{prefix} Pull FORZATO {label} terminato (locale allineato a origin/main):\n\n{output}"


def git_status(project: str = "leles") -> str:
    """Branch corrente + ultimo commit + eventuali modifiche locali non committate."""
    path = _project_path(project)
    if not path:
        return f"❌ Progetto sconosciuto: '{project}'. Disponibili: {', '.join(PROJECTS)}"

    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=path, capture_output=True, text=True, timeout=15,
    )
    status_result = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=path, capture_output=True, text=True, timeout=15,
    )
    log_result = subprocess.run(
        ["git", "log", "-1", "--oneline"],
        cwd=path, capture_output=True, text=True, timeout=15,
    )

    branch = branch_result.stdout.strip() or "?"
    last_commit = log_result.stdout.strip() or "(nessun commit)"
    status_output = status_result.stdout.strip() or "(nessuna modifica locale)"

    ok = branch_result.returncode == 0 and status_result.returncode == 0
    prefix = "✅" if ok else "❌"
    label = PROJECTS[project]["label"]

    return (
        f"{prefix} Status {label}:\n\n"
        f"🌿 Branch: {branch}\n"
        f"📌 Ultimo commit: {last_commit}\n\n"
        f"{status_output}"
    )
    

def git_diff(project: str = "leles") -> str:
    """Restituisce il diff delle modifiche locali non committate."""
    path = _project_path(project)
    if not path:
        return f"❌ Progetto sconosciuto: '{project}'. Disponibili: {', '.join(PROJECTS)}"

    result = subprocess.run(
        ["git", "diff"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = (result.stdout + result.stderr).strip() or "(nessuna modifica nel diff)"
    prefix = "✅" if result.returncode == 0 else "❌"
    label = PROJECTS[project]["label"]

    return f"{prefix} Diff {label}:\n\n{output}"


def git_last_commit_diff(project: str = "leles") -> str:
    """
    Diff dell'ULTIMO COMMIT (già salvato nella storia), non delle modifiche
    non committate — utile dopo un 'pull report' per vedere esattamente cosa
    è cambiato nell'ultimo push, invece di 'diff' (sempre vuoto dopo un pull
    pulito, perché non ci sono modifiche locali in sospeso) o 'status'
    (mostra solo l'hash/messaggio, non il contenuto reale del cambiamento).
    """
    path = _project_path(project)
    if not path:
        return f"❌ Progetto sconosciuto: '{project}'. Disponibili: {', '.join(PROJECTS)}"

    result = subprocess.run(
        ["git", "show", "--stat", "-p", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = (result.stdout + result.stderr).strip() or "(nessun commit trovato)"
    if len(output) > 3800:
        output = output[:3800] + "\n...(troncato — diff completo troppo lungo)"

    prefix = "✅" if result.returncode == 0 else "❌"
    label = PROJECTS[project]["label"]

    return f"{prefix} Ultimo commit {label}:\n\n{output}"

