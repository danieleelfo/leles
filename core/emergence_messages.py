from core.db import get_connection

def get_recent_messages(limit=3, role=None, model=None, order="asc"):
    conn = get_connection()
    cur = conn.cursor()
    try:
        c=[];p=[]
        if role: c.append("a.name ILIKE %s"); p.append(role)
        if model: c.append("m.name ILIKE %s"); p.append(f"%{model}%")
        w = f"WHERE {' AND '.join(c)}" if c else ""
        p.append(limit)
        cur.execute(f"""
            SELECT a.name, m.name, i.run_id, i.iteration_number, msg.response, msg.created_at
            FROM emergence.messages msg
            JOIN emergence.agents a ON msg.agent_id=a.id
            JOIN emergence.models m ON msg.model_id=m.id
            JOIN emergence.iterations i ON msg.iteration_id=i.id
            {w} ORDER BY msg.created_at DESC LIMIT %s
        """, p)
        rows = cur.fetchall()
        result = [{"agent":r[0],"model":r[1],"run_id":r[2],"iteration":r[3],"response":r[4],"created_at":str(r[5])} for r in rows]
        if order == "asc":
            result.reverse()
        return result
    finally:
        cur.close(); conn.close()

def get_run_progress(run_id=None, limit=15):
    conn = get_connection()
    cur = conn.cursor()
    try:
        base = """
            SELECT i.run_id, i.iteration_number, a.name, m.name, msg.duration_ms, msg.created_at
            FROM emergence.messages msg
            JOIN emergence.iterations i ON msg.iteration_id=i.id
            JOIN emergence.agents a ON msg.agent_id=a.id
            JOIN emergence.models m ON msg.model_id=m.id
        """
        if run_id:
            cur.execute(base + " WHERE i.run_id=%s ORDER BY i.iteration_number ASC, msg.created_at ASC", (run_id,))
        else:
            cur.execute(base + " ORDER BY msg.created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        return [{"run_id":r[0],"iteration":r[1],"agent":r[2],"model":r[3],"duration_ms":r[4],"created_at":str(r[5])} for r in rows]
    finally:
        cur.close(); conn.close()