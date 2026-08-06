import time
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"

def query_model(model_name: str, prompt: str, system_prompt: str = None, temperature: float = 0.7):
    """
    Client generico per effettuare chiamate ad Ollama.
    Ritorna la risposta e i metadati di esecuzione.
    """
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": 16384,
            "num_predict": 4096,
            "temperature": temperature
        }
    }
    
    if system_prompt:
        payload["system"] = system_prompt

    start_time = time.time()
    response = requests.post(OLLAMA_URL, json=payload)
    duration_ms = int((time.time() - start_time) * 1000)
    
    response.raise_for_status()
    data = response.json()

    return {
        "response": data.get("response", ""),
        "duration_ms": duration_ms,
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "completion_tokens": data.get("eval_count", 0),
        "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
    }
