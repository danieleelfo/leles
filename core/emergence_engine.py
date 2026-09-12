"""
core/emergence_engine.py
=========================
Motore di simulazione concettuale per Emergence Lab.

Gestisce la discussione multi-agente, salvando la cronologia nel DB per
consentire analisi e audit di coerenza. Supporta due modalità:

  - Storica (senza config): tutti gli agenti in DB, modelli a rotazione
    casuale ad ogni iterazione, prompt "broadcast" (ogni agente vede tutti
    i turni già fatti).
  - Configurabile (con config, vedi run_experiment): pipeline di ruoli
    esplicita e ordinata, strategia modello per ruolo (random/fixed/
    override), visibilità del prompt (broadcast/previous_only).
"""

import json
import logging
import random
from datetime import datetime

from core.db import get_connection
from core.llm import query_model

logger = logging.getLogger(__name__)


# FIX (2026-09-09): PROJECT_CONTEXT mancava — era importato da
# core/improve_engine.py (`from core.emergence_engine import PROJECT_CONTEXT, ...`)
# ma non era mai stato definito in questo file. Questo causava un
# ImportError a livello di modulo, che a sua volta faceva fallire il
# parsing di improve_dag.py in Airflow (DAG mostrato "in errore" nella UI,
# senza nemmeno bisogno di eseguirlo — l'import fallisce prima di qualsiasi
# task). Testo scritto da Claude su richiesta di Danny ("scrivi tu poi
# correggo") — da rivedere/personalizzare a piacere, non è vincolante.
#
# Scopo: dare agli agenti Emergence Lab un contesto minimo e stabile sul
# progetto Leles PRIMA di mostrargli codice reale da migliorare (usato da
# improve_engine.py in run_code_improvement(), interpolato nello scenario
# insieme al codice sorgente del file target).
PROJECT_CONTEXT = """
Contesto del progetto (Leles):

Leles è un ecosistema di assistenti AI locale-first, gestito quasi
esclusivamente via Telegram. Gira su Mac (Apple Silicon), usa Ollama per
l'inferenza locale (modelli: llama3, gemma4, qwen2.5, deepseek-r1,
mistral), PostgreSQL come storage persistente, FastAPI/uvicorn come layer
API, e Apache Airflow per l'orchestrazione di task lunghi/asincroni
(DAG in ~/Desktop/Danny/airflow/dags/, non tracciati in git).

Convenzioni di codice da rispettare quando si propongono modifiche:
- Connessioni al DB sempre tramite core/db.py (get_connection()), mai
  hardcodare credenziali o aprire connessioni parallele.
- Logging strutturato via modulo `logging`, non print() nudi nel codice
  di produzione (print() è accettabile solo per output diagnostico
  temporaneo negli script standalone).
- Mai usare kill -9 / pkill -9 sui processi: shutdown pulito e attesa
  prima di un eventuale restart, per evitare 409 Conflict lato Telegram
  su bot in polling.
- I path vanno calcolati dinamicamente (es. da __file__), mai
  hardcodati in valore assoluto quando evitabile.
- Le funzioni pubbliche hanno docstring in italiano, concise, che
  spiegano IL PERCHÉ di una scelta non ovvia, non solo COSA fa il codice.
- Le modifiche proposte devono essere file completi e autonomi, pronti
  per essere copiati ed eseguiti — niente snippet parziali o
  placeholder tipo "# resto invariato".

L'obiettivo di ogni miglioramento è codice più leggibile, robusto (error
handling esplicito), e coerente con queste convenzioni — non riscritture
speculative che cambiano l'architettura senza necessità.
""".strip()


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
    """Ritorna [{'id':.., 'name':.., 'system_prompt':..}, ...] con profilo unito.
    Prende SEMPRE tutti gli agenti in tabella, ordinati per id — comportamento
    storico, usato quando non è specificata una pipeline di ruoli esplicita."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.name, p.system_prompt, a.default_model_id
        FROM emergence.agents a
        JOIN emergence.agent_profiles p ON a.profile_id = p.id
        ORDER BY a.id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "name": r[1], "system_prompt": r[2], "default_model_id": r[3]} for r in rows]


def get_agents_by_names(names):
    """
    Ritorna gli agenti richiesti, NELL'ORDINE in cui sono stati richiesti —
    a differenza di get_agents() che ritorna sempre tutto ordinato per id.
    È la base della pipeline dinamica: `names` è l'ordine ruolo-per-ruolo
    che vuoi far girare (es. ["Planner", "Designer", "Reviewer", "Developer",
    "Tester"]), letto dal config del run.
    """
    if not names:
        return []

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.name, p.system_prompt, a.default_model_id
        FROM emergence.agents a
        JOIN emergence.agent_profiles p ON a.profile_id = p.id
        WHERE a.name = ANY(%s)
    """, (list(names),))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    by_name = {r[1]: {"id": r[0], "name": r[1], "system_prompt": r[2], "default_model_id": r[3]} for r in rows}

    missing = [n for n in names if n not in by_name]
    if missing:
        raise ValueError(f"Ruoli non trovati in emergence.agents: {missing}")

    # WHERE ... = ANY(%s) non garantisce l'ordine — lo ricostruiamo noi
    return [by_name[n] for n in names]


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
    logger.info(f"🧪 Experiment creato: id={exp_id} name={name} Contesto: {description}")
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


