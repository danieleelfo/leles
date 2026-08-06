"""
core/emergence_analysis.py
==========================
Modulo per l'analisi dei risultati delle simulazioni (LLM-as-a-Judge).
Supporta il filtraggio per Ruolo (target_role), Modello (model_to_study) e la personalizzazione della Persona del Giudice.
"""

import logging
from core.db import get_connection
from core.llm import query_model

logger = logging.getLogger(__name__)


def get_run_messages(run_id, target_role="ALL", model_to_study="ALL", max_iterations=None):
    """
    Estrae dal DB i messaggi di una specifica Run, applicando i filtri per Ruolo, Modello e Iterazioni.
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

    # Filtro per Ruolo (es. 'Planner', 'Critic', 'Builder', 'Scientist', 'Observer')
    if target_role and target_role.upper() != "ALL":
        query += " AND LOWER(a.name) = LOWER(%s)"
        params.append(target_role)

    # Filtro per Modello specifico
    if model_to_study and model_to_study.upper() != "ALL":
        query += " AND LOWER(m.name) = LOWER(%s)"
        params.append(model_to_study)

    # Limite iterazioni
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


def analyze_run(
    run_id,
    target_role="ALL",
    model_to_study="ALL",
    trait_to_study="Coerenza del ruolo, capacita critica ed evoluzione delle proposte",
    max_iterations=5,
    judge_model="mistral",
    judge_role="Esperto di Sistemi Multi-Agente ed Ingegneria del Software"
):
    """
    Formatta i dati estratti e chiama l'LLM Giudice con logging trasparente di query, dati e prompt.
    """
    logger.info(f"📊 Avvio analisi per Run ID: {run_id} | Focus Ruolo: {target_role} | Giudice: {judge_model}")
    
    # 1. Estrazione dati
    messages = get_run_messages(
        run_id=run_id,
        target_role=target_role,
        model_to_study=model_to_study,
        max_iterations=max_iterations
    )

    if not messages:
        raise ValueError(f"Nessun messaggio trovato per la Run ID {run_id} con i filtri applicati.")

    # 🔍 Conflitto d'interesse: il giudice ha generato lui stesso alcune
    # delle risposte che sta per valutare? Prima non veniva mai controllato.
    models_in_transcript = {msg["model_name"].lower() for msg in messages}
    judge_participated = judge_model.lower() in models_in_transcript

    if judge_participated:
        logger.warning(
            f"⚠️ Il giudice '{judge_model}' ha generato risposte presenti in questa "
            f"trascrizione — possibile conflitto d'interesse nel giudizio."
        )

    # 🔍 LOG DEI DATI ESTRATTI
    logger.info(f"📦 Dati estratti dal DB per l'analisi ({len(messages)} messaggi trovati):")
    for msg in messages:
        logger.info(
            f"   • [Iterazione {msg['iteration']}] Agente: {msg['agent_name']} | "
            f"Modello: {msg['model_name']} | Tokens: {msg['total_tokens']} | Durata: {msg['duration_ms']}ms"
        )

    # 2. Costruzione trascrizione
    transcript_lines = []
    for msg in messages:
        transcript_lines.append(
            f"[Iterazione {msg['iteration']}] Ruolo/Agente: {msg['agent_name']} | Modello Usato: {msg['model_name']}\n"
            f"Risposta:\n{msg['response']}\n"
            f"--------------------------------------------------"
        )
    transcript_text = "\n".join(transcript_lines)

    # 3. Istruzione di Focus
    if target_role and target_role.upper() != "ALL":
        focus_instruction = f"""
STAI ANALIZZANDO ESCLUSIVAMENTE IL RUOLO: '{target_role.upper()}'.
Nella trascrizione vedrai solo gli interventi del ruolo '{target_role}', eseguiti da modelli diversi nelle varie iterazioni.
Valuta come le diverse risposte del {target_role} hanno fatto avanzare la discussione, se il ruolo è stato mantenuto coerente tra i vari modelli e quale modello ha interpretato meglio questo ruolo.
"""
    else:
        focus_instruction = "Stai analizzando l'interazione globale tra tutti i ruoli e la dinamica di gruppo."

    conflict_warning = ""
    if judge_participated:
        conflict_warning = f"""
