"""
core/emergence_worlds.py — Scenari salvati per Emergence Lab (emergence.scenarios).

Permette di salvare uno scenario una volta e riusarlo per più run senza
doverlo riscrivere/incollare ogni volta (utile soprattutto da mobile).
Gli scenari sono immutabili: per "modificarne" uno se ne salva uno nuovo,
mai update in-place — così restano uno storico coerente di cosa è stato
testato, e un run passato resta sempre ricostruibile risalendo al suo
scenario originale.

Comandi Leles equivalenti:
    save world <nome> as "<testo scenario>"
    query worlds
    query world <id>
"""

from core.db import get_connection

_DDL = """
CREATE TABLE IF NOT EXISTS emergence.scenarios (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_table(cur):
    """Self-healing: crea la tabella al primo uso se non esiste ancora,
    stesso principio 'safe to execute multiple times' di db_init_exp.py —
    evita un passo di init manuale separato."""
    cur.execute(_DDL)


def save_world(name: str, description: str) -> int:
    """Salva un nuovo scenario, ritorna l'id assegnato."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_table(cur)
        cur.execute(
            "INSERT INTO emergence.scenarios (name, description) VALUES (%s, %s) RETURNING id",
            (name, description),
        )
        world_id = cur.fetchone()[0]
        conn.commit()
        return world_id
    finally:
        cur.close()
        conn.close()


def get_world(world_id: int):
    """Ritorna {'id':.., 'name':.., 'description':.., 'created_at':..} o None."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_table(cur)
        cur.execute(
            "SELECT id, name, description, created_at FROM emergence.scenarios WHERE id = %s",
            (world_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "description": row[2], "created_at": str(row[3])}
    finally:
        cur.close()
        conn.close()


def list_worlds(limit: int = 20):
    """Ritorna [{'id':.., 'name':.., 'created_at':..}, ...] — SENZA il testo
    completo (per stare comodamente in un messaggio Telegram)."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_table(cur)
        cur.execute(
            "SELECT id, name, created_at FROM emergence.scenarios ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
        return [{"id": r[0], "name": r[1], "created_at": str(r[2])} for r in rows]
    finally:
        cur.close()
        conn.close()
