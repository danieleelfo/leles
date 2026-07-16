"""
leles_bot.py — Bot Telegram per Lelé ES, aperto a tutti con rate limit
di 50 domande al giorno per chat_id (Illimitate per l'Admin).
Versione Ottimizzata (Async & Thread-Safe) ES
"""

import os
import sys
import subprocess
import httpx
import logging
import asyncio
from datetime import date
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from voice_transcriber import transcribe_audio
from tts_engine import synthesize_to_ogg
from tts_engine import synthesize_multilang_to_ogg

from langdetect import detect, LangDetectException

# --- Config (Caricata da ambiente o fallback su porta 8080) ---
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LELE_API_URL = os.getenv("LELE_API_URL", "http://localhost:8082/ask")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN non impostato — controlla il file .env")

MAX_QUESTIONS_PER_DAY = 500
ADMIN_IDS = [8733881519]  # Il tuo Chat ID con superpoteri
MAX_VOICE_DURATION = 5 * 60  # 5 minuti (solo utenti normali)

# Root del progetto (cartella che contiene scripts/), usata da "pull"/"restart"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_PORT = os.getenv("LELE_API_PORT", "8082")

# Cartella temporanea per i vocali in arrivo (cancellati subito dopo la trascrizione)
VOICE_TMP_DIR = os.getenv("VOICE_TMP_DIR", "tmp_voice_in")
os.makedirs(VOICE_TMP_DIR, exist_ok=True)

# Aiutino per Whisper: orienta la trascrizione verso i comandi noti di Lelé
VOICE_INITIAL_PROMPT = "query, review, improve, edita, roast, critica"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Rate limit in-memory protetto da Lock ---
_usage = {}
_usage_lock = asyncio.Lock()


async def check_and_increment(chat_id: int) -> tuple[bool, int]:
    """Ritorna (consentito, domande_rimaste) - Thread Safe"""
    async with _usage_lock:
        if chat_id in ADMIN_IDS:
            return True, 999

        today = date.today()
        entry = _usage.get(chat_id)

        if entry is None or entry["date"] != today:
            _usage[chat_id] = {"date": today, "count": 1}
            return True, MAX_QUESTIONS_PER_DAY - 1

        if entry["count"] >= MAX_QUESTIONS_PER_DAY:
            return False, 0

        entry["count"] += 1
        return True, MAX_QUESTIONS_PER_DAY - entry["count"]
        
