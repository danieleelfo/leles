"""
lele_telegram_bot.py — Bot Telegram per Lelé, aperto a tutti con rate limit
di 5 domande al giorno per chat_id (Illimitate per l'Admin).

Setup:
    pip install python-telegram-bot

Uso (dalla cartella di Lelé, con lele_api.py già attivo su :8001):
    python3 lele_telegram_bot.py
"""

import requests
import logging
from datetime import date
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# --- Config ---
TELEGRAM_TOKEN = "8864071391:AAGnLTkkElhzHsBHvc7LhwuPuNmxOl6yyZ0"  # nuovo bot da BF
LELE_API_URL = "http://localhost:8080/ask"

MAX_QUESTIONS_PER_DAY = 5
ADMIN_IDS = [8733881519]  # Il tuo Chat ID con superpoteri

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Rate limit in-memory: {chat_id: {"date": date, "count": int}} ---
_usage = {}


def check_and_increment(chat_id: int) -> tuple[bool, int]:
    """Ritorna (consentito, domande_rimaste)"""
    # Se sei tu, salta completamente il blocco del rate limit
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

    # Log di debug per vedere chi scrive in background
    logger.info(f"Messaggio da ID {chat_id} ({update.effective_user.username}): '{message}'")

    allowed, remaining = check_and_increment(chat_id)

    if not allowed:
        await update.message.reply_text(
            f"⏳ Hai raggiunto il limite di {MAX_QUESTIONS_PER_DAY} domande oggi. "
            "Torna a trovarmi domani, nostromo!"
        )
        return

    thinking_msg = await update.message.reply_text("🏴‍☠️ Lelé sta pensando...")

    try:
        response = requests.post(LELE_API_URL, json={"message": message}, timeout=180)
        response.raise_for_status()
        data = response.json()

        answer = data.get("answer", "🦜 ...")

        if len(answer) > 4000:
            answer = answer[:4000] + "\n\n... (troncato)"

        # Personalizzazione del footer in base all'utente
        if chat_id in ADMIN_IDS:
            footer = "\n\n_🏴‍☠️ Accesso Admin: Domande illimitate_"
        else:
            footer = f"\n\n_({remaining} domande rimaste oggi)_" if remaining > 0 else "\n\n_(ultima domanda di oggi)_"

        await thinking_msg.edit_text(answer + footer, parse_mode="Markdown")

    except requests.exceptions.Timeout:
        await thinking_msg.edit_text("⏱️ Lelé ci sta pensando troppo su... riprova.")
    except requests.exceptions.ConnectionError:
        await thinking_msg.edit_text("❌ Lelé non è raggiungibile. È attivo lele_api.py su :8001?")
    except Exception as e:
        logger.error(f"Errore: {e}")
        await thinking_msg.edit_text(f"❌ Errore: {e}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🏴‍☠️ Bot Lelé avviato — in ascolto...")
    app.run_polling()


if __name__ == "__main__":
    main()