def assign_models_to_agents(agents, models, rng=None):
    """Strategia storica: shuffle casuale, un modello diverso per agente ad
    ogni chiamata. Richiede tanti modelli quanti agenti."""
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


def resolve_models_for_agents(agents, models, model_strategy="random", model_overrides=None, rng=None):
    """
    Determina quale modello usa ciascun agente per l'iterazione, secondo la
    strategia scelta (letta dal config del run):

      - "random"   — comportamento storico: shuffle casuale via
                      assign_models_to_agents (richiede n_agenti == n_modelli).
      - "fixed"     — usa agent["default_model_id"] di ciascun agente (colonna
                      già in schema, prima mai letta). Ogni ruolo della
                      pipeline deve avere un default_model_id impostato.
      - "override"  — usa model_overrides={"Planner": "llama3", ...}; i ruoli
                      non presenti nel dict ricadono su default_model_id.

    Ritorna {agent_id: {"model_id":.., "model_name":..}}, stessa forma di
    assign_models_to_agents, così run_iteration non deve distinguere le due.
    """
    if model_strategy == "random":
        return assign_models_to_agents(agents, models, rng=rng)

    if model_strategy not in ("fixed", "override"):
        raise ValueError(f"model_strategy sconosciuta: '{model_strategy}' (valide: random, fixed, override)")

    model_overrides = model_overrides or {}
    models_by_id = {m["id"]: m for m in models}
    models_by_name = {m["name"]: m for m in models}

    mapping = {}
    for agent in agents:
        model = None

        if model_strategy == "override" and agent["name"] in model_overrides:
            override_name = model_overrides[agent["name"]]
            model = models_by_name.get(override_name)
            if not model:
                raise ValueError(
                    f"Modello '{override_name}' (override per '{agent['name']}') "
                    f"non trovato in emergence.models"
                )
        else:
            model = models_by_id.get(agent.get("default_model_id"))

            if not model:
                raise ValueError(
                    f"Agente '{agent['name']}' non ha un default_model_id valido — "
                    f"impostalo in emergence.agents, oppure aggiungi un override "
                    f"per questo ruolo, oppure usa model_strategy='random'"
                )

        mapping[agent["id"]] = {"model_id": model["id"], "model_name": model["name"]}

    return mapping


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


def build_agent_prompt(world_state, transcript_so_far, agent_name, visibility="broadcast"):
    """
    visibility:
      - "broadcast"     — comportamento storico: l'agente vede TUTTI i turni
                          già fatti in questa iterazione. Con pipeline lunghe
                          (5 ruoli) il prompt cresce parecchio e diluisce il
                          segnale di ciascun passaggio.
      - "previous_only" — l'agente vede SOLO l'ultimo turno (il ruolo
                          immediatamente precedente nella pipeline). Pensato
                          per pipeline sequenziali tipo Planner -> Designer ->
                          Reviewer -> Developer -> Tester, dove ogni ruolo
                          reagisce a UN input preciso, non all'intera
                          discussione.
    """
    lines = [
        f"# YOUR ROLE\nYou are acting as the {agent_name}.\nStay consistent with your assigned personality.\n",
        f"# WORLD STATE\n{json.dumps(world_state or {}, ensure_ascii=False, indent=2)}\n"
    ]

    visible_turns = transcript_so_far
    if visibility == "previous_only" and transcript_so_far:
        visible_turns = transcript_so_far[-1:]

    if visible_turns:
        header = "# PREVIOUS STEP" if visibility == "previous_only" else "# CURRENT ITERATION DISCUSSION"
        lines.append(f"{header}\n")
        for turn in visible_turns:
            lines.append(f"[{turn['agent_name']}]\n{turn['response']}\n")
    else:
        lines.append("You are the first agent speaking in this iteration.\n")

    lines.append(
        "# YOUR TASK\n"
        "Continue the discussion.\n"
        "Do NOT repeat previous answers.\n"
        "Build upon previous reasoning.\n"
        "Be concise, practical and logical.\n"
    )

    return "\n".join(lines)


