"""
core/db_init_exp.py

Emergence Lab database initialization.

Safe to execute multiple times.

Usage:
    python -m core.db_init_exp
"""

import json
from psycopg2.extras import execute_batch

# Reuse the same connection used by Leles
from core.db import get_connection


# ==========================================================
# DATABASE DDL
# ==========================================================

DDL = [

# Schema
"""
CREATE SCHEMA IF NOT EXISTS emergence;
""",

# Global configuration
"""
CREATE TABLE IF NOT EXISTS emergence.config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
);
""",

# Available models
"""
CREATE TABLE IF NOT EXISTS emergence.models (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL DEFAULT 'ollama',
    version TEXT,
    parameters JSONB DEFAULT '{}'::jsonb
);
""",

# Agent profiles
"""
CREATE TABLE IF NOT EXISTS emergence.agent_profiles (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    system_prompt TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, version)
);
""",

# Agents
"""
CREATE TABLE IF NOT EXISTS emergence.agents (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    profile_id INTEGER REFERENCES emergence.agent_profiles(id),
    default_model_id INTEGER REFERENCES emergence.models(id)
);
""",

# Experiment definition
"""
CREATE TABLE IF NOT EXISTS emergence.experiments (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'CREATED',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""",

# Experiment runs
"""
CREATE TABLE IF NOT EXISTS emergence.runs (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER REFERENCES emergence.experiments(id),
    random_seed INTEGER,
    temperature DOUBLE PRECISION DEFAULT 0.7,
    config JSONB DEFAULT '{}'::jsonb,
    status TEXT DEFAULT 'CREATED',
    started_at TIMESTAMP,
    ended_at TIMESTAMP
);
""",

# Iterations
"""
CREATE TABLE IF NOT EXISTS emergence.iterations (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES emergence.runs(id) ON DELETE CASCADE,
    iteration_number INTEGER NOT NULL,
    world_state JSONB DEFAULT '{}'::jsonb,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    UNIQUE(run_id, iteration_number)
);
""",

# Messages
"""
CREATE TABLE IF NOT EXISTS emergence.messages (
    id SERIAL PRIMARY KEY,
    iteration_id INTEGER NOT NULL REFERENCES emergence.iterations(id) ON DELETE CASCADE,
    agent_id INTEGER NOT NULL REFERENCES emergence.agents(id),
    model_id INTEGER NOT NULL REFERENCES emergence.models(id),
    parent_message_id INTEGER REFERENCES emergence.messages(id),
    role TEXT DEFAULT 'assistant',
    temperature DOUBLE PRECISION,
    prompt TEXT,
    response TEXT,
    duration_ms INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""",

# Metrics
"""
CREATE TABLE IF NOT EXISTS emergence.metrics (
    id SERIAL PRIMARY KEY,
    iteration_id INTEGER NOT NULL REFERENCES emergence.iterations(id) ON DELETE CASCADE,
    agent_id INTEGER REFERENCES emergence.agents(id),
    model_id INTEGER REFERENCES emergence.models(id),
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""",

# INDEXES
"""CREATE INDEX IF NOT EXISTS idx_exp_runs ON emergence.runs(experiment_id);""",
"""CREATE INDEX IF NOT EXISTS idx_iterations_run ON emergence.iterations(run_id);""",
"""CREATE INDEX IF NOT EXISTS idx_messages_iteration ON emergence.messages(iteration_id);""",
"""CREATE INDEX IF NOT EXISTS idx_messages_agent ON emergence.messages(agent_id);""",
"""CREATE INDEX IF NOT EXISTS idx_messages_model ON emergence.messages(model_id);""",
"""CREATE INDEX IF NOT EXISTS idx_metrics_iteration ON emergence.metrics(iteration_id);""",
"""CREATE INDEX IF NOT EXISTS idx_metrics_agent ON emergence.metrics(agent_id);""",
"""CREATE INDEX IF NOT EXISTS idx_metrics_model ON emergence.metrics(model_id);"""

]


# ==========================================================
# INITIAL CONFIGURATION
# ==========================================================

