import re
import requests
import os
from core.memoryPG import save_memory

OLLAMA_URL = "http://localhost:11434/api/chat"

# Sopra i ~18k caratteri, sommando i 3 step (originale + draft + review, tutti
# nel contesto dello step finale) si rischia di sforare num_ctx=16384. Soglia
# più bassa dei 40k di prima apposta: qui il contesto si accumula su 3 step,
# non è un singolo passaggio.
MAX_FILE_CHARS = 18000

# Regola di grounding condivisa dai tre step — è il motivo per cui in
# passato lo step "llama3 enhance" era stato rimosso: tendeva a inventare
# funzioni/variabili che non esistevano nel file originale. La riproponiamo
# ma con questo vincolo esplicito e ripetuto in ogni step.
GROUNDING_RULE = """
REGOLA FERREA — NIENTE INVENZIONI:
- Puoi usare SOLO nomi (funzioni, variabili, classi, import) che esistono
  già letteralmente nel codice mostrato sotto.
- Se proponi qualcosa di NUOVO (una funzione, un import, una libreria),
  marcalo esplicitamente come "NUOVO:" e spiega perché serve — non
  introdurlo come se esistesse già nel file.
- Se un fix richiederebbe di sapere cosa c'è in un ALTRO file (non quello
  mostrato), dillo esplicitamente invece di indovinare cosa contiene.
"""

SYSTEM_LLAMA_DRAFT = f"""
You are an expert Python engineer. You are given a Python file and asked to
propose a REVISED, improved version of it — fixing bugs, improving
readability and performance where it's clearly justified.

{GROUNDING_RULE}

Output format:
1. A short bullet list of what you changed and why (max 6 bullets).
2. Then the FULL revised file in a single ```python code block — complete,
   ready to run, not a diff or excerpt.
"""

SYSTEM_GEMMA_TEST_REASONING = f"""
You are a rigorous Python code reviewer and tester. You are given the
ORIGINAL file and a DRAFT revision of it proposed by another engineer.
Your job is NOT to rewrite the code — it's to critically review the draft.

{GROUNDING_RULE}

Specifically:
- Compare the draft against the original: does it introduce any name
  (function/variable/import) that isn't in the original and isn't clearly
  marked "NUOVO:"? Call this out explicitly — it's the #1 failure mode to
  catch.
- Reason through concrete test scenarios: given typical/edge-case inputs,
  trace step by step what the draft's code would actually do, and say
  whether it matches the expected behavior. Do this for at least 2-3
  scenarios if the file's logic allows it. This is reasoning, not real
  execution — think it through like a human doing a careful code trace.
- Flag regressions: anything the draft breaks that worked in the original.
- Be concise and specific — reference line numbers/function names.
"""

SYSTEM_LLAMA_FINAL = f"""
You are an expert Python engineer finalizing a code revision. You are given
the ORIGINAL file, your own DRAFT revision, and a reviewer's feedback on
that draft. Produce the FINAL version, incorporating valid feedback and
fixing anything the reviewer correctly flagged.

{GROUNDING_RULE}

If the reviewer flagged something you disagree with, briefly say why you're
not applying it — don't silently ignore feedback. Output the FULL final
file in a single ```python code block — complete, ready to run, not a diff
or excerpt.
"""


def ask_ollama(system, prompt, model="llama3:latest", num_predict=3000):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.4,
                    "num_ctx": 16384,     
                    "num_predict": num_predict,
                    "think": False
                }
            },
            timeout=300
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"[ERROR] {str(e)}"


def read_file(filepath):
    if not os.path.exists(filepath):
        return None, f"❌ File not found: {filepath}"
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read(), None


def extract_code_block(text):
    """Estrae il contenuto dell'ULTIMO blocco ```python ... ``` (o ``` ... ```
    generico) da un output LLM. None se non trovato — usato per salvare la
    versione finale come file vero e proprio."""
    matches = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return matches[-1].strip() if matches else None


def llama_draft(filepath, code):
    prompt = f"""
File: {filepath}

Original code:
{code}

Propose a revised version.
"""
    print("⚙️  Llama3 drafting improved version...")
    return ask_ollama(SYSTEM_LLAMA_DRAFT, prompt, model="llama3:latest", num_predict=3500)


