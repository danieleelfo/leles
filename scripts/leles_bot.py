"""
leles_bot.py — Bot Telegram per Lelé ES.

Bot personale (solo Danny) — niente rate-limit multi-utente: chi non è
nella whitelist ADMIN_IDS viene semplicemente ignorato con un messaggio
di accesso negato, non c'è un tier "utente normale" da gestire.
"""

import os
import sys
import subprocess
import httpx
import logging
import asyncio
import re
from telegram import Update
from telegram.error import Conflict
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from voice_transcriber import transcribe_audio
from tts_engine import synthesize_to_ogg
from tts_engine import synthesize_multilang_to_ogg

from langdetect import detect, LangDetectException

from timoniere import is_restart_leles_trigger
from datetime import datetime

# --- Config (Caricata da ambiente o fallback su porta 8080) ---
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LELE_API_URL = os.getenv("LELE_API_URL", "http://localhost:8082/ask")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN non impostato — controlla il file .env")

ADMIN_IDS = [8733881519, 8249666123]  # Il tuo Chat ID — unico utente autorizzato
MAX_VOICE_DURATION = 5 * 60  # 5 minuti

# Root del progetto (cartella che contiene scripts/), usata da "pull"/"restart"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_PORT = os.getenv("LELE_API_PORT", "8082")

# Cartella temporanea per i vocali in arrivo (cancellati subito dopo la trascrizione)
VOICE_TMP_DIR = os.getenv("VOICE_TMP_DIR", "tmp_voice_in")
os.makedirs(VOICE_TMP_DIR, exist_ok=True)

DETTATURA_DIR = os.path.join(PROJECT_ROOT, "Dettatura")

os.makedirs(DETTATURA_DIR, exist_ok=True)

# Aiutino per Whisper: orienta la trascrizione verso i comandi noti di Lelé
VOICE_INITIAL_PROMPT = "query, review, improve, edita, roast, critica"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def is_authorized(chat_id: int) -> bool:
    return chat_id in ADMIN_IDS


AGENT_LABELS = {
    "gemma": "🐐 Gemma 🧜🏻‍♀️",
    "llama_review": "⚓ Lelé reviewer ",
    "query": "🗄️ Query Agent",
    "export": "📤 Export",
    "improve": "🔧 Improve",
    "verify": "✅ Verify",
    "git_pull": "📥 Git Agent",
    "git_status": "🔍 Git Agent",
    "start_process": "🟢 Process Agent",
    "stop_process": "🛑 Process Agent",
    "restart_process": "🔄 Process Agent",
    "uvicorn_status": "🔍 Process Agent",
    "telegram_status": "🔍 Process Agent",
    "system_status": "🖥️ Health Agent",
    "airflow_trigger": "🌀 Airflow Agent",
    "airflow_trigger_disabled": "🌀 Airflow Agent ❌",
    "synthesize": "📄 Synthesizer Agent",
    "synthesize_disabled": "📄 Synthesizer Agent ❌",
    "empty": "⚓ Lelé 🏴‍☠️",
    "improve_disabled": "🔧 Improve",
    "verify_disabled": "❌ Verify",
    "query_disabled": "🗄️ Query Agent ❌",
    "export_disabled": "📤 Export ❌",
    "git_pull_disabled": "📥 Git Agent ❌",
    "git_status_disabled": "🔍 Git Agent ❌",
    "start_process_disabled": "🟢 Process Agent ❌",
    "stop_process_disabled": "🛑 Process Agent ❌",
    "restart_process_disabled": "🔄 Process Agent ❌",
    "restart_unavailable": "🔄 Process Agent ⚠️",
}


