"""
core/llm.py
===========

Client generico per Ollama.

Caratteristiche:
- Retry automatico
- Timeout
- Logging
- Connessione persistente (Session)
- Parametri configurabili
"""

import logging
import time

import requests
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"

DEFAULT_CTX = 16384
DEFAULT_NUM_PREDICT = 4096
DEFAULT_TIMEOUT = (10, 600)  # (connect, read)

_session = requests.Session()


def query_model(
    model_name: str,
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    num_ctx: int = DEFAULT_CTX,
    num_predict: int = DEFAULT_NUM_PREDICT,
    seed: int | None = None,
    retries: int = 3,
):
    """
    Esegue una richiesta ad Ollama.

    Returns:
        {
            "success": bool,
            "response": str,
            "duration_ms": int,
            "prompt_tokens": int,
            "completion_tokens": int,
            "total_tokens": int,
            "model": str,
            "error": str | None,
        }

    Solleva RuntimeError solo se tutti i tentativi falliscono.
    """

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }

    if system_prompt:
        payload["system"] = system_prompt

    if seed is not None:
        payload["options"]["seed"] = seed

    last_error = None

    for attempt in range(1, retries + 1):

        try:
            start = time.perf_counter()

            response = _session.post(
                OLLAMA_URL,
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )

            response.raise_for_status()

            elapsed = int((time.perf_counter() - start) * 1000)

            data = response.json()

            return {
                "success": True,
                "model": model_name,
                "response": data.get("response", ""),
                "duration_ms": elapsed,
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": (
                    data.get("prompt_eval_count", 0)
                    + data.get("eval_count", 0)
                ),
                "error": None,
            }

        except (Timeout, RequestException) as exc:

            last_error = exc

            logger.warning(
                "Ollama call failed (%s/%s) model=%s : %s",
                attempt,
                retries,
                model_name,
                exc,
            )

            if attempt < retries:
                time.sleep(2 ** (attempt - 1))

    raise RuntimeError(
        f"Ollama request failed after {retries} attempts "
        f"for model '{model_name}'. Last error: {last_error}"
    )
