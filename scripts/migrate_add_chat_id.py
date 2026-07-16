"""
migrate_add_chat_id.py — Migration una tantum: aggiunge la colonna chat_id
alla tabella memory per isolare gli utenti di Leles tra loro.

Da lanciare UNA VOLTA sul Mac, dalla root del progetto:
    python3 -m scripts.migrate_add_chat_id

Righe esistenti restano con chat_id NULL (non isolate). Se vuoi
assegnarle retroattivamente a un chat_id specifico (es. il tuo, capitano),
passa --backfill <chat_id>.
"""

import argparse
from core.db import get_connection


def migrate(backfill_chat_id: int | None = None):
    conn = get_connection()
    cur = conn.cursor()

    print("🔧 ALTER TABLE memory ADD COLUMN chat_id...")
    cur.execute("ALTER TABLE memory ADD COLUMN IF NOT EXISTS chat_id BIGINT;")

    print("🔧 CREATE INDEX idx_memory_chat_id...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_chat_id ON memory (chat_id);")

    print("🔧 CREATE INDEX idx_memory_role_chatid...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_role_chatid ON memory (role, chat_id);")

    if backfill_chat_id is not None:
        print(f"🔧 Backfill righe NULL con chat_id={backfill_chat_id}...")
        cur.execute(
            "UPDATE memory SET chat_id = %s WHERE chat_id IS NULL;",
            (backfill_chat_id,)
        )
        print(f"   → {cur.rowcount} righe aggiornate.")

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Migration completata.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", type=int, default=None, help="chat_id a cui assegnare le righe esistenti (NULL)")
    args = parser.parse_args()
    migrate(backfill_chat_id=args.backfill)
