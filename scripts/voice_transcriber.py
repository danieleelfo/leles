"""
voice_transcriber.py — Trascrizione vocale locale per Lelé, via faster-whisper.

Il modello gira 100% in locale (nessuna chiamata cloud), coerente con
l'architettura Ollama-first del progetto.

Requisiti:
    pip install faster-whisper

Il modello viene caricato UNA SOLA VOLTA a livello di modulo (singleton lazy)
e riusato per ogni messaggio vocale, per evitare il costo di reload ad ogni
trascrizione (che sarebbe qualche secondo perso ogni volta).
"""

import os
import logging
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# --- Config (override via variabili ambiente, nessuna modifica al codice) ---
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")   # tiny/base/small/medium/large-v3
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")             # su Mac senza CUDA: sempre "cpu"
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # int8 = molto più veloce su CPU

_model = None


def get_model() -> WhisperModel:
    """Carica il modello Whisper una sola volta (lazy singleton)."""
    global _model
    if _model is None:
        logger.info(
            f"🎙️  Caricamento Whisper ({WHISPER_MODEL_SIZE}, "
            f"device={WHISPER_DEVICE}, compute={WHISPER_COMPUTE_TYPE})..."
        )
        _model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        logger.info("🎙️  Whisper pronto.")
    return _model


def transcribe_audio(file_path: str, language: str = "it", initial_prompt: str = None) -> str:
    """
    Trascrive un file audio (ogg/mp3/wav/m4a/...) in testo.

    initial_prompt: testo opzionale passato a Whisper per orientare la
    trascrizione verso un vocabolario noto (es. i comandi di Lelé: "query",
    "review"...). Zero-effort dialect/style bias — non forza nulla, aumenta
    solo la probabilità che Whisper scelga quelle parole quando l'audio è
    ambiguo (utile per "query" che a volte esce come "queri").

    Ritorna stringa vuota se non riesce a estrarre nulla di intelligibile
    (es. audio muto o troppo rumoroso).
    """
    model = get_model()

    segments, info = model.transcribe(
        file_path,
        language=language,
        beam_size=5,
        vad_filter=True,  # filtra i silenzi — utile per i vocali Telegram
        initial_prompt=initial_prompt,
    )

    text = " ".join(segment.text.strip() for segment in segments).strip()

    logger.info(
        f"🎙️  Trascrizione completata ({info.language}, "
        f"{info.duration:.1f}s): '{text[:120]}'"
    )

    return text