def build_broadcast_prompt(world_state, transcript_so_far, agent_name):
    """Alias retrocompatibile — equivale a build_agent_prompt(..., visibility='broadcast')."""
    return build_agent_prompt(world_state, transcript_so_far, agent_name, visibility="broadcast")


def run_agent_turn(iteration_id, agent, model_id, model_name, world_state,
                    transcript_so_far, temperature=0.7, parent_message_id=None,
                    visibility="broadcast"):
    prompt = build_agent_prompt(world_state, transcript_so_far, agent["name"], visibility=visibility)

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

    return {
        "message_id": message_id,
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "model_id": model_id,
        "model_name": model_name,
        "response": result["response"],
    }


def run_iteration(run_id, iteration_number, world_state, agents, models,
                   temperature=0.7, rng=None, model_strategy="random",
                   model_overrides=None, visibility="broadcast"):
    iteration_id = create_iteration(run_id, iteration_number, world_state)
    model_map = resolve_models_for_agents(
        agents, models,
        model_strategy=model_strategy,
        model_overrides=model_overrides,
        rng=rng,
    )

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
            visibility=visibility,
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


def run_experiment(run_id, num_iterations, initial_world_state=None, temperature=0.7,
                    seed=None, config=None):
    """
    config (opzionale, stessa struttura salvata in runs.config):
        {
            "pipeline": ["Planner", "Designer", "Reviewer", "Developer", "Tester"],
            "model_strategy": "random" | "fixed" | "override",
            "model_overrides": {"Planner": "llama3", ...},   # solo per "override"
            "visibility": "broadcast" | "previous_only",
        }
    Senza config (o con config={}), il comportamento è quello storico:
    tutti gli agenti in DB, modelli a rotazione casuale, prompt broadcast.
    """
    config = config or {}
    pipeline_names = config.get("pipeline")
    model_strategy = config.get("model_strategy", "random")
    model_overrides = config.get("model_overrides")
    visibility = config.get("visibility", "broadcast")

    agents = get_agents_by_names(pipeline_names) if pipeline_names else get_agents()
    models = get_models()

    if model_strategy == "random" and len(agents) != len(models):
        raise ValueError(
            f"model_strategy='random' richiede lo stesso numero di agenti e modelli "
            f"(agents={len(agents)}, models={len(models)}) — con una pipeline di "
            f"dimensione diversa usa model_strategy='fixed' o 'override'"
        )

    rng = random.Random(seed) if seed is not None else random
    world_state = initial_world_state or {"iteration": 0, "notes": "Inizio simulazione."}
    iterations_summary = []

    for i in range(1, num_iterations + 1):
        world_state["iteration"] = i
        result = run_iteration(
            run_id, i, world_state, agents, models,
            temperature=temperature, rng=rng,
            model_strategy=model_strategy,
            model_overrides=model_overrides,
            visibility=visibility,
        )
        iterations_summary.append(result)

        # Il turno finale della pipeline porta avanti il contesto alla prossima
        # iterazione. Prima si cercava esplicitamente un agente chiamato
        # "Observer" (presente per costruzione nella vecchia pipeline fissa);
        # con pipeline dinamiche quel ruolo potrebbe non esistere, quindi si
        # usa semplicemente l'ultimo turno dell'iterazione, chiunque sia.
        last_turn = result["transcript"][-1] if result["transcript"] else None
        if last_turn:
            world_state = {
                **world_state,
                "iteration": i,
                "notes": last_turn["response"][:2000],
            }

    finalize_run(run_id)
    return iterations_summary
