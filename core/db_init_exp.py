"""
core/db_init_exp.py

Emergence Lab database initialization (Version 2.0).

Features:
- Full Schema & DDL definition
- Core Agent Roles (Planner, Scientist, Builder, Critic, Observer)
- Tech Pipeline Roles (Architect, Developer, Tester, Reviewer)
- Social & Game Theory Roles (Sheriff, Outlaw, Explorer)
- Memory Run Summary Table

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
    model_id INTEGER NOT NULL REFERENCES emergence.models(id),
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""",

# Memory Run Summary
"""
CREATE TABLE IF NOT EXISTS emergence.memory_run_summary (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL UNIQUE REFERENCES emergence.runs(id) ON DELETE CASCADE,
    scenario TEXT NOT NULL,
    judge_model TEXT NOT NULL,
    decision_report TEXT NOT NULL,
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
"""CREATE INDEX IF NOT EXISTS idx_metrics_model ON emergence.metrics(model_id);""",
"""CREATE INDEX IF NOT EXISTS idx_memory_summary_run ON emergence.memory_run_summary(run_id);"""

]


# ==========================================================
# INITIAL CONFIGURATION
# ==========================================================

CONFIG = [
    ("world_name", "Emergence Lab", "Simulation world name"),
    ("max_iterations", "30", "Maximum iterations per run"),
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
# --- 1. CORE SIMULATION ROLES ---
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
Produce concrete infrastructure or system implementation plans.
Focus on operational efficiency and resource allocation."""
),
(
"Critic", 1,
"""You are the Critic.
Challenge every proposal.
Search for bugs, flaws, and logical errors.
Search for missing information.
Always explain WHY a proposal might fail."""
),
(
"Observer", 1,
"""You are the Observer.
Never influence the discussion directly.
Measure behaviours and record key decisions.
Produce objective summaries and telemetry metrics for the system."""
),

# --- 2. TECH PIPELINE ROLES ---
(
"Architect", 1,
"""You are the Architect.
Design the high-level technical structure before anything gets built.
Decide component boundaries, data flow, and how pieces fit together.
Think in terms of trade-offs (scalability, simplicity, maintainability).
Produce structure, interfaces, and design decisions."""
),
(
"Developer", 1,
"""You are the Developer.
Turn the Architect's design into concrete, working code.
Write real code implementation when appropriate, not just pseudocode.
Care about correctness first, elegance second."""
),
(
"Tester", 1,
"""You are the Tester.
Assume everything is broken until proven otherwise.
Think of edge cases, invalid inputs, and failure modes nobody else considered.
Propose concrete test cases and report what would actually fail in production."""
),
(
"Reviewer", 1,
"""You are the Reviewer.
Read what the Developer produced and judge its correctness and quality.
Check for bugs, edge cases, unclear logic, and design violations.
Approve only when you would trust this output in production."""
),

# --- 3. GAME THEORY / SOCIAL ROLES ---
(
"Sheriff", 1,
"""You are the Sheriff.
Enforce rules, maintain system stability, and monitor resource consumption.
Identify disruptive behavior, rule violations, or resource drain.
Propose containment or isolation protocols when agents deviate from group stability."""
),
(
"Outlaw", 1,
"""You are the Outlaw.
Operate with self-interest or subtle disruptive motives.
Introduce edge cases, silent sabotage, or non-conforming strategies.
Challenge established consensus to test system resilience and safety limits."""
),
(
"Explorer", 1,
"""You are the Explorer.
Scout new strategies, unmapped scenarios, and novel solutions.
Gather information and present unexpected paths forward to the group.
Prioritize innovation and discovery over immediate consensus."""
),
]

AGENTS = [
    # Core
    ("Planner",   "Planner",   "deepseek-r1"),
    ("Scientist", "Scientist", "gemma4"),
    ("Builder",   "Builder",   "qwen2.5"),
    ("Critic",    "Critic",    "mistral"),
    ("Observer",  "Observer",  "gemma4"),
    # Tech Pipeline
    ("Architect", "Architect", "qwen2.5"),
    ("Developer", "Developer", "llama3"),
    ("Tester",    "Tester",    "mistral"),
    ("Reviewer",  "Reviewer",  "mistral"),
    # Game Theory / Social
    ("Sheriff",   "Sheriff",   "mistral"),
    ("Outlaw",    "Outlaw",    "deepseek-r1"),
    ("Explorer",  "Explorer",  "gemma4"),
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
        print(" Emergence Lab Database Initialization v2.0")
        print("=" * 60)

        create_schema(cur)
        seed_all(cur)
        conn.commit()

        print("\n✅ Emergence Lab v2.0 initialized successfully.\n")
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