async def ask_lele(message: str, chat_id: int) -> str:
    """
    Invia una richiesta al motore Lelé e restituisce la risposta.
    """
    async with httpx.AsyncClient(timeout=620) as client:
        response = await client.post(
            LELE_API_URL,
            json={"message": message, "chat_id": chat_id},
        )
        response.raise_for_status()

        data = response.json()
        return data.get("answer", "🦜 ...")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    welcome_text = "🏴‍☠️ *Lelé Engine* è online! Spara!\n\n"
    
    if chat_id in ADMIN_IDS:
        welcome_text += "⚓ *Bentornato Capitano!* Per te l'accesso è totale e illimitato, mio padrone.\n\n"
    else:
        welcome_text += f"Hai diritto a {MAX_QUESTIONS_PER_DAY} domande al giorno.\n\n"

    welcome_text += (
        "Comandi speciali:\n"
        "`query <domanda>` → interroga il database\n"
        "`review <testo>` → revisione llama3\n"
        "Altrimenti parla normalmente con Lelé."
    )
    
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def handle_pull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    'pull report leles' — fa git pull sul repo e manda l'output com'è.
    Solo admin. Uvicorn gira con --reload, quindi l'API si aggiorna da
    sola non appena i file cambiano — non serve riavviarla per questo.
    """
    await update.message.reply_text("📥 Pull in corso...")

    result = subprocess.run(
        ["git", "pull"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = (result.stdout + result.stderr).strip() or "(nessun output)"
    if len(output) > 3500:
        output = output[:3500] + "\n... (troncato)"

    prefix = "✅" if result.returncode == 0 else "❌"
    await update.message.reply_text(f"{prefix} Pull terminato:\n\n{output}")


async def handle_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    'restart Lelé' — riavvia sia uvicorn (kill + rilancio detached) sia
    questo stesso processo bot (self-exec). Solo admin.
    """
    await update.message.reply_text("🔄 Riavvio Lelé in corso, torno subito...")

    # 1. Uccidi l'istanza uvicorn attuale (best-effort, ignora se non gira)
    subprocess.run(["pkill", "-f", "uvicorn scripts.lele_api"], check=False)
    await asyncio.sleep(1)

    # 2. Rilancia uvicorn come processo indipendente (sopravvive al riavvio del bot)
    log_path = os.path.join(PROJECT_ROOT, "uvicorn_restart.log")
    with open(log_path, "a") as logfile:
        subprocess.Popen(
            ["uvicorn", "scripts.lele_api:app", "--reload", "--port", API_PORT],
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

    message = update.message.text

    if chat_id in ADMIN_IDS:
        if message.lower().startswith("pull report"):
            await handle_pull(update, context)
            return
        if message.lower().startswith("restart"):
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

    allowed, remaining = await check_and_increment(chat_id)

    if not allowed:
        await update.message.reply_text(
            f"⏳ Hai raggiunto il limite di {MAX_QUESTIONS_PER_DAY} domande oggi. "
            "Torna a trovarmi domani, nostromo!"
        )
        return

    thinking_msg = await update.message.reply_text("🏴‍☠️ Lelé sta pensando... Aspé... 🌊 🏴‍☠️ ")

    try:
        answer = await ask_lele(message, chat_id)
        if len(answer) > 4000:
            answer = answer[:4000] + "\n\n... (troncato)"

        if chat_id in ADMIN_IDS:
            footer = "\n\n🏴‍☠️ Accesso Admin: Domande illimitate"
        else:
            footer = f"\n\n({remaining} domande rimaste oggi)" if remaining > 0 else "\n\n(ultima domanda di oggi)"

        if "|" in answer or "---" in answer:
            from html import escape
            safe_answer = escape(answer)
            full_message = f"<pre>{safe_answer}</pre>{footer}"
            parse_mode_to_use = "HTML"
        else:
            full_message = answer + footer
            parse_mode_to_use = None

        try:
            await thinking_msg.delete()
        except Exception:
            pass

        await update.message.reply_text(full_message, parse_mode=parse_mode_to_use)
        
        if send_voice:
            ogg_out_path = None
            try:
                ogg_out_path, lang_label = await loop.run_in_executor(
                    None,
                    lambda: synthesize_multilang_to_ogg(answer)
                )

                with open(ogg_out_path, "rb") as voice_out:
                    await update.message.reply_voice(voice=voice_out, caption=f"🌍 {lang_label}")

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
    loop = asyncio.get_running_loop()

    allowed, remaining = await check_and_increment(chat_id)

    if not allowed:
        await update.message.reply_text(
            f"⏳ Hai raggiunto il limite di {MAX_QUESTIONS_PER_DAY} domande oggi. "
            "Torna a trovarmi domani, nostromo!"
        )
        return

    thinking_msg = await update.message.reply_text("🎙️ Lelé sta ascoltando... Con calma... 🏴‍☠️ 🌊")

    voice = update.message.voice

    # Limite durata solo per utenti normali
    if chat_id not in ADMIN_IDS and voice.duration > MAX_VOICE_DURATION:
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

    # --- STEP 2: instrada il testo trascritto nella stessa pipeline /ask del testo ---
    try:
        answer = await ask_lele(transcribed_text, chat_id)
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
            await update.message.reply_voice(voice=voice_out, caption=f"🌍 {lang_label}")
    except Exception as e:
        logger.error(f"TTS fallito per {chat_id}, rispondo solo in testo: {e}")
        await update.message.reply_text(answer)
    finally:
        if ogg_out_path and os.path.exists(ogg_out_path):
            os.remove(ogg_out_path)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("🏴‍☠️ Bot Lelé ES avviato (Porta API: 8082) — in ascolto delle sirene... 🧜🏻‍♀️ ")
    app.run_polling()


if __name__ == "__main__":
    main()
