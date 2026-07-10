"""
tts_engine.py — Sintesi vocale locale per Leles, basata su Piper TTS.

Perché Piper: gira su CPU (bene su Apple Silicon), è offline al 100%,
pesa poco in RAM e produce una voce neurale decente — in linea con
la filosofia local-first del progetto. Nota: dal 2025 il progetto
attivo è OHF-Voice/piper1-gpl, licenza GPL-3.0 (il vecchio repo MIT
rhasspy/piper è archiviato).

Supporto multi-lingua: Leles risponde in italiano, spagnolo o inglese
a seconda dell'input, quindi il TTS carica dinamicamente il modello
Piper giusto per lingua (vedi VOICE_MODELS sotto), invece di un'unica
voce fissa. Ogni modello viene caricato una sola volta e tenuto in
cache (_voices), riusato per le sintesi successive nella stessa lingua.

Setup (una tantum, sul Mac):
    source .venv/bin/activate
    pip install piper-tts
    python3 -m piper.download_voices --download-dir voices it_IT-riccardo-x_low
    python3 -m piper.download_voices --download-dir voices es_ES-davefx-medium

    # serve ffmpeg per convertire il wav in ogg/opus (formato voice-note Telegram)
    brew install ffmpeg

Voci di default: it_IT-riccardo-x_low (italiano) e es_ES-davefx-medium
(spagnolo, castigliano). Override via env var TTS_VOICE_MODEL_IT /
TTS_VOICE_MODEL_ES se vuoi cambiarle senza toccare il codice.
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

VOICE_MODELS = {
    "it": os.getenv("TTS_VOICE_MODEL_IT", "it_IT-riccardo-x_low"),
    "es": os.getenv("TTS_VOICE_MODEL_ES", "es_ES-davefx-medium"),
}

TTS_TMP_DIR = os.getenv("TTS_TMP_DIR", "tmp_tts")
os.makedirs(TTS_TMP_DIR, exist_ok=True)

TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "6000"))


# --- Cache multi-voce: una PiperVoice caricata per lingua, non più singleton --

_voices: dict[str, PiperVoice] = {}


def _get_voice(lang: str = "it") -> PiperVoice:
    global _voices
    model_name = VOICE_MODELS.get(lang, VOICE_MODELS["it"])

    if model_name not in _voices:
        model_path = os.path.join(VOICE_MODEL_DIR, f"{model_name}.onnx")
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Modello Piper non trovato: {model_path}\n"
                f"Scaricalo con: python3 -m piper.download_voices "
                f"--download-dir {VOICE_MODEL_DIR} {model_name}"
            )
        logger.info(f"🔊 Carico modello Piper ({lang}): {model_path}")
        _voices[model_name] = PiperVoice.load(model_path)

    return _voices[model_name]


def _strip_for_speech(text: str) -> str:
    """Toglie markdown ed emoji che Piper leggerebbe male o ignorerebbe male."""
    text = re.sub(r"[*_`#>]", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if TTS_MAX_CHARS and len(text) > TTS_MAX_CHARS:
        cut = text[:TTS_MAX_CHARS]
        last_dot = cut.rfind(". ")
        text = cut[: last_dot + 1] if last_dot > 0 else cut

    return text


def synthesize_to_ogg(text: str, lang: str = "it") -> str:
    """
    Sintetizza `text` nella lingua richiesta e ritorna il path di un file
    .ogg/opus pronto per Telegram reply_voice(). Il chiamante è responsabile
    di cancellarlo dopo l'invio.

    lang: "it" o "es" — determina quale modello Piper viene usato.
          Se la lingua non è mappata, ricade su "it".
    """
    voice = _get_voice(lang)
    clean_text = _strip_for_speech(text)

    if not clean_text:
        raise ValueError("Testo vuoto dopo la pulizia: niente da sintetizzare.")

    file_id = uuid.uuid4().hex
    wav_path = os.path.join(TTS_TMP_DIR, f"{file_id}.wav")
    ogg_path = os.path.join(TTS_TMP_DIR, f"{file_id}.ogg")

    try:

        with wave.open(wav_path, "wb") as wav_file:

            voice.synthesize_wav(clean_text, wav_file)

        with wave.open(wav_path, "rb") as w:

            duration = w.getnframes() / w.getframerate()

        logger.info(f"TTS chars: {len(clean_text)}")
        logger.info(f"WAV duration = {duration:.1f}s")

        result = subprocess.run(

            ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "32k", ogg_path],

            capture_output=True,

            timeout=60,

        )

        if result.returncode != 0 or not os.path.exists(ogg_path):
            raise RuntimeError(
                f"ffmpeg conversion failed: {result.stderr.decode(errors='ignore')}"
            )

        return ogg_path

    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
