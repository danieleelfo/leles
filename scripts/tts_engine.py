"""
tts_engine.py — Sintesi vocale locale per Leles, basata su Piper TTS.

Perché Piper: gira su CPU (bene su Apple Silicon), è offline al 100%,
pesa poco in RAM e produce una voce neurale decente — in linea con
la filosofia local-first del progetto. Nota: dal 2025 il progetto
attivo è OHF-Voice/piper1-gpl, licenza GPL-3.0 (il vecchio repo MIT
rhasspy/piper è archiviato).

Supporto multi-lingua: Leles risponde in italiano, spagnolo, inglese,
francese, olandese, catalano, russo o ucraino a seconda dell'input,
quindi il TTS carica dinamicamente il modello Piper giusto per lingua
(vedi VOICE_MODELS sotto), invece di un'unica voce fissa. Ogni modello
viene caricato una sola volta e tenuto in cache (_voices), riusato per
le sintesi successive nella stessa lingua.

Setup (una tantum, sul Mac):
    source .venv/bin/activate
    pip install piper-tts
    python3 -m piper.download_voices --download-dir voices it_IT-riccardo-x_low
    python3 -m piper.download_voices --download-dir voices es_ES-davefx-medium
    python3 -m piper.download_voices --download-dir voices en_US-lessac-medium
    python3 -m piper.download_voices --download-dir voices fr_FR-tom-medium
    python3 -m piper.download_voices --download-dir voices nl_BE-nathalie-medium
    python3 -m piper.download_voices --download-dir voices ca_ES-upc_ona-medium
    python3 -m piper.download_voices --download-dir voices ru_RU-irina-medium
    python3 -m piper.download_voices --download-dir voices uk_UA-ukrainian_tts-medium

    # serve ffmpeg per convertire il wav in ogg/opus (formato voice-note Telegram)
    brew install ffmpeg

Voci di default sotto in VOICE_MODELS. Override via env var
TTS_VOICE_MODEL_<LINGUA> (es. TTS_VOICE_MODEL_IT) se vuoi cambiarle
senza toccare il codice.
"""

import os
import re
import wave
import uuid
import logging
import subprocess

from piper import PiperVoice

logger = logging.getLogger(__name__)

from langdetect import detect, LangDetectException

MIN_SEGMENT_LEN = 15  # sotto questa lunghezza langdetect non è affidabile
MAX_SEGMENTS = 15      # tetto di sicurezza: troppi segmenti = troppa latenza


# --- Config ---------------------------------------------------------------

VOICE_MODEL_DIR = os.getenv("TTS_VOICE_MODEL_DIR", "voices")

VOICE_MODELS = {
    "it": os.getenv("TTS_VOICE_MODEL_IT", "it_IT-riccardo-x_low"),
    "es": os.getenv("TTS_VOICE_MODEL_ES", "es_ES-davefx-medium"),
    "en": os.getenv("TTS_VOICE_MODEL_EN", "en_US-lessac-medium"),
    "fr": os.getenv("TTS_VOICE_MODEL_FR", "fr_FR-tom-medium"),
    "nl": os.getenv("TTS_VOICE_MODEL_NL", "nl_BE-nathalie-medium"),
    "ca": os.getenv("TTS_VOICE_MODEL_CA", "ca_ES-upc_ona-medium"),
    "ru": os.getenv("TTS_VOICE_MODEL_RU", "ru_RU-irina-medium"),
    "uk": os.getenv("TTS_VOICE_MODEL_UK", "uk_UA-ukrainian_tts-medium"),
}

# Etichette leggibili per la caption del vocale su Telegram — mostrano
# all'utente quale/i lingua/e ha usato Lelé per la sintesi vocale.
LANG_LABELS = {
    "it": "🇮🇹 Italiano",
    "es": "🇪🇸 Español",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "nl": "🇳🇱 Nederlands",
    "ca": "🏴 Català",
    "ru": "🇷🇺 Русский",
    "uk": "🇺🇦 Українська",
}


def _format_lang_label(langs: list[str]) -> str:
    """Costruisce una didascalia leggibile dalle lingue usate, es. '🇮🇹 Italiano + 🇬🇧 English'."""
    return " + ".join(LANG_LABELS.get(l, l.upper()) for l in langs)

TTS_TMP_DIR = os.getenv("TTS_TMP_DIR", "tmp_tts")
os.makedirs(TTS_TMP_DIR, exist_ok=True)

TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "6000"))


# --- Cache multi-voce: una PiperVoice caricata per lingua, non più singleton --

_voices: dict[str, PiperVoice] = {}


def _get_voice(lang: str = "en") -> PiperVoice:
    global _voices
    model_name = VOICE_MODELS.get(lang, VOICE_MODELS["en"])

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


