"""
core/emergence_analysis.py
==========================
Modulo per l'analisi dei risultati delle simulazioni (LLM-as-a-Judge).
"""

import json
import logging
from core.db import get_connection
from core.llm import query_model

logger = logging.getLogger(__name__)


def get_run_messages(run_id, model_to_study="ALL", max_iterations=None):
    """
    Estrae dal DB i messaggi di una specifica Run, con opzioni di filtraggio.
    """
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT 
            i.iteration_number,
            a.name AS agent_name,
            m.name AS model_name,
            msg.response,
            msg.duration_ms,
            msg.total_tokens
        FROM emergence.messages msg
        JOIN emergence.iterations i ON msg.iteration_id = i.id
        JOIN emergence.agents a ON msg.agent_id = a.id
        JOIN emergence.models m ON msg.model_id = m.id
        WHERE i.run_id = %s
    """
    params = [run_id]

    if model_to_study and model_to_study.upper() != "ALL":
        query += " AND m.name = %s"
        params.append(model_to_study)

    if max_iterations:
        query += " AND i.iteration_number <= %s"
        params.append(max_iterations)

    query += " ORDER BY i.iteration_number ASC, msg.id ASC;"

    cur.execute(query, params)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    messages = []
    for row in rows:
        messages.append({
            "iteration": row[0],
            "agent_name": row[1],
            "model_name": row[2],
            "response": row[3],
            "duration_ms": row[4],
            "total_tokens": row[5]
        })

    return messages


def analyze_run(run_id, model_to_study="ALL", trait_to_study="Coerenza e capacità critica",
                max_iterations=5, judge_model="gemma4"):
    """
    Formatta i dati estratti e chiama l'LLM Giudice per produrre un'analisi strutturata.
    """
    logger.info(f"📊 Avvio analisi per Run ID: {run_id}")
    
    messages = get_run_messages(run_id, model_to_study, max_iterations)

    if not messages:
        raise ValueError(f"Nessun messaggio trovato per la Run ID {run_id} con i filtri applicati.")

    # Costruzione trascrizione per il Giudice
    transcript_lines = []
    for msg in messages:
        transcript_lines.append(
            f"[Iterazione {msg['iteration']}] Agente: {msg['agent_name']} | Modello: {msg['model_name']}\n"
            f"Risposta: {msg['response']}\n"
            f"--------------------------------------------------"
        )
    transcript_text = "\n".join(transcript_lines)

    # Prompt per il Giudice
    system_prompt = """
Sei un esperto analista di sistemi multi-agente e comportamento emergente delle IA.
Il tuo compito è analizzare la trascrizione dell'esperimento fornito e produrre un report critico e strutturato.
Sii analitico, oggettivo e fornisci esempi concreti presi dalle risposte.
"""

    prompt = f"""
=== DATI ESPERIMENTO (RUN ID: {run_id}) ===
Modello sotto analisi: {model_to_study}
Carattere / Comportamento da studiare: {trait_to_study}
Iterazioni esaminate: fino alla {max_iterations}

=== TRASCRIZIONE INTERAZIONI ===
{transcript_text}

=== OBIETTIVO ANALISI ===
Fornisci un report dettagliato rispondendo ai seguenti punti:

1. **Valutazione del Carattere/Comportamento ('{trait_to_study}'):** 
   Come si sono comportati gli agenti (o il modello '{model_to_study}') rispetto a questo parametro?
2. **Coerenza con il Ruolo:** I ruoli (Planner, Scientist, Builder, Critic, Observer) sono stati mantenuti o ci sono state sovrapposizioni?
3. **Punti di Forza ed Errori Riscontrati:** Quali sono stati i passaggi più brillanti o le allucinazioni/cicli infiniti?
4. **Conclusioni ed Esercizio di Sintesi:** Che comportamento emergente è scaturito dalla simulazione?
5. **Voto Complessivo (1-10):** Assegna un punteggio alla qualità della discussione.
"""

    logger.info(f"🧠 Invio richiesta di analisi al Giudice: {judge_model}...")
    
    result = query_model(
        model_name=judge_model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.3  # Temperatura bassa per una valutazione più oggettiva
    )

    return result["response"]
