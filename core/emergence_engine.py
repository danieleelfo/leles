"""
core/emergence_engine.py
=========================
Motore di simulazione per Emergence Lab.

Logica di una RUN:
  - ad ogni iterazione i 5 modelli vengono assegnati random (senza ripetizioni,
    permutazione 1:1) alle 5 personalità (agent_profiles)
  - dentro l'iterazione gli agenti parlano in ordine ma con visibilità BROADCAST:
    ogni agente vede il world_state + TUTTI i messaggi già scritti in
    quella iterazione (non solo il messaggio precedente)
  - ogni messaggio viene salvato in emergence.messages con agent_id e model_id
    (indipendenti, il binding cambia ad ogni iterazione)
  - metriche semplici (tokens, durata) vengono salvate in emergence.metrics
    per ogni messaggio prodotto

Questo modulo non dipende da Airflow: è testabile/eseguibile standalone.
I DAG in dags/ lo chiamano come task Python.
"""

import json
import random
import logging
from datetime import datetime

from core.db import get_connection
from core.llm import query_model

logger = logging.getLogger(__name__)


# ==========================================================
# LETTURA CONFIGURAZIONE / ANAGRAFICHE
# ==========================================================

def get_config_value(key, default=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM emergence.config WHERE key = %s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else default


def get_models():
    """Ritorna [{'id':.., 'name':..}, ...] per tutti i modelli configurati."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM emergence.models ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "name": r[1]} for r in rows]


def get_agents():
    """Ritorna [{'id':.., 'name':.., 'system_prompt':..}, ...] con profilo unito."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.name, p.system_prompt
        FROM emergence.agents a
        JOIN emergence.agent_profiles p ON a.profile_id = p.id
        ORDER BY a.id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "name": r[1], "system_prompt": r[2]} for r in rows]


# ==========================================================
# CREAZIONE EXPERIMENT / RUN / ITERATION
# ==========================================================

def create_experiment(name, description=""):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO emergence.experiments (name, description, status)
        VALUES (%s, %s, 'CREATED')
        RETURNING id
        """,
        (name, description),
    )
    exp_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"🧪 Experiment creato: id={exp_id} name={name}")
    return exp_id


def create_run(experiment_id, seed=None, temperature=0.7, config=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO emergence.runs
            (experiment_id, random_seed, temperature, config, status, started_at)
        VALUES (%s, %s, %s, %s::jsonb, 'RUNNING', %s)
        RETURNING id
        """,
        (experiment_id, seed, temperature, json.dumps(config or {}), datetime.utcnow()),
    )
    run_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"🚀 Run creata: id={run_id} experiment_id={experiment_id} seed={seed}")
    return run_id


def finalize_run(run_id, status="COMPLETED"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE emergence.runs
        SET status = %s, ended_at = %s
        WHERE id = %s
        """,
        (status, datetime.utcnow(), run_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"🏁 Run {run_id} finalizzata con status={status}")


def create_iteration(run_id, iteration_number, world_state):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO emergence.iterations
            (run_id, iteration_number, world_state, started_at)
        VALUES (%s, %s, %s::jsonb, %s)
        RETURNING id
        """,
        (run_id, iteration_number, json.dumps(world_state or {}), datetime.utcnow()),
    )
    iteration_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return iteration_id


def close_iteration(iteration_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE emergence.iterations SET ended_at = %s WHERE id = %s",
        (datetime.utcnow(), iteration_id),
    )
    conn.commit()
    cur.close()
    conn.close()


# ==========================================================
# ASSEGNAZIONE RANDOM MODELLI <-> AGENTI (permutazione, senza ripetizioni)
# ==========================================================

def assign_models_to_agents(agents, models, rng=None):
    """
    Permutazione 1:1 senza ripetizioni: ogni modello viene usato esattamente
    una volta in questa iterazione. Richiede len(agents) == len(models).

    Ritorna dict {agent_id: {'model_id':.., 'model_name':..}}
    """
    if len(agents) != len(models):
        raise ValueError(
            f"assign_models_to_agents richiede lo stesso numero di agenti e modelli "
            f"(agents={len(agents)}, models={len(models)})"
        )

    rng = rng or random
    shuffled_models = models[:]
    rng.shuffle(shuffled_models)

    mapping = {}
    for agent, model in zip(agents, shuffled_models):
        mapping[agent["id"]] = {"model_id": model["id"], "model_name": model["name"]}

    return mapping


# ==========================================================
# SALVATAGGIO MESSAGGI / METRICHE
# ==========================================================

def save_message(iteration_id, agent_id, model_id, prompt, result,
                  parent_message_id=None, role="assistant", temperature=None,
                  metadata=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO emergence.messages
            (iteration_id, agent_id, model_id, parent_message_id, role,
             temperature, prompt, response, duration_ms,
             prompt_tokens, completion_tokens, total_tokens, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            iteration_id, agent_id, model_id, parent_message_id, role,
            temperature, prompt, result["response"], result["duration_ms"],
            result["prompt_tokens"], result["completion_tokens"], result["total_tokens"],
            json.dumps(metadata or {}),
        ),
    )
    message_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return message_id


