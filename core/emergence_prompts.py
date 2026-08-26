from core.db import get_connection

def get_prompts(role: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        if role:
            cur.execute("SELECT a.name, p.system_prompt, p.version FROM emergence.agents a JOIN emergence.agent_profiles p ON a.profile_id = p.id WHERE a.name ILIKE %s ORDER BY a.name", (role,))
        else:
            cur.execute("SELECT a.name, p.system_prompt, p.version FROM emergence.agents a JOIN emergence.agent_profiles p ON a.profile_id = p.id ORDER BY a.name")
        rows = cur.fetchall()
        return [{"name": r[0], "system_prompt": r[1], "version": r[2]} for r in rows]
    finally:
        cur.close()
        conn.close()

def update_prompt(role: str, new_prompt: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE emergence.agent_profiles p SET system_prompt = %s FROM emergence.agents a WHERE a.profile_id = p.id AND a.name ILIKE %s", (new_prompt, role))
        updated = cur.rowcount > 0
        conn.commit()
        return updated
    finally:
        cur.close()
        conn.close()