def load_memory(limit=20):
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

    rows.reverse()

    return "\n".join([f"{r[0]}: {r[1]}" for r in rows])
