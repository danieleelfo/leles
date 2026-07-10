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

Output:
    YAML
"""

import re
import yaml

from core.memory_query import (
    get_all_memory,
    get_memory_by_id,
    search_memory,
)

from core.memoryPG import load_memory_by_suffix


def _yaml(data):
    return yaml.dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def export_agent(command: str) -> str:

    cmd = command.lower().strip()

    # ---------------------------------------------------------
    # esporta 1963
    # esporta id 1963
    # ---------------------------------------------------------

    m = re.match(r"esporta(?:\s+id)?\s+(\d+)$", cmd)

    if m:
        mem_id = m.group(1)

        result = get_memory_by_id(mem_id)

        if not result:
            return "❌ ID non trovato."

        return _yaml(result)

    # ---------------------------------------------------------
    # esporta cerca horror
    # esporta cerca horror ultime 10
    # ---------------------------------------------------------

    m = re.match(
        r"esporta\s+cerca\s+(.+?)(?:\s+ultime\s+(\d+))?$",
        cmd,
    )

    if m:

        keyword = m.group(1).strip()
        limit = int(m.group(2) or 9999)

        rows = search_memory(keyword)

        return _yaml(rows[:limit])

    # ---------------------------------------------------------
    # esporta ultime 20
    # ---------------------------------------------------------

    m = re.match(r"esporta\s+ultime\s+(\d+)", cmd)

    if m:

        limit = int(m.group(1))

        rows = get_all_memory()

        return _yaml(rows[-limit:])

    # ---------------------------------------------------------
    # esporta ruolo gemma
    # esporta ruolo gemma ultime 10
    # ---------------------------------------------------------

    m = re.match(
        r"esporta\s+ruolo\s+(\w+)(?:\s+ultime\s+(\d+))?$",
        cmd,
    )

    if m:

        role = m.group(1).upper()
        limit = int(m.group(2) or 9999)

        rows = get_all_memory()

        rows = [
            r
            for r in rows
            if r["role"].startswith(role)
        ]

        rows = rows[-limit:]

        return _yaml(rows)

    return (
        "Comandi disponibili:\n\n"
        "esporta id 1963\n"
        "esporta ruolo gemma ultime 10\n"
        "esporta cerca horror\n"
        "esporta ultime 20"
    )
