"""
core/improve_engine.py
======================
Engine specializzato nel miglioramento e refactoring di codice sorgente esistente.
Inietta le regole del LELES PROJECT CONTEXT e gestisce l'analisi mirata di file .py.
"""

import os
import logging

from core.emergence_engine import (
    PROJECT_CONTEXT,
    create_experiment,
    create_run,
    run_experiment,
)

logger = logging.getLogger(__name__)


def run_code_improvement(
    target_file_path: str,
    feature_request: str,
    num_iterations: int = 3,
    temperature: float = 0.7,
    seed: int = 42,
) -> int:
    """Carica un file sorgente reale e avvia la discussione degli agenti su di esso."""

    if not target_file_path or not os.path.exists(target_file_path):
        raise FileNotFoundError(
            f"❌ Impossibile trovare il file sorgente target: {target_file_path}"
        )

    with open(target_file_path, "r", encoding="utf-8") as f:
        file_content = f.read()

    file_name = os.path.basename(target_file_path)

    formatted_scenario = f"""{PROJECT_CONTEXT}

=== OBIETTIVO E RICHIESTA DI MIGLIORAMENTO ===
{feature_request}

=== CODICE SORGENTE ATTUALE (File: {file_name}) ===
```python
{file_content}
```"""

    exp_id = create_experiment(
        name=f"Improve File: {file_name}",
        description=f"Refactoring guidato di {target_file_path}",
    )

    run_id = create_run(
        experiment_id=exp_id,
        seed=seed,
        temperature=temperature,
    )

    initial_world_state = {
        "scenario": formatted_scenario,
        "target_file": target_file_path,
        "source_code": file_content,
    }

    run_experiment(
        run_id=run_id,
        num_iterations=num_iterations,
        initial_world_state=initial_world_state,
        temperature=temperature,
        seed=seed,
    )

    return run_id
