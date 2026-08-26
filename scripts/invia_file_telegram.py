"""
invia_file_telegram.py - Invia qualsiasi file come allegato su Telegram.
Uso da CLI: python invia_file_telegram.py <percorso_file>
Uso come libreria: from scripts.invia_file_telegram import invia_file_telegram
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv("/Users/danny/Desktop/Danny/leles/.env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8733881519")

def invia_file_telegram(file_path: str, chat_id: str = None) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN non impostato")
        return False

    target_chat_id = chat_id or TELEGRAM_CHAT_ID

    if not os.path.exists(file_path):
        print(f"File non trovato: {file_path}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"

    try:
        with open(file_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': target_chat_id}
            response = requests.post(url, files=files, data=data, timeout=30)

            if response.status_code != 200:
                print(f"Telegram API error {response.status_code}: {response.text[:200]}")
                return False

            print(f"File inviato: {file_path}")
            return True

    except Exception as e:
        print(f"Errore invio file: {e}")
        return False

if len(sys.argv) > 1 and os.path.basename(sys.argv[0]) == "invia_file_telegram.py":
    ok = invia_file_telegram(sys.argv[1])
    sys.exit(0 if ok else 1)