"""
telegram_notify.py — Manda il risultato di un task/DAG Airflow su Telegram,
come ultimo step di qualsiasi pipeline. Riusabile: non è specifico a
emergence_full_pipeline, qualsiasi DAG può importare notify_telegram()
e usarla come callable di un PythonOperator finale.

Setup:
    Metti questo file in dags/utils/telegram_notify.py (o dove preferisci,
    basta che sia importabile dai tuoi DAG file).

    Nel .env di Airflow (o come Airflow Variable/Connection, se preferisci
    non usare .env), servono:
        TELEGRAM_BOT_TOKEN   — stesso token del bot di Leles
        TELEGRAM_CHAT_ID     — il tuo chat_id (8733881519)

Uso tipico in un DAG:

    from utils.telegram_notify import notify_telegram

    def _send_result(**context):
        # Prendi il risultato dal task precedente via XCom
        result = context["ti"].xcom_pull(task_ids="run_llm_judge_analysis")
        notify_telegram(f"✅ Analisi completata:\n\n{result}")

    notify_task = PythonOperator(
        task_id="notify_telegram",
        python_callable=_send_result,
    )

    # nel grafo del DAG:
    analysis_task >> notify_task
"""

import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8733881519")  # il tuo chat_id di default

TELEGRAM_MAX_CHARS = 4000  # margine di sicurezza sotto il limite reale (4096)


def _split_message(text: str, max_len: int = TELEGRAM_MAX_CHARS) -> list:
    """Spezza un testo lungo in più blocchi, tagliando su un a-capo quando possibile."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_len:
        cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def notify_xcom_result(
    context: dict,
    source_dag_id: str,
    source_task_id: str,
    trigger_task_id: str,
    header: str = "✅ Pipeline completata",
    chat_id: str = None,
) -> bool:
    """
    Recupera il risultato di un task dentro un DAG lanciato via
    TriggerDagRunOperator e lo manda su Telegram — riusabile da QUALSIASI
    pipeline che segue il pattern trigger -> wait_for_completion -> leggi
    XCom, non solo emergence_full_pipeline.

    TriggerDagRunOperator non ripropaga mai l'XCom del DAG che triggera:
    pusha solo il proprio 'trigger_run_id' (l'id del DagRun creato). Per
    leggere il risultato vero serve un secondo xcom_pull, mirato su quel
    run_id specifico — stesso pattern già usato per incatenare
    trigger_simulation_dag -> trigger_analysis_dag nel DAG.

    Uso in un PythonOperator:

        def _notify(**context):
            notify_xcom_result(
                context,
                source_dag_id="emergence_lab_analysis",
                source_task_id="run_llm_judge_analysis",
                trigger_task_id="trigger_analysis_dag",
                header="✅ Pipeline Emergence completata",
            )

        notify_task = PythonOperator(
            task_id="notify_telegram_result",
            python_callable=_notify,
        )

    Ritorna True se il messaggio è stato inviato (anche come avviso di
    XCom mancante) — non solleva mai eccezioni verso il DAG chiamante.
    """
    ti = context["ti"]

    run_id = ti.xcom_pull(task_ids=trigger_task_id, key="trigger_run_id")
    if not run_id:
        return notify_telegram(
            f"⚠️ {header}, ma non sono riuscito a recuperare il run_id "
            f"del DAG triggerato da '{trigger_task_id}'.",
            chat_id=chat_id,
        )

    result = ti.xcom_pull(task_ids=source_task_id, dag_id=source_dag_id, run_id=run_id)
    if result is None:
        return notify_telegram(
            f"⚠️ {header}, ma XCom vuoto per il task '{source_task_id}' "
            f"(dag={source_dag_id}, run={run_id}).",
            chat_id=chat_id,
        )

    return notify_telegram(f"{header}:\n\n{result}", chat_id=chat_id)
    """
    Manda `text` alla chat Telegram indicata (o TELEGRAM_CHAT_ID di default),
    spezzandolo in più messaggi se supera il limite di caratteri invece di
    troncarlo. Pensata per essere chiamata da un PythonOperator come ultimo
    step di un DAG — non solleva mai eccezioni: se la notifica fallisce,
    logga l'errore ma non fa fallire il task Airflow che l'ha chiamata
    (un DAG che ha fatto il suo lavoro non dovrebbe segnare 'failed' solo
    perché Telegram era irraggiungibile).

    Ritorna True se tutti i pezzi sono stati inviati con successo.
    """
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN non impostato — notifica saltata.")
        return False

    target_chat_id = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    chunks = _split_message(text)
    total = len(chunks)
    all_ok = True

    for i, chunk in enumerate(chunks, start=1):
        prefix = f"[{i}/{total}]\n" if total > 1 else ""
        try:
            response = requests.post(
                url,
                json={"chat_id": target_chat_id, "text": prefix + chunk},
                timeout=15,
            )
            if response.status_code != 200:
                print(f"⚠️ Telegram ha risposto {response.status_code}: {response.text[:200]}")
                all_ok = False
        except Exception as e:
            print(f"⚠️ Errore inviando notifica Telegram: {e}")
            all_ok = False

    return all_ok
