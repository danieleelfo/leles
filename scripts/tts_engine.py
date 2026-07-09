"""
tts_engine.py — Sintesi vocale locale per Lelé, basata su Piper TTS.

Perché Piper: gira su CPU (bene su Apple Silicon), è offline al 100%,
pesa poco in RAM e produce una voce neurale decente — in linea con
la filosofia local-first del progetto. Nota: dal 2025 il progetto
attivo è OHF-Voice/piper1-gpl, licenza GPL-3.0 (il vecchio repo MIT
rhasspy/piper è archiviato).

Setup (una tantum, sul Mac):
    source .venv/bin/activate
    pip install piper-tts
    python3 -m piper.download_voices --download-dir voices it_IT-riccardo-x_low

    # serve ffmpeg per convertire il wav in ogg/opus (formato voice-note Telegram)
    brew install ffmpeg

Voce di default: it_IT-riccardo-x_low (maschile, leggera, si carica in fretta).
Alternativa più naturale ma più pesante: it_IT-paola-medium (femminile).
Cambiala con la env var TTS_VOICE_MODEL.
"""

import os
import re
import wave
import uuid
import logging
import subprocess

from piper import PiperVoice

logger = logging.getLogger(__name__)

# --- Config ---------------------------------------------------------------

VOICE_MODEL_DIR = os.getenv("TTS_VOICE_MODEL_DIR", "voices")
VOICE_MODEL_NAME = os.getenv("TTS_VOICE_MODEL", "it_IT-riccardo-x_low")
VOICE_MODEL_PATH = os.path.join(VOICE_MODEL_DIR, f"{VOICE_MODEL_NAME}.onnx")

TTS_TMP_DIR = os.getenv("TTS_TMP_DIR", "tmp_tts")
os.makedirs(TTS_TMP_DIR, exist_ok=True)

# Taglio di sicurezza: risposte lunghissime diventano vocali chilometrici.
# Alza/abbassa a piacere, o metti None per disattivare il taglio.
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))


# --- Singleton: il modello Piper si carica una volta sola in RAM ----------

_voice = None


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        if not os.path.exists(VOICE_MODEL_PATH):
            raise FileNotFoundError(
                f"Modello Piper non trovato: {VOICE_MODEL_PATH}\n"
                f"Scaricalo con: python3 -m piper.download_voices "
                f"--download-dir {VOICE_MODEL_DIR} {VOICE_MODEL_NAME}"
            )
        logger.info(f"🔊 Carico modello Piper: {VOICE_MODEL_PATH}")
        _voice = PiperVoice.load(VOICE_MODEL_PATH)
    return _voice


def _strip_for_speech(text: str) -> str:
    """Toglie markdown ed emoji che Piper leggerebbe male o ignorerebbe male."""
    text = re.sub(r"[*_`#>]", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if TTS_MAX_CHARS and len(text) > TTS_MAX_CHARS:
        # taglia all'ultimo punto pieno prima del limite, se possibile
        cut = text[:TTS_MAX_CHARS]
        last_dot = cut.rfind(". ")
        text = cut[: last_dot + 1] if last_dot > 0 else cut

    return text


def synthesize_to_ogg(text: str) -> str:
    """
    Sintetizza `text` e ritorna il path di un file .ogg/opus pronto per
    Telegram reply_voice(). Il chiamante è responsabile di cancellarlo
    dopo l'invio (vedi esempio in handle_voice).
    """
    voice = _get_voice()
    clean_text = _strip_for_speech(text)

    if not clean_text:
        raise ValueError("Testo vuoto dopo la pulizia: niente da sintetizzare.")

    file_id = uuid.uuid4().hex
    wav_path = os.path.join(TTS_TMP_DIR, f"{file_id}.wav")
    ogg_path = os.path.join(TTS_TMP_DIR, f"{file_id}.ogg")

    try:
        with wave.open(wav_path, "wb") as wav_file:
            voice.synthesize_wav(clean_text, wav_file)

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "32k", ogg_path],
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0 or not os.path.exists(ogg_path):
            raise RuntimeError(
                f"ffmpeg conversion failed: {result.stderr.decode(errors='ignore')}"
            )

        return ogg_path

    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