ATTENZIONE — CONFLITTO D'INTERESSE: alcune delle risposte che stai per valutare
sono state generate da te stesso ({judge_model}), in un turno precedente di questo
stesso esperimento. Sii consapevole di questo bias potenziale: non essere
automaticamente più indulgente con le risposte del tuo stesso modello. Se noti
che le tue risposte passate hanno debolezze, dillo esplicitamente.
"""

    system_prompt = f"""
Sei un {judge_role}.
{focus_instruction}
{conflict_warning}
Il tuo compito è analizzare la trascrizione dell'esperimento fornito e produrre un report critico, rigoroso e strutturato.
Sii analitico, oggettivo e cita esempi concreti presi dalle risposte.

REGOLA OBBLIGATORIA SULLE CITAZIONI: ogni punto della tua analisi che si riferisce
a un intervento specifico deve includere almeno una citazione testuale tra
virgolette (max 20-25 parole), seguita da (Iterazione N, modello). Frasi vaghe
come "esempio: Iterazione 2 e 3" senza citazione testuale non sono accettabili.
"""

    prompt = f"""
=== DATI ESPERIMENTO (RUN ID: {run_id}) ===
Ruolo sotto analisi: {target_role}
Modello specifico sotto analisi: {model_to_study}
Carattere / Comportamento da studiare: {trait_to_study}
Iterazioni esaminate: fino alla {max_iterations}

=== TRASCRIZIONE INTERAZIONI ===
{transcript_text}

=== OBIETTIVO ANALISI ===
Fornisci un report dettagliato rispondendo ai seguenti punti:

1. **Valutazione del Carattere/Comportamento ('{trait_to_study}'):** 
   Come si sono comportati gli interventi estratti rispetto a questo parametro?
2. **Coerenza e Performance del Ruolo ('{target_role}'):** 
   Il ruolo è stato mantenuto saldamente nei vari passaggi? Se ci sono stati modelli diversi ad eseguirlo, chi ha performato meglio?
3. **Punti di Forza ed Errori Riscontrati:** Quali sono stati i passaggi più brillanti, o al contrario ridondanze, allucinazioni e stalli?
4. **Conclusioni e Comportamento Emergente:** Che evoluzione o pattern è emerso analizzando questa sequenza?
5. **Voto Complessivo (1-10):** Assegna un punteggio globale alla qualità di questi contributi.
"""

    # 🔍 LOG DEL PROMPT COMPLETO
    logger.info("\n" + "📝 " + "="*30 + " SYSTEM PROMPT " + "="*30)
    logger.info(system_prompt.strip())
    logger.info("\n" + "📄 " + "="*30 + " PROMPT INVIATO AL GIUDICE " + "="*30)
    logger.info(prompt.strip())
    logger.info("="*80 + "\n")

    logger.info(f"🧠 Invio richiesta di analisi al Giudice ({judge_model})...")
    
    result = query_model(
        model_name=judge_model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.3
    )

    # 1. Recupero sicuro della risposta con fallback
    report = result.get("response") if isinstance(result, dict) else None

    # 2. Controllo se la risposta dell'LLM è vuota o None
    if not report:
        logger.error(f"❌ La chiamata a query_model per il modello {judge_model} ha restituito None o vuoto!")
        return f"❌ ERRORE: Il modello Giudice '{judge_model}' non ha generato alcuna risposta (possibile timeout API o risposta vuota)."

    if judge_participated:
        report = (
            f"⚠️ **Nota metodologica**: il giudice ({judge_model}) ha generato "
            f"alcune delle risposte analizzate in questo report — possibile "
            f"conflitto d'interesse, leggi con cautela.\n\n{report}"
        )

    return report
