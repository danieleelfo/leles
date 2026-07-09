"""
lele_telegram_bot.py — Bot Telegram per Lelé, aperto a tutti con rate limit
di 5 domande al giorno per chat_id (Illimitate per l'Admin).
Versione Ottimizzata (Async & Thread-Safe)
"""

import os
import requests
import logging
import asyncio
from datetime import date
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from voice_transcriber import transcribe_audio
from tts_engine import synthesize_to_ogg

# --- Config (Caricata da ambiente o fallback su porta 8080) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8864071391:AAGnLTkkElhzHsBHvc7LhwuPuNmxOl6yyZ0")
LELE_API_URL = os.getenv("LELE_API_URL", "http://localhost:8080/ask")

MAX_QUESTIONS_PER_DAY = 50
ADMIN_IDS = [8733881519]  # Il tuo Chat ID con superpoteri

# Cartella temporanea per i vocali in arrivo (cancellati subito dopo la trascrizione)
VOICE_TMP_DIR = os.getenv("VOICE_TMP_DIR", "tmp_voice_in")
os.makedirs(VOICE_TMP_DIR, exist_ok=True)

# Aiutino per Whisper: orienta la trascrizione verso i comandi noti di Lelé
# (query capitava fosse capito come "queri" — questo + il fuzzy match in
# lele_engine9.is_query_trigger dovrebbero coprirlo da entrambi i lati)
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message = update.message.text

    logger.info(f"Messaggio da ID {chat_id} ({update.effective_user.username}): '{message}'")

    # FIX 1: Await del rate limit (ora asincrono per via del Lock)
    allowed, remaining = await check_and_increment(chat_id)

    # FIX 2: Early exit immediato se ha superato il limite
    if not allowed:
        await update.message.reply_text(
            f"⏳ Hai raggiunto il limite di {MAX_QUESTIONS_PER_DAY} domande oggi. "
            "Torna a trovarmi domani, nostromo!"
        )
        return

    thinking_msg = await update.message.reply_text("🏴‍☠️ Lelé sta pensando...")

    try:
        # FIX 3: Esecuzione asincrona della richiesta HTTP bloccante
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(LELE_API_URL, json={"message": message}, timeout=180)
        )
        response.raise_for_status()
        data = response.json()

        answer = data.get("answer", "🦜 ...")

        if len(answer) > 4000:
            answer = answer[:4000] + "\n\n... (troncato)"

        if chat_id in ADMIN_IDS:
            footer = "\n\n🏴‍☠️ Accesso Admin: Domande illimitate"
        else:
            footer = f"\n\n({remaining} domande rimaste oggi)" if remaining > 0 else "\n\n(ultima domanda di oggi)"

        # --- FIX DEFINITIVO PER CARATTERI SQL ---
        # Se la risposta contiene i pipe della tabella del DB, la formattiamo
        # in un blocco di codice pulito per Telegram, altrimenti la mandiamo normale.
        if "|" in answer or "---" in answer:
            # Proteggiamo i caratteri speciali che fanno impazzire il parser di Telegram
            # Usiamo l'HTML che è più rigido e sicuro rispetto al testo libero
            from html import escape
            safe_answer = escape(answer)
            full_message = f"<pre>{safe_answer}</pre>{footer}"
            parse_mode_to_use = "HTML"
        else:
            full_message = answer + footer
            parse_mode_to_use = None

        # Eliminiamo il messaggio di attesa e ne mandiamo uno fresco per evitare l'ereditarietà dei bug
        try:
            await thinking_msg.delete()
        except Exception:
            pass

        await update.message.reply_text(full_message, parse_mode=parse_mode_to_use)

    except requests.exceptions.Timeout:
        await thinking_msg.edit_text("⏱️ Lelé ci sta pensando troppo su... riprova.")
    except requests.exceptions.ConnectionError:
        await thinking_msg.edit_text("❌ Lelé non è raggiungibile. Controlla che Uvicorn sia attivo sulla porta 8080.")
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

    thinking_msg = await update.message.reply_text("🎙️ Lelé sta ascoltando...")

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
                ogg_in_path, language="it", initial_prompt=VOICE_INITIAL_PROMPT
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
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(LELE_API_URL, json={"message": transcribed_text}, timeout=180)
        )
        response.raise_for_status()
        data = response.json()
        answer = data.get("answer", "🦜 ...")

    except requests.exceptions.Timeout:
        await update.message.reply_text("⏱️ Lelé ci sta pensando troppo su... riprova.")
        return
    except requests.exceptions.ConnectionError:
        await update.message.reply_text("❌ Lelé non è raggiungibile. Controlla che Uvicorn sia attivo sulla porta 8080.")
        return
    except Exception as e:
        logger.error(f"Errore critico durante l'API call (voce) per {chat_id}: {e}", exc_info=True)
        await update.message.reply_text("❌ Si è verificato un errore inaspettato nel sistema di Lelé.")
        return

    # --- STEP 3: input era vocale → rispondi con un vocale (fallback a testo se il TTS fallisce) ---
    ogg_out_path = None
    try:
        ogg_out_path = await loop.run_in_executor(None, lambda: synthesize_to_ogg(answer))
        with open(ogg_out_path, "rb") as voice_out:
            await update.message.reply_voice(voice=voice_out)
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

    logger.info("🏴‍☠️ Bot Lelé avviato (Porta API: 8080) — in ascolto...")
    app.run_polling()


if __name__ == "__main__":
    main()
