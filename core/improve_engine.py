"""
core/improve_engine.py
======================
Engine specializzato nel miglioramento e refactoring di codice sorgente esistente.
Inietta le regole del LELES PROJECT CONTEXT e gestisce l'analisi mirata di file .py.

FIX (2026-09-10): run_code_improvement() non passava mai `config` a
run_experiment(). Senza config, run_experiment() usa il comportamento
storico: TUTTI e 12 gli agenti in DB + model_strategy="random" di default.
Ma "random" richiede len(agenti) == len(modelli) esatto — con 12 agenti e
solo 5 modelli configurati in emergence.models, questo faceva fallire
IMMEDIATAMENTE (ValueError, ~8 secondi, prima ancora di chiamare un LLM)
ogni singola esecuzione di improve_dag, indipendentemente dai parametri
passati via conf Airflow.

Fix: costruiamo esplicitamente un config con model_strategy="fixed" di
default (legge agent["default_model_id"], già impostato in DB per tutti
e 12 gli agenti — nessun bisogno di override manuali), e lo passiamo a
run_experiment(). Aggiunta anche la possibilità di restringere la
pipeline a un sottoinsieme di ruoli via `pipeline`, utile per un
refactoring mirato senza dover coinvolgere tutti e 12 gli agenti
(es. solo Developer/Reviewer/Tester per una code review pura).
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

# Pipeline di default per improve: i ruoli tecnici, non l'intero cast di 12
# (Sheriff/Outlaw/Explorer ecc. hanno poco senso per un task di refactoring
# codice). Se in futuro serve il cast completo, passare pipeline=None
# esplicitamente da chi chiama run_code_improvement().
DEFAULT_IMPROVE_PIPELINE = [
    "Planner",
    "Architect",
    "Developer",
    "Tester",
    "Reviewer",
]


def run_code_improvement(
    target_file_path: str,
    feature_request: str,
    num_iterations: int = 3,
    temperature: float = 0.7,
    seed: int = 42,
    pipeline: list | None = DEFAULT_IMPROVE_PIPELINE,
    model_strategy: str = "fixed",
    model_overrides: dict | None = None,
) -> int:
    """
    Carica un file sorgente reale e avvia la discussione degli agenti su di esso.

    pipeline: lista di nomi ruolo da usare (default: i 5 ruoli tecnici,
        vedi DEFAULT_IMPROVE_PIPELINE). Passare `None` esplicitamente per
        usare TUTTI e 12 gli agenti (in tal caso model_strategy="fixed" è
        obbligatorio, "random" fallirebbe per mismatch conteggio).
    model_strategy: "fixed" (default, legge default_model_id da DB — nessun
        modello va specificato a mano), "override" (richiede model_overrides
        completo per ogni ruolo in pipeline), oppure "random" (SOLO se
        len(pipeline) == numero di modelli configurati, altrimenti crasha).
    model_overrides: dict {ruolo: nome_modello}, usato solo se
        model_strategy="override".
    """

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

    config = {
        "pipeline": pipeline,
        "model_strategy": model_strategy,
    }

    if model_overrides:
        config["model_overrides"] = model_overrides

    run_id = create_run(
        experiment_id=exp_id,
        seed=seed,
        temperature=temperature,
        config=config,
    )

    initial_world_state = {
        "scenario": formatted_scenario,
        "target_file": target_file_path,
        "source_code": file_content,
    }

    logger.info(
        "🔧 Improve avviato: file=%s pipeline=%s model_strategy=%s run_id=%s",
        target_file_path,
        pipeline,
        model_strategy,
        run_id,
    )

    run_experiment(
        run_id=run_id,
        num_iterations=num_iterations,
        initial_world_state=initial_world_state,
        temperature=temperature,
        seed=seed,
        config=config,
    )

    return run_id
