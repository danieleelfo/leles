from core.db import get_connection


# 💾 SALVA MEMORIA
def save_memory(role, content):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO memory (role, content) VALUES (%s, %s)",
        (role, content)
    )

    conn.commit()
    cur.close()
    conn.close()


# 📥 CARICA MEMORIA (ULTIMI N MESSAGGI)
def load_memory(limit=200):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT role, content
        FROM memory
        ORDER BY created_at DESC
        LIMIT %s
    """, (limit,))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    # ribalta per tornare in ordine cronologico
    rows.reverse()

    # formato leggibile per LLM
    return "\n".join([f"{r[0]}: {r[1]}" for r in rows])
def get_memory_by_role(role, limit=1):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT content
        FROM memory
        WHERE role = %s
        ORDER BY created_at DESC
        LIMIT %s
    """, (role, limit))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    if not rows:
        return None

    # se limit=1 → ritorna stringa diretta
    return rows[0][0] if limit == 1 else [r[0] for r in rows]

def load_memory_by_suffix(suffix, limit=20):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT role, content
        FROM memory
        WHERE role LIKE %s ESCAPE '\\'
        ORDER BY created_at DESC
        LIMIT %s
    """, (f"%\\_{suffix}", limit))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    rows.reverse()

    return "\n".join([f"{r[0]}: {r[1]}" for r in rows])

def load_memory_structured(limit=200):
    """
    Come load_memory(), ma ritorna dati strutturati (id/role/content/
    timestamp reali) invece di stringhe pre-formattate. Serve a
    export_agent per id reali, filtro ruolo affidabile e ordinamento
    corretto — cose che load_memory() da sola non può dare.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, role, content, created_at
        FROM memory
        ORDER BY created_at DESC
        LIMIT %s
    """, (limit,))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    rows.reverse()

    return [
        {
            "id": r[0],
            "role": r[1],
            "content": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
        }
        for r in rows
    ]

def get_memory_by_id_db(mem_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, role, content, created_at
        FROM memory
        WHERE id = %s
    """, (mem_id,))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return None

    return {"id": row[0], "role": row[1], "content": row[2], "created_at": row[3]}