def gemma_test_review(filepath, original_code, draft):
    prompt = f"""
File: {filepath}

ORIGINAL code:
{original_code}

DRAFT revision proposed:
{draft}

Review the draft as instructed.
"""
    print("🧪 Gemma4 reviewing draft (test-case reasoning)...")
    return ask_ollama(SYSTEM_GEMMA_TEST_REASONING, prompt, model="gemma4:latest", num_predict=3000)


def llama_finalize(filepath, original_code, draft, review):
    prompt = f"""
File: {filepath}

ORIGINAL code:
{original_code}

YOUR DRAFT:
{draft}

REVIEWER FEEDBACK:
{review}

Produce the FINAL version.
"""
    print("🏁 Llama3 finalizing...")
    return ask_ollama(SYSTEM_LLAMA_FINAL, prompt, model="llama3:latest", num_predict=3500)


def improve_agent(filepath, chat_id=None):
    # STEP 1: leggi file
    code, error = read_file(filepath)
    if error:
        print(error)
        return None

    print(f"📂 File loaded: {filepath} ({len(code)} chars)\n")

    # Safeguard: qui il contesto si accumula su 3 step (vedi MAX_FILE_CHARS).
    if len(code) > MAX_FILE_CHARS:
        return (
            f"⚠️ Il file è troppo grande per la pipeline a 3 step "
            f"(>{MAX_FILE_CHARS} caratteri, qui ne ha {len(code)}). "
            f"Spezzalo in moduli più piccoli."
        )

    # STEP 2: llama3 propone una prima revisione
    draft = llama_draft(filepath, code)
    print("\n🏴‍☠️ LLAMA3 DRAFT:\n")
    print(draft)
    save_memory("IMP_LLAMA_DRAFT_ES", f"[{filepath}]\n{draft}", chat_id=chat_id)

    # STEP 3: gemma4 la rivede e ragiona su casi di test (nessuna esecuzione
    # reale — è un trace mentale del codice, non un pytest vero)
    review = gemma_test_review(filepath, code, draft)
    print("\n🧪 GEMMA4 REVIEW:\n")
    print(review)
    save_memory("IMP_GEMMA_ES", f"[{filepath}]\n{review}", chat_id=chat_id)

    # STEP 4: llama3 produce la versione finale incorporando il feedback
    final = llama_finalize(filepath, code, draft, review)
    print("\n🏁 LLAMA3 FINAL:\n")
    print(final)
    save_memory("IMP_LLAMA_FINAL_ES", f"[{filepath}]\n{final}", chat_id=chat_id)

    # Se il finale contiene un blocco di codice completo, lo salviamo
    # AFFIANCO all'originale — MAI sovrascritto in automatico, così puoi
    # confrontare/applicare a mano (git diff, review, ecc.)
    final_code = extract_code_block(final)
    saved_path = None
    if final_code:
        saved_path = f"{filepath}.improved.py"
        with open(saved_path, "w", encoding="utf-8") as f:
            f.write(final_code.rstrip() + "\n")
        print(f"\n💾 Versione finale salvata in: {saved_path}")

    summary = (
        f"🔧 Improve completato per {filepath}\n\n"
        f"--- DRAFT (llama3) ---\n{draft}\n\n"
        f"--- REVIEW (gemma4) ---\n{review}\n\n"
        f"--- FINALE (llama3) ---\n{final}"
    )
    if saved_path:
        summary += f"\n\n💾 Codice finale salvato in: {saved_path} (non sovrascrive l'originale)"

    return summary


def main():
    print("🔧 Improver Agent — local Python file analyzer\n")

    while True:
        user_input = input("\n🔧 IMPROVE <filepath>: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("👋 Ciao!")
            break

        if not user_input.lower().startswith("improve "):
            print("Usage: IMPROVE <filepath>  e.g. IMPROVE scripts/db_agent.py")
            continue

        filepath = user_input[8:].strip()
        improve_agent(filepath)


if __name__ == "__main__":
    main()
