"""
scripts/run_standalone_exp.py
=============================
Script CLI per testare il motore Emergence Lab in standalone.

Uso:
    python -m scripts.run_standalone_exp
    python -m scripts.run_standalone_exp --iterations 5 --temp 0.8 --seed 123
"""

import argparse
import logging
import sys
from datetime import datetime

from core.emergence_engine import (
    create_experiment,
    create_run,
    finalize_run,
    run_experiment,
)


def main():
    parser = argparse.ArgumentParser(description="Emergence Lab Standalone Runner")
    parser.add_argument("--name", type=str, default="Simulazione Standalone", help="Nome dell'esperimento")
    parser.add_argument("--desc", type=str, default="Test CLI manuale", help="Descrizione esperimento")
    parser.add_argument("--iterations", type=int, default=3, help="Numero di iterazioni")
    parser.add_argument("--temp", type=float, default=0.7, help="Temperatura degli LLM")
    parser.add_argument("--seed", type=int, default=42, help="Seed per la permutazione random dei modelli")
    parser.add_argument(
        "--scenario",
        type=str,
        default="Progettazione di una colonia sostenibile su Marte",
        help="Scenario o problema iniziale da risolvere",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("🚀 Inizializzazione simulazione Emergence Lab...")

    # 1. Creazione record Esperimento e Run nel DB
    exp_id = create_experiment(name=args.name, description=args.desc)
    run_id = create_run(experiment_id=exp_id, seed=args.seed, temperature=args.temp)

    initial_world_state = {
        "scenario": args.scenario,
        "notes": "Avvio simulazione in modalità standalone.",
        "created_at": datetime.now().isoformat(),
    }

    # 2. Esecuzione loop delle iterazioni
    try:
        logging.info(f"▶️ Avvio Run {run_id} ({args.iterations} iterazioni)...")
        run_experiment(
            run_id=run_id,
            num_iterations=args.iterations,
            initial_world_state=initial_world_state,
            temperature=args.temp,
            seed=args.seed,
        )
        logging.info(f"\n✅ Esperimento completato! Risultati salvati per la Run ID: {run_id}")

    except Exception as e:
        logging.error(f"\n❌ Errore durante l'esecuzione della Run {run_id}: {e}", exc_info=True)
        finalize_run(run_id, status="FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