CONFIG = [
    ("world_name", "Emergence Lab", "Simulation world name"),
    ("max_iterations", "20", "Maximum iterations per run"),
    ("judge_model", "gemma4", "LLM used as final judge"),
    ("default_temperature", "0.7", "Default Ollama temperature"),
    ("parallel_agents", "false", "Run all agents simultaneously"),
    ("memory_enabled", "true", "Enable persistent agent memory"),
]

MODELS = [
    ("llama3", "ollama", "latest", "{}"),
    ("gemma4", "ollama", "latest", "{}"),
    ("qwen2.5", "ollama", "latest", "{}"),
    ("deepseek-r1", "ollama", "latest", "{}"),
    ("mistral", "ollama", "latest", "{}"),
]

AGENT_PROFILES = [
(
"Planner", 1,
"""You are the Planner.
Your objective is to coordinate the simulation.
Analyse the current world state.
Break large problems into smaller tasks.
Assign priorities.
Always think before proposing actions.
Never write code unless explicitly requested."""
),
(
"Scientist", 1,
"""You are the Scientist.
Question assumptions.
Reason carefully.
Use evidence.
Detect inconsistencies.
Suggest experiments before conclusions."""
),
(
"Builder", 1,
"""You are the Builder.
Transform ideas into practical solutions.
Produce concrete implementation plans.
When useful, generate code.
Focus on execution."""
),
(
"Critic", 1,
"""You are the Critic.
Challenge every proposal.
Search for bugs.
Search for logical errors.
Search for missing information.
Always explain WHY."""
),
(
"Observer", 1,
"""You are the Observer.
Never influence the discussion.
Measure behaviours.
Record interesting events.
Produce objective summaries.
Generate metrics whenever possible."""
),
]

AGENTS = [
    ("Planner",   "Planner",   "llama3"),
    ("Scientist", "Scientist", "deepseek-r1"),
    ("Builder",   "Builder",   "qwen2.5"),
    ("Critic",    "Critic",    "mistral"),
    ("Observer",  "Observer",  "gemma4"),
]


# ==========================================================
# SEED FUNCTIONS
# ==========================================================

def seed_config(cur):
    execute_batch(
        cur,
        """
        INSERT INTO emergence.config (key, value, description)
        VALUES (%s, %s, %s)
        ON CONFLICT(key) DO NOTHING;
        """,
        CONFIG
    )

def seed_models(cur):
    execute_batch(
        cur,
        """
        INSERT INTO emergence.models (name, provider, version, parameters)
        VALUES (%s, %s, %s, %s::jsonb)
        ON CONFLICT(name) DO NOTHING;
        """,
        MODELS
    )

def seed_profiles(cur):
    execute_batch(
        cur,
        """
        INSERT INTO emergence.agent_profiles (name, version, system_prompt)
        VALUES (%s, %s, %s)
        ON CONFLICT(name, version) DO NOTHING;
        """,
        AGENT_PROFILES
    )

def seed_agents(cur):
    for agent_name, profile_name, model_name in AGENTS:
        cur.execute(
            """
            INSERT INTO emergence.agents (name, profile_id, default_model_id)
            SELECT %s, p.id, m.id
            FROM emergence.agent_profiles p, emergence.models m
            WHERE p.name = %s AND p.version = 1 AND m.name = %s
            ON CONFLICT(name) DO NOTHING;
            """,
            (agent_name, profile_name, model_name)
        )

def seed_all(cur):
    print("Seeding configuration...")
    seed_config(cur)
    print("Seeding models...")
    seed_models(cur)
    print("Seeding agent profiles...")
    seed_profiles(cur)
    print("Seeding agents...")
    seed_agents(cur)
    print("Seed completed.")


# ==========================================================
# DATABASE INITIALIZATION
# ==========================================================

def create_schema(cur):
    print("Creating Emergence Lab schema...")
    for sql in DDL:
        cur.execute(sql)
    print(f"{len(DDL)} DDL statements executed.")

def initialize_database():
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        print("=" * 60)
        print(" Emergence Lab Database Initialization")
        print("=" * 60)

        create_schema(cur)
        seed_all(cur)
        conn.commit()

        print("\n✅ Emergence Lab initialized successfully.\n")
        return True

    except Exception as ex:
        if conn:
            conn.rollback()
        print(f"\n❌ Initialization failed: {type(ex).__name__}\n{ex}\n")
        raise

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()

def main():
    initialize_database()

if __name__ == "__main__":
    main()