async def ask_lele(message: str, chat_id: int) -> tuple[str, str]:
    """
    Invia una richiesta al motore Lelé e restituisce (risposta, tipo_agente).
    """
    async with httpx.AsyncClient(timeout=620) as client:
        payload = {
            "message": message,
            "chat_id": chat_id,
        }

        print("BOT INVIA:", payload)

        response = await client.post(
            LELE_API_URL,
            json=payload,
        )
        response.raise_for_status()

        data = response.json()
        return data.get("answer", "🦜 ..."), data.get("type", "gemma")


TELEGRAM_MAX_CHARS = 4000  # margine di sicurezza sotto il limite reale (4096)


def split_message(text: str, max_len: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """
    Spezza un testo lungo in più blocchi <= max_len, tagliando su un
    a-capo quando possibile per non spaccare righe/entry YAML a metà.
    Se un singolo "paragrafo" supera comunque max_len, lo taglia secco.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_len:
        cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len  # nessun a-capo utile, taglio secco
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    if remaining:
        chunks.append(remaining)

    return chunks

def formatta_poesia(testo: str) -> str:
    """
    Formatta una poesia dettata a voce senza modificarne le parole.
    Inserisce una riga vuota dopo ogni verso riconosciuto.
    """
    # pulizia spazi
    testo = re.sub(r"\s+", " ", testo).strip()
    # separa sui principali segni di punteggiatura
    versi = re.split(r"(?<=[\.,;:!?])\s+", testo)
    versi = [v.strip().capitalize() for v in versi if v.strip()]
    return "\n\n".join(versi)

async def send_long_message(update: Update, text: str, parse_mode=None):
    """
    Manda `text` come uno o più messaggi Telegram, spezzandolo se supera
    il limite di caratteri, invece di troncarlo silenziosamente.
    """
    chunks = split_message(text)
    total = len(chunks)

    for i, chunk in enumerate(chunks, start=1):
        prefix = f"[{i}/{total}]\n" if total > 1 else ""
        await update.message.reply_text(prefix + chunk, parse_mode=parse_mode)
        if i < total:
            await asyncio.sleep(0.3)  # non intasare l'API Telegram


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ Accesso non autorizzato.")
        return

    welcome_text = (
        "🏴‍☠️ *Lelé Engine* è online! Spara!\n\n"
        "⚓ *Bentornato Capitano!*\n\n"
        "Comandi admin:\n"
        "`pull report <leles|bar_ai|lele|story_whisper>` → git pull\n"
        "`status <leles|bar_ai|lele|story_whisper>` → git status + ultimo commit\n"
        "`uvicorn status` → controlla se tutte le API sono vive\n"
        "`telegram status` → controlla se tutti i bot sono vivi\n"
        "`status sistema` → dashboard completa (API+bot+Ollama+Postgres)\n"
        "`status ip` → indirizzo IP pubblico attuale (rete di casa, dinamico)\n"
        "`status os` → CPU/RAM/disco/uptime del Mac\n"
        "`status ram` → breakdown RAM + modelli Ollama caricati\n"
        "`status tts <progetto>` → voci Piper installate per quel progetto\n"
        "`directory <progetto> [sottocartella]` → elenca file/cartelle (es. 'directory ns voices')\n"
        "`tts copy <sorgente> <destinazione>` → copia le voci Piper tra due progetti (es. 'tts copy sw ns')\n"
        "`tts install <progetto> <nome_modello>` → scarica una voce Piper (solo tra quelle configurate nel progetto)\n"
        "`directory dag [sottocartella]` → elenca i file nella cartella Airflow reale (non è in git)\n"
        "`export dag <nome_file.py>` → cerca e mostra il contenuto di un DAG (ricorsivo, tutta la cartella Airflow)\n"
        "`status dag [dag_id]` → ultime esecuzioni di un DAG, o elenco di tutti i DAG se omesso\n"
        "`logs <progetto>` → ultime righe dei log (es. 'logs ns'), utile se un processo parte e crasha subito\n"
        "`restart Lelé` → riavvia bot + API Leles (solo per questo bot)\n"
        "`start|stop|restart <bar_ai|lele|story_whisper>` → controlla i progetti esterni\n\n"
        "Nota: 'lele' da solo indica sempre il progetto Lelé (pirata), "
        "per riferirti a questo bot usa 'leles' per esteso.\n\n"
        "Comandi speciali:\n"
        "`query <domanda>` → interroga il database\n"
        "`review <testo>` → revisione llama3\n"
        "Altrimenti parla normalmente con Lelé."
    )

    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def handle_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    'restart Lelé' — riavvia sia uvicorn (kill + rilancio detached) sia
    questo stesso processo bot (self-exec). Solo admin.

    Process Agent: a differenza di git pull/status (delegati al Timoniere
    lato API in git_agent.py), il restart DEVE girare qui — è l'unico
    processo che può riavviare se stesso via os.execv.
    """
    await update.message.reply_text("🔄 Riavvio Lelé in corso, torno subito...")

    # 1. Uccidi l'istanza uvicorn attuale (best-effort, ignora se non gira)
    subprocess.run(["pkill", "-f", "uvicorn scripts.lele_api"], check=False)
    await asyncio.sleep(1)

    # 2. Rilancia uvicorn come processo indipendente (sopravvive al riavvio del bot)
    #
    # IMPORTANTE: usiamo il path assoluto dell'uvicorn dentro il venv di
    # Leles (PROJECT_ROOT/.venv/bin/uvicorn), NON solo "uvicorn". Se
    # chiamato per nome, subprocess.Popen risolve il binario cercando nel
    # PATH ereditato dal processo che ha lanciato/rilanciato questo bot
    # (es. via os.execv più sotto) — se quel processo era stato avviato
    # da un terminale con un venv DIVERSO attivo (es. il venv di un altro
    # progetto), si finisce per lanciare l'uvicorn sbagliato, con le
    # dipendenze sbagliate (bug reale riscontrato: ModuleNotFoundError su
    # psycopg2 perché aveva preso l'uvicorn del venv di Airflow).
    log_path = os.path.join(PROJECT_ROOT, "uvicorn_restart.log")
    uvicorn_bin = os.path.join(PROJECT_ROOT, ".venv", "bin", "uvicorn")
    with open(log_path, "a") as logfile:
        subprocess.Popen(
            [uvicorn_bin, "scripts.lele_api:app", "--reload", "--port", API_PORT],
            cwd=PROJECT_ROOT,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # non muore quando il bot fa execv sotto
        )

    # 3. Riavvia questo stesso processo bot (execv sostituisce il processo
    #    corrente rileggendo lo script da disco — quindi prende il codice
    #    appena pullato, non serve altro)
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ Accesso non autorizzato.")
        return

    message = update.message.text

    if is_restart_leles_trigger(message):
        await handle_restart(update, context)
        return

    loop = asyncio.get_running_loop()

    send_voice = False

    VOICE_PREFIXES = (
        "audio&text",
        "audio&txt",
        "aud&text",
        "audio&testo",
    )

    for prefix in VOICE_PREFIXES:
        if message.lower().startswith(prefix):
            send_voice = True
            message = message[len(prefix):].strip()
            break

    logger.info(f"Messaggio da ID {chat_id} ({update.effective_user.username}): '{message}'")

    thinking_msg = await update.message.reply_text("🏴‍☠️ Lelé sta pensando... Aspé... 🌊 🏴‍☠️ ")

    try:
        answer, agent_type = await ask_lele(message, chat_id)
        agent_label = AGENT_LABELS.get(agent_type, "🏴‍☠️ Lelé")

        try:
            await thinking_msg.delete()
        except Exception:
            pass

        if "|" in answer or "---" in answer:
            from html import escape
            answer_chunks = split_message(answer, max_len=TELEGRAM_MAX_CHARS - 20)
            total = len(answer_chunks)
            for i, chunk in enumerate(answer_chunks, start=1):
                label = f"<b>{escape(agent_label)}</b> [{i}/{total}]\n" if total > 1 else f"<b>{escape(agent_label)}</b>\n"
                full_message = f"{label}<pre>{escape(chunk)}</pre>"
                await update.message.reply_text(full_message, parse_mode="HTML")
                if i < total:
                    await asyncio.sleep(0.3)
        else:
            await send_long_message(update, f"{agent_label}\n\n{answer}", parse_mode=None)
        
        if send_voice:
            ogg_out_path = None
            try:
                ogg_out_path, lang_label = await loop.run_in_executor(
                    None,
                    lambda: synthesize_multilang_to_ogg(answer)
                )

                with open(ogg_out_path, "rb") as voice_out:
                    await update.message.reply_voice(voice=voice_out, caption=f"{agent_label} · 🌍 {lang_label}")

            finally:
                if ogg_out_path and os.path.exists(ogg_out_path):
                    os.remove(ogg_out_path)

    except httpx.TimeoutException:
        await thinking_msg.edit_text("⏱️ Lelé ci sta pensando troppo su... riprova.")
    except httpx.ConnectError:
        await thinking_msg.edit_text("❌ Lelé non è raggiungibile. Controlla che Uvicorn sia attivo sulla porta 8082.")
    except Exception as e:
        logger.error(f"Errore critico durante l'API call per {chat_id}: {e}", exc_info=True)
        await thinking_msg.edit_text("❌ Si è verificato un errore inaspettato nel sistema di Lelé.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Vocale in entrata → trascrizione (faster-whisper) → pipeline /ask →
    risposta in vocale (Piper TTS). Se il TTS fallisce, risponde in testo.
    """
    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        await update.message.reply_text("⛔ Accesso non autorizzato.")
        return

    loop = asyncio.get_running_loop()

    thinking_msg = await update.message.reply_text("🎙️ Lelé sta ascoltando... Con calma... 🏴‍☠️ 🌊")

    voice = update.message.voice

    if voice.duration > MAX_VOICE_DURATION:
        minutes = voice.duration // 60
        seconds = voice.duration % 60

        await thinking_msg.edit_text(
            f"🎙️ Il tuo vocale dura {minutes}m {seconds:02d}s.\n\n"
            "Al momento posso trascrivere vocali fino a 5 minuti, AAAARRH.\n"
            "Dividilo in più parti, logorroico. 🏴‍☠️"
        )
        return

    # --- STEP 1: scarica e trascrivi il vocale ---
    ogg_in_path = None
    try:
        voice_file = await update.message.voice.get_file()
        ogg_in_path = os.path.join(VOICE_TMP_DIR, f"{voice_file.file_unique_id}.ogg")
        await voice_file.download_to_drive(ogg_in_path)

        # faster-whisper è bloccante: giralo in executor per non congelare l'event loop
        transcribed_text = await loop.run_in_executor(
            None,
            lambda: transcribe_audio(
                ogg_in_path, language=None, initial_prompt=VOICE_INITIAL_PROMPT
            ),
        )

        if not transcribed_text:
            await thinking_msg.edit_text("🦜 Non ho capito nulla, prova a rimandare il vocale più chiaro.")
            return

        logger.info(f"Vocale trascritto da ID {chat_id}: '{transcribed_text}'")
        await thinking_msg.edit_text(f"📝 Hai detto: _{transcribed_text}_", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Errore trascrizione vocale per {chat_id}: {e}", exc_info=True)
        await thinking_msg.edit_text("❌ Non sono riuscito a capire il vocale, riprova.")
        return
    finally:
        if ogg_in_path and os.path.exists(ogg_in_path):
            os.remove(ogg_in_path)

    # --- Modalità "Dettatura": salva la trascrizione su disco.
    if transcribed_text.lower().startswith("dettatura"):
        testo = transcribed_text[len("dettatura"):].strip(" ,.-")
        # Formato:
        # Dettatura storia, C'era una volta...
        if "," in testo:
            nome_file, contenuto = testo.split(",", 1)
            nome_file = nome_file.strip()
            contenuto = contenuto.strip()
        else:
            nome_file = "dettatura"
            contenuto = testo
        # pulizia nome file
        nome_file = "".join(
            c if c.isalnum() else "_"
            for c in nome_file.lower()
        )

        while "__" in nome_file:
            nome_file = nome_file.replace("__", "_")
        nome_file = nome_file.strip("_")
        # Formattazione speciale per le poesie
        if nome_file == "poesia":
            contenuto = formatta_poesia(contenuto)
        filename = (
            datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            + f"_{nome_file}.txt"
        )

        txt_path = os.path.join(DETTATURA_DIR, filename)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(contenuto)
        with open(txt_path, "rb") as doc:
            await update.message.reply_document(
                document=doc,
                filename=filename,
                caption=f"📝 Dettatura salvata\n📂 {filename}"
            )
        return
    # --- STEP 2: instrada il testo trascritto nella stessa pipeline /ask del testo ---
    try:
        answer, agent_type = await ask_lele(transcribed_text, chat_id)
        agent_label = AGENT_LABELS.get(agent_type, "🏴‍☠️ Lelé")
    except httpx.TimeoutException:
        await update.message.reply_text("⏱️ Lelé ci sta pensando troppo su... riprova.")
        return
    except httpx.ConnectError:
        await update.message.reply_text("❌ Lelé ES non è raggiungibile. Controlla che Uvicorn sia attivo sulla porta 8082.")
        return
    except Exception as e:
        logger.error(f"Errore critico durante l'API call (voce) per {chat_id}: {e}", exc_info=True)
        await update.message.reply_text("❌ Si è verificato un errore inaspettato nel sistema di Lelé ES.")
        return

    # --- STEP 3: rispondi con un vocale (fallback a testo se il TTS fallisce) ---
    ogg_out_path = None
    try:
        ogg_out_path, lang_label = await loop.run_in_executor(
            None,
            lambda: synthesize_multilang_to_ogg(answer)
        )
        with open(ogg_out_path, "rb") as voice_out:
            await update.message.reply_voice(voice=voice_out, caption=f"{agent_label} · 🌍 {lang_label}")
    except Exception as e:
        logger.error(f"TTS fallito per {chat_id}, rispondo solo in testo: {e}")
        await send_long_message(update, f"{agent_label}\n\n{answer}")
    finally:
        if ogg_out_path and os.path.exists(ogg_out_path):
            os.remove(ogg_out_path)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("🏴‍☠️ Bot Lelé ES avviato (Porta API: 8082) — in ascolto delle sirene... 🧜🏻‍♀️ ")

    # drop_pending_updates=True: alla partenza, scarta qualsiasi update
    # residuo lato Telegram invece di riprocessarlo — utile soprattutto
    # dopo un kill non pulito della sessione precedente.
    #
    # Il retry qui sotto è una rete di sicurezza: se capita comunque un
    # 409 Conflict transitorio (es. sessione precedente non ancora
    # scaduta lato Telegram), il bot aspetta e riprova invece di
    # spammare traceback all'infinito nei log.
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            app.run_polling(drop_pending_updates=True)
            break  # uscita pulita (es. Ctrl+C) — non riprovare
        except Conflict:
            if attempt == max_retries:
                logger.error(
                    f"🏴‍☠️ Conflict persistente dopo {max_retries} tentativi — "
                    "probabile un'altra istanza attiva altrove. Mi fermo."
                )
                raise
            wait_s = 10 * attempt
            logger.warning(
                f"⚠️ Conflict (tentativo {attempt}/{max_retries}), "
                f"riprovo tra {wait_s}s..."
            )
            import time
            time.sleep(wait_s)


if __name__ == "__main__":
    main()
