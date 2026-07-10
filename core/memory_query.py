from core.memoryPG import load_memory, get_memory_by_id_db

def get_all_memory():
    return load_memory().split("\n")


def get_memory_by_id(mem_id):
    try:
        mem_id_int = int(mem_id)
    except (TypeError, ValueError):
        return None

    return get_memory_by_id_db(mem_id_int)


def search_memory(keyword, limit=5):
    memory = get_all_memory()

    results = []
    for line in memory:
        if keyword.lower() in line.lower():
            results.append(line)

    return results[-limit:]
