"""
export_agent.py

Export Agent per Lelé.

Comandi supportati:

    esporta 1963
    esporta id 1963
    esporta ruolo gemma
    esporta ruolo gemma ultime 10
    esporta cerca horror
    esporta cerca horror ultime 20
    esporta ultime 50
    esporta file <percorso>          # <-- NUOVO
    export file <percorso>          # <-- NUOVO

Output:
    YAML (per comandi memoria)
    Testo (per file)

Nota tecnica: usa core.memoryPG.load_memory_structured() invece delle
funzioni stringa in core.memory_query (get_all_memory / get_memory_by_id /
search_memory). Quelle lavorano su righe "ROLE: content" già appiattite,
che non portano l'id reale della riga DB e rendono il filtro per ruolo
inaffidabile (r["role"] su una stringa esplode). load_memory_structured
ritorna dict {id, role, content, created_at}, quindi tutti i comandi qui
sotto lavorano su dati veri, non su testo parsato a mano.
"""

import os
import re
import yaml

from core.memoryPG import load_memory_structured

# Finestra di ricerca per "cerca"/"ruolo": quante righe recenti scansionare
# prima di applicare il filtro. Se in futuro il DB cresce molto e serve
# cercare più indietro, alza questo valore (o passa a una query SQL con
# WHERE invece del filtro Python).
SEARCH_WINDOW = 200

def _read_file(filepath: str) -> str:
    """Legge il contenuto di un file e lo restituisce come stringa."""
    if not os.path.exists(filepath):
        return f"❌ File non trovato: {filepath}"

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        return f"❌ Errore lettura file {filepath}: {e}"

def _yaml(data):
    return yaml.dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

def export_agent(command: str) -> str:

    cmd = command.lower().strip()

    # ==========================================================
    # NUOVO: esporta file <percorso> / export file <percorso>
    # ==========================================================

    m = re.match(r"esporta\s+file\s+(.+)$", cmd)
    if m:
        filepath = m.group(1).strip()
        content = _read_file(filepath)
        return f"📄 {filepath}:\n\n{content}"

    m = re.match(r"export\s+file\s+(.+)$", cmd)
    if m:
        filepath = m.group(1).strip()
        content = _read_file(filepath)
        return f"📄 {filepath}:\n\n{content}"

    # ==========================================================
    # Comandi esistenti (INVARIATI)
    # ==========================================================

    # esporta 1963
    # esporta id 1963
    m = re.match(r"esporta(?:\\s+id)?\\s+(\\d+)$", cmd)
    if m:
        mem_id = int(m.group(1))
        rows = load_memory_structured(limit=SEARCH_WINDOW)
        result = next((r for r in rows if r["id"] == mem_id), None)
        if not result:
            return "❌ ID non trovato."
        return _yaml(result)

    # esporta cerca horror
    # esporta cerca horror ultime 10
    m = re.match(
        r"esporta\\s+cerca\\s+(.+?)(?:\\s+ultime\\s+(\\d+))?$",
        cmd,
    )
    if m:
        keyword = m.group(1).strip()
        limit = int(m.group(2)) if m.group(2) else 9999
        rows = load_memory_structured(limit=SEARCH_WINDOW)
        results = [r for r in rows if keyword in r["content"].lower()]
        return _yaml(results[-limit:])

    # esporta ultime 20
    m = re.match(r"esporta\\s+ultime\\s+(\\d+)$", cmd)
    if m:
        limit = int(m.group(1))
        rows = load_memory_structured(limit=limit)
        return _yaml(rows)

    # esporta ruolo gemma
    # esporta ruolo gemma ultime 10
    m = re.match(
        r"esporta\\s+ruolo\\s+(\\w+)(?:\\s+ultime\\s+(\\d+))?$",
        cmd,
    )
    if m:
        role = m.group(1).upper()
        limit = int(m.group(2)) if m.group(2) else 9999
        rows = load_memory_structured(limit=SEARCH_WINDOW)
        results = [r for r in rows if r["role"].upper().startswith(role)]
        return _yaml(results[-limit:])

    return (
        "Comandi disponibili:\n\n"
        "esporta id 1963\n"
        "esporta ruolo gemma ultime 10\n"
        "esporta cerca horror\n"
        "esporta ultime 20\n"
        "esporta file <percorso>\n"  # <-- NUOVO
        "export file <percorso>"   # <-- NUOVO
    )
