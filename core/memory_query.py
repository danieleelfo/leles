from core.memoryPG import load_memory

def get_all_memory():
    return load_memory().split("\n")


def get_memory_by_id(mem_id):
    memory = get_all_memory()

    for line in memory:
        if f"id {mem_id}" in line:
            return line

    return None


def search_memory(keyword, limit=5):
    memory = get_all_memory()

    results = []
    for line in memory:
        if keyword.lower() in line.lower():
            results.append(line)

    return results[-limit:]
