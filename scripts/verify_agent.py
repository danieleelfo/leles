"""
verify_agent.py — Verifica di sintassi + logica per un file Python, pensata
per essere affidabile invece che creativa.

Due passaggi, in quest'ordine:
1. py_compile: check deterministico, zero LLM, zero allucinazioni possibili.
   Se il file ha un errore di sintassi vero, questo lo dice con certezza.
2. gemma4 (solo, niente passaggio llama3 "enhancer"): review logica con un
   prompt che vieta esplicitamente di inventare funzioni/variabili non
   presenti nel file. Se serve contesto che non ha, deve dirlo, non inventare.

Diverso da improve_agent.py (improver_agent.py): quello è pensato per idee
creative/refactoring, questo è pensato per essere corretto anche a costo
di essere meno ambizioso nei suggerimenti.
"""

import os
import subprocess
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_VERIFY = """
You are a strict Python code auditor. You ONLY see the file provided below —
nothing else in the codebase exists for you.

Hard rules:
- NEVER reference, call, or suggest a function/variable/class/import that is
  not literally defined or imported in the code you were given.
- If a check would require knowledge of code outside this file (another
  module, a class defined elsewhere), say so explicitly instead of guessing
  or inventing what it might contain.
- Do NOT propose stylistic refactors, naming preferences, or "nice to have"
  suggestions. Focus ONLY on: logic bugs, incorrect control flow, exceptions
  that could crash the program at runtime, unreachable code, race conditions,
  off-by-one errors.
- Every code snippet you propose must use ONLY names that already exist in
  the file shown. If you are not certain, describe the issue in prose
  instead of writing code for it.
- If you find nothing wrong, say so plainly. Do not invent an issue just to
  have something to report.
- Reply in italian, in dialetto barese se ti va, ma resta preciso e tecnico.
"""


def _syntax_check(filepath: str) -> tuple[bool, str]:
    """
    Ritorna (ok, messaggio). Deterministico: nessun modello coinvolto,
    quindi nessun rischio di falsi positivi/negativi da allucinazione.
    """
    result = subprocess.run(
        ["python3", "-m", "py_compile", filepath],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0:
        return True, "✅ Sintassi valida, nessun errore di compilazione."
    else:
        return False, f"❌ Errore di sintassi:\n{result.stderr.strip()}"


def _read_file(filepath: str):
    if not os.path.exists(filepath):
        return None, f"❌ File non trovato: {filepath}"
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read(), None


def _ask_gemma_strict(filepath: str, code: str) -> str:
    prompt = f"""
File: {filepath}

Code:
{code}

Verifica logica di questo file, seguendo rigorosamente le regole del system prompt:
"""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": "gemma4:latest",
                "messages": [
                    {"role": "system", "content": SYSTEM_VERIFY},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.1,  # bassa: meno creatività, meno invenzioni
                    "num_predict": 4000,
                },
            },
            timeout=180,
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"[ERRORE gemma4] {str(e)}"


def verify_agent(filepath: str) -> str:
    """
    Esegue il check di sintassi, poi (solo se la sintassi è valida) la
    review logica di gemma4. Ritorna un report testuale unico pronto
    per essere rispedito su Telegram.
    """
    code, error = _read_file(filepath)
    if error:
        return error

    syntax_ok, syntax_msg = _syntax_check(filepath)

    if not syntax_ok:
        # Se il file non compila nemmeno, non ha senso far ragionare gemma4
        # sulla logica di codice che non gira comunque.
        return f"{syntax_msg}\n\n⚠️ Salto la verifica logica: sistema prima l'errore di sintassi."

    logic_review = _ask_gemma_strict(filepath, code)

    return f"{syntax_msg}\n\n🧠 REVIEW LOGICA (gemma4):\n\n{logic_review}"
