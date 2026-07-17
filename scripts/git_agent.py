"""
git_agent.py — Git Agent: operazioni di sola lettura/aggiornamento sul
repo (pull, status). Riservato all'admin, invocato dal Timoniere sia
via Telegram (/ask) sia potenzialmente da CLI.

Il restart (kill + rilancio di uvicorn e del bot) NON vive qui: quello
richiede di agire sul processo del bot stesso (os.execv), quindi resta
nel Process Agent dentro leles_bot.py. Questo file copre solo git.
"""

import os
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git_pull() -> str:
    """Esegue 'git pull' sulla root del progetto e ritorna un report testuale."""
    result = subprocess.run(
        ["git", "pull"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = (result.stdout + result.stderr).strip() or "(nessun output)"
    prefix = "✅" if result.returncode == 0 else "❌"
    return f"{prefix} Pull terminato:\n\n{output}"


def git_status() -> str:
    """Branch corrente + ultimo commit + eventuali modifiche locali non committate."""
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
    )
    status_result = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
    )
    log_result = subprocess.run(
        ["git", "log", "-1", "--oneline"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
    )

    branch = branch_result.stdout.strip() or "?"
    last_commit = log_result.stdout.strip() or "(nessun commit)"
    status_output = status_result.stdout.strip() or "(nessuna modifica locale)"

    ok = branch_result.returncode == 0 and status_result.returncode == 0
    prefix = "✅" if ok else "❌"

    return (
        f"{prefix} Status:\n\n"
        f"🌿 Branch: {branch}\n"
        f"📌 Ultimo commit: {last_commit}\n\n"
        f"{status_output}"
    )