def save_metric(iteration_id, metric_name, metric_value, agent_id=None, model_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO emergence.metrics
            (iteration_id, agent_id, model_id, metric_name, metric_value)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (iteration_id, agent_id, model_id, metric_name, metric_value),
    )
    conn.commit()
    cur.close()
    conn.close()


# ==========================================================
# COSTRUZIONE PROMPT (broadcast round-robin)
# ==========================================================

def build_broadcast_prompt(world_state, transcript_so_far, agent_name):
    """
    transcript_so_far: lista di dict {'agent_name':.., 'response':..}
    già prodotti in QUESTA iterazione, in ordine di turno.
    """
    lines = [f"World state:\n{json.dumps(world_state or {}, ensure_ascii=False, indent=2)}\n"]

    if transcript_so_far:
        lines.append("Messaggi già scritti in questa iterazione (in ordine):")
        for turn in transcript_so_far:
            lines.append(f"[{turn['agent_name']}]: {turn['response']}")
    else:
        lines.append("Sei il primo a parlare in questa iterazione.")

    lines.append(f"\nOra tocca a te, {agent_name}. Rispondi in coerenza con il tuo ruolo.")

    return "\n".join(lines)


# ==========================================================
# TURNO SINGOLO AGENTE
# ==========================================================

def run_agent_turn(iteration_id, agent, model_id, model_name, world_state,
                    transcript_so_far, temperature=0.7, parent_message_id=None):
    prompt = build_broadcast_prompt(world_state, transcript_so_far, agent["name"])

    logger.info(f"🎭 Turno: agent={agent['name']} model={model_name} iteration_id={iteration_id}")

    result = query_model(
        model_name=model_name,
        prompt=prompt,
        system_prompt=agent["system_prompt"],
        temperature=temperature,
    )

    message_id = save_message(
        iteration_id=iteration_id,
        agent_id=agent["id"],
        model_id=model_id,
        prompt=prompt,
        result=result,
        parent_message_id=parent_message_id,
        temperature=temperature,
        metadata={"agent_name": agent["name"], "model_name": model_name},
    )

    # metriche base per il messaggio appena prodotto
    save_metric(iteration_id, "duration_ms", result["duration_ms"], agent["id"], model_id)
    save_metric(iteration_id, "total_tokens", result["total_tokens"], agent["id"], model_id)

    return {
        "message_id": message_id,
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "model_id": model_id,
        "model_name": model_name,
        "response": result["response"],
    }


# ==========================================================
# ITERAZIONE COMPLETA (broadcast round-robin su tutti gli agenti)
# ==========================================================

def run_iteration(run_id, iteration_number, world_state, agents, models,
                   temperature=0.7, rng=None):
    iteration_id = create_iteration(run_id, iteration_number, world_state)

    # nuova permutazione random ad OGNI iterazione
    model_map = assign_models_to_agents(agents, models, rng=rng)

    transcript = []
    last_message_id = None

    for agent in agents:
        assigned = model_map[agent["id"]]
        turn = run_agent_turn(
            iteration_id=iteration_id,
            agent=agent,
            model_id=assigned["model_id"],
            model_name=assigned["model_name"],
            world_state=world_state,
            transcript_so_far=transcript,
            temperature=temperature,
            parent_message_id=last_message_id,
        )
        transcript.append(turn)
        last_message_id = turn["message_id"]

    close_iteration(iteration_id)

    return {
        "iteration_id": iteration_id,
        "iteration_number": iteration_number,
        "model_map": model_map,
        "transcript": transcript,
    }


# ==========================================================
# RUN COMPLETA (loop di N iterazioni)
# ==========================================================

def run_experiment(run_id, num_iterations, initial_world_state=None, temperature=0.7, seed=None):
    agents = get_agents()
    models = get_models()

    if len(agents) != len(models):
        raise ValueError(
            f"run_experiment richiede lo stesso numero di agenti e modelli "
            f"(agents={len(agents)}, models={len(models)}) — controlla il seed di init_db_exp"
        )

    rng = random.Random(seed) if seed is not None else random

    world_state = initial_world_state or {"iteration": 0, "notes": "Inizio simulazione."}
    iterations_summary = []

    for i in range(1, num_iterations + 1):
        world_state["iteration"] = i
        result = run_iteration(run_id, i, world_state, agents, models, temperature=temperature, rng=rng)
        iterations_summary.append(result)

        # l'Observer chiude ogni iterazione: la sua risposta diventa la nota
        # di world_state per l'iterazione successiva (continuità narrativa)
        observer_turn = next(
            (t for t in result["transcript"] if t["agent_name"] == "Observer"), None
        )
        if observer_turn:
            world_state = {
                **world_state,  # mantiene scenario, execution_date, ecc.
                "iteration": i,
                "notes": observer_turn["response"][:2000],
            }

    finalize_run(run_id)

    return iterations_summary