def synthesize_to_ogg(text: str, lang: str = "en") -> str:
    """
    Sintetizza `text` nella lingua richiesta e ritorna il path di un file
    .ogg/opus pronto per Telegram reply_voice(). Il chiamante è responsabile
    di cancellarlo dopo l'invio.

    lang: "it" o "es" — determina quale modello Piper viene usato.
          Se la lingua non è mappata, ricade su "en".
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

def _split_into_lang_segments(text: str) -> list[tuple[str, str]]:
    """
    Divide il testo in blocchi contigui della stessa lingua rilevata.
    Segmenti troppo corti ereditano la lingua del blocco precedente
    invece di essere classificati alla cieca (langdetect è inaffidabile
    su testi brevissimi).
    """
    raw_parts = re.split(r'(?<=[.!?])\s+|\n+', text)
    raw_parts = [p.strip() for p in raw_parts if p.strip()]

    segments: list[tuple[str, str]] = []
    last_lang = "it"

    for part in raw_parts:
        if len(part) >= MIN_SEGMENT_LEN:
            try:
                lang = detect(part)[:2]
            except LangDetectException:
                lang = last_lang
        else:
            lang = last_lang

        if lang not in VOICE_MODELS:
            lang = last_lang if last_lang in VOICE_MODELS else "en"

        if segments and segments[-1][0] == lang:
            prev_lang, prev_text = segments[-1]
            segments[-1] = (prev_lang, f"{prev_text} {part}")
        else:
            segments.append((lang, part))

        last_lang = lang

    # Tetto di sicurezza: se ci sono troppi micro-segmenti (frasi che
    # alternano lingua di continuo), meglio collassare tutto sulla
    # lingua dominante piuttosto che fare 30 sintesi separate.
    if len(segments) > MAX_SEGMENTS:
        dominant_lang = max(
            VOICE_MODELS.keys(),
            key=lambda l: sum(len(t) for lg, t in segments if lg == l)
        )
        return [(dominant_lang, text)]

    return segments


def synthesize_multilang_to_ogg(text: str) -> tuple[str, str]:
    """
    Come synthesize_to_ogg, ma rileva la lingua per ogni segmento del
    testo e usa la voce Piper corrispondente per ciascuno, invece di
    leggere tutto con una sola voce. Utile quando la risposta mescola
    più lingue (dialetto + traduzione tra parentesi, code-switching).

    Ritorna (ogg_path, lang_label): lang_label è una stringa leggibile
    con le lingue effettivamente usate nella sintesi (es. "🇮🇹 Italiano
    + 🇬🇧 English"), pensata per essere passata come caption a
    reply_voice() su Telegram.
    """
    clean_text = _strip_for_speech(text)

    if not clean_text:
        raise ValueError("Testo vuoto dopo la pulizia: niente da sintetizzare.")

    segments = _split_into_lang_segments(clean_text)
    langs_used = list(dict.fromkeys(lang for lang, _ in segments))
    lang_label = _format_lang_label(langs_used)

    file_id = uuid.uuid4().hex
    wav_paths = []

    try:
        for i, (lang, seg_text) in enumerate(segments):
            voice = _get_voice(lang)
            wav_path = os.path.join(TTS_TMP_DIR, f"{file_id}_{i}.wav")
            with wave.open(wav_path, "wb") as wav_file:
                voice.synthesize_wav(seg_text, wav_file)
            wav_paths.append(wav_path)

        ogg_path = os.path.join(TTS_TMP_DIR, f"{file_id}.ogg")

        if len(wav_paths) == 1:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", wav_paths[0],
                 "-c:a", "libopus", "-b:a", "32k", ogg_path],
                capture_output=True, timeout=60,
            )
        else:
            # Voci diverse possono avere sample rate diversi (es.
            # x_low vs medium) — resample esplicito prima del concat
            # per evitare glitch o fallimento silenzioso di ffmpeg.
            inputs = []
            filter_parts = []
            for i, wp in enumerate(wav_paths):
                inputs += ["-i", wp]
                filter_parts.append(f"[{i}:a]aresample=22050[a{i}]")
            concat_inputs = "".join(f"[a{i}]" for i in range(len(wav_paths)))
            filter_complex = ";".join(filter_parts) + \
                f";{concat_inputs}concat=n={len(wav_paths)}:v=0:a=1[out]"

            result = subprocess.run(
                ["ffmpeg", "-y", *inputs,
                 "-filter_complex", filter_complex,
                 "-map", "[out]",
                 "-c:a", "libopus", "-b:a", "32k", ogg_path],
                capture_output=True, timeout=90,
            )

        if result.returncode != 0 or not os.path.exists(ogg_path):
            raise RuntimeError(
                f"ffmpeg concat failed: {result.stderr.decode(errors='ignore')}"
            )

        return ogg_path, lang_label

    finally:
        for wp in wav_paths:
            if os.path.exists(wp):
                os.remove(wp)
