from core.db import get_connection

def get_recent_messages(limit: int = 3, role: str = None, model: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions = []
        params = []
        if role:
            conditions.append("a.name ILIKE %s")
            params.append(role)
        if model:
            conditions.append("m.name ILIKE %s")
            params.append(f"%{model}%")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        cur.execute(f"""
            SELECT a.name, m.name, i.run_id, i.iteration_number, msg.response, msg.created_at
            FROM emergence.messages msg
            JOIN emergence.agents a ON msg.agent_id = a.id
            JOIN emergence.models m ON msg.model_id = m.id
            JOIN emergence.iterations i ON msg.iteration_id = i.id
            {where_clause}
            ORDER BY msg.created_at DESC
            LIMIT %s
        """, params)
        rows = cur.fetchall()
        return [{"agent": r[0], "model": r[1], "run_id": r[2], "iteration": r[3], "response": r[4], "created_at": str(r[5])} for r in rows]
    finally:
        cur.close()
        conn.close()