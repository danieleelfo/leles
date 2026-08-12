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

# Il default di query_model (16384) basta per una singola risposta, ma qui
# la trascrizione può contenere DECINE di risposte concatenate (target_role
# ALL, molte iterazioni) — con num_ctx insufficiente Ollama tronca il
# prompt SENZA errore, e il giudice genera in base a un contesto mutilato
# (risposte quasi vuote, non un'eccezione — per questo il bug era silenzioso).
JUDGE_NUM_CTX = 32768

# ~4 caratteri per token è una stima approssimativa ma sufficiente qui: se
# la trascrizione supera comunque questa soglia anche con num_ctx alzato,
# meglio un errore chiaro che un altro giudizio silenziosamente mutilato.
MAX_TRANSCRIPT_CHARS = JUDGE_NUM_CTX * 3


def _cap_transcript(transcript_text: str) -> tuple:
    """Ritorna (testo, è_stato_troncato). Taglia dalla coda se troppo lungo per JUDGE_NUM_CTX."""
    if len(transcript_text) <= MAX_TRANSCRIPT_CHARS:
        return transcript_text, False
    return transcript_text[:MAX_TRANSCRIPT_CHARS], True


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
    judge_model="deepseek-r1",
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
    transcript_text, was_capped = _cap_transcript(transcript_text)
    if was_capped:
        logger.warning(
            f"⚠️ Trascrizione Run {run_id} troppo lunga ({len(transcript_lines)} messaggi), "
            f"troncata a {MAX_TRANSCRIPT_CHARS} caratteri per stare in JUDGE_NUM_CTX."
        )

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
4. **Conclusioni e Comportamento Emergente:** Che evoluzione o pattern è emerso analizzando questa sequenza? Quale modello é più adatto ad ogni ruolo?
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
        temperature=0.3,
        num_ctx=JUDGE_NUM_CTX,
    )

    # 1. Recupero sicuro della risposta con fallback
    report = result.get("response") if isinstance(result, dict) else None

    # 2. Controllo se la risposta dell'LLM è vuota o None
    # 'if not report' non basta: una risposta degenere tipo ' ' o '**'
    # (spazi/markdown vuoto) è truthy in Python e passerebbe indisturbata,
    # producendo un messaggio Telegram che sembra 'vuoto' senza errore.
    if not report or len(report.strip()) < 50:
        logger.error(f"❌ La chiamata a query_model per il modello {judge_model} ha restituito None o vuoto!")
        return f"❌ ERRORE: Il modello Giudice '{judge_model}' non ha generato alcuna risposta (possibile timeout API o risposta vuota)."

    if judge_participated:
        report = (
            f"⚠️ **Nota metodologica**: il giudice ({judge_model}) ha generato "
            f"alcune delle risposte analizzate in questo report — possibile "
            f"conflitto d'interesse, leggi con cautela.\n\n{report}"
        )

    return report


def get_run_scenario(run_id):
    """
    Recupera lo scenario iniziale (world_state) della run — serve per dare
    all'analisi decisionale il contesto di cosa doveva essere risolto,
    non solo la trascrizione nuda.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT world_state
        FROM emergence.iterations
        WHERE run_id = %s
        ORDER BY iteration_number ASC
        LIMIT 1;
    """, (run_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or not row[0]:
        return None

    world_state = row[0]
    return world_state.get("scenario") if isinstance(world_state, dict) else None


def analyze_decision(
    run_id,
    judge_model="deepseek-r1",
    judge_role="Analista Decisionale ed Esperto di Dinamiche di Gruppo Multi-Agente",
):
    """
    A differenza di analyze_run() (che valuta se un ruolo è stato
    interpretato bene), questa funzione estrae la CONCLUSIONE PRATICA
    raggiunta dal gruppo: quale decisione è stata presa rispetto allo
    scenario, chi l'ha guidata, con quale motivazione, e se c'è stato
    consenso reale o il gruppo si è arenato senza decidere nulla.
    """
    logger.info(f"🎯 Avvio analisi decisionale per Run ID: {run_id} | Giudice: {judge_model}")

    scenario = get_run_scenario(run_id)
    messages = get_run_messages(run_id=run_id, target_role="ALL", model_to_study="ALL")

    if not messages:
        raise ValueError(f"Nessun messaggio trovato per la Run ID {run_id}.")

    # Stessa protezione conflitto d'interesse di analyze_run()
    models_in_transcript = {msg["model_name"].lower() for msg in messages}
    judge_participated = judge_model.lower() in models_in_transcript

    conflict_warning = ""
    if judge_participated:
        conflict_warning = f"""
ATTENZIONE — CONFLITTO D'INTERESSE: il giudice ({judge_model}) ha generato
alcune delle risposte in questa trascrizione. Non essere più indulgente con
le tue stesse proposte quando valuti se una decisione è stata effettivamente
presa o solo suggerita.
"""

    transcript_lines = []
    for msg in messages:
        transcript_lines.append(
            f"[Iterazione {msg['iteration']}] {msg['agent_name']} ({msg['model_name']}):\n"
            f"{msg['response']}\n"
            f"{'-' * 40}"
        )
    transcript_text = "\n".join(transcript_lines)
    transcript_text, was_capped = _cap_transcript(transcript_text)
    if was_capped:
        logger.warning(
            f"⚠️ Trascrizione Run {run_id} troppo lunga ({len(transcript_lines)} messaggi), "
            f"troncata a {MAX_TRANSCRIPT_CHARS} caratteri per stare in JUDGE_NUM_CTX."
        )

    scenario_block = f"=== SCENARIO INIZIALE ===\n{scenario}\n" if scenario else ""

    system_prompt = f"""
Sei un {judge_role}.
{conflict_warning}
Il tuo compito NON è valutare se i ruoli sono stati interpretati bene — è
estrarre la CONCLUSIONE PRATICA raggiunta dal gruppo rispetto allo scenario
dato. Sii concreto: rispondi come se dovessi riferire a qualcuno che non ha
letto la trascrizione "cosa hanno deciso, chi, e perché".

REGOLA OBBLIGATORIA SULLE CITAZIONI: ogni affermazione su cosa è stato deciso
deve essere supportata da almeno una citazione testuale tra virgolette (max
20-25 parole) con (Iterazione N, agente). Se il gruppo NON ha raggiunto una
decisione chiara, dillo esplicitamente — non inventare un consenso che non c'è.
"""

    prompt = f"""
=== DATI ESPERIMENTO (RUN ID: {run_id}) ===
{scenario_block}
=== TRASCRIZIONE INTERAZIONI ===
{transcript_text}

=== OBIETTIVO ANALISI ===
Rispondi punto per punto:

1. **Decisione finale**: cosa ha deciso il gruppo, in una frase chiara? Se non c'è consenso, dillo.
2. **Chi ha deciso**: quale ruolo/agente ha guidato o imposto la decisione finale? Scelta condivisa o imposta da un singolo ruolo?
3. **Motivazione**: quali argomentazioni hanno portato a questa decisione? Cita i passaggi chiave.
4. **Dissenso**: qualcuno si è opposto? Con quali argomenti? Il dissenso è stato affrontato o ignorato?
5. **Coerenza con lo scenario**: la decisione risolve effettivamente il problema posto, o lo elude?
"""

    result = query_model(
        model_name=judge_model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        num_ctx=JUDGE_NUM_CTX,
    )

    report = result.get("response") if isinstance(result, dict) else None

    # 'if not report' non basta: una risposta degenere tipo ' ' o '**'
    # (spazi/markdown vuoto) è truthy in Python e passerebbe indisturbata,
    # producendo un messaggio Telegram che sembra 'vuoto' senza errore.
    if not report or len(report.strip()) < 50:
        logger.error(f"❌ query_model per {judge_model} ha restituito None o vuoto!")
        return f"❌ ERRORE: Il modello Giudice '{judge_model}' non ha generato alcuna risposta (timeout o risposta vuota)."

    if judge_participated:
        report = (
            f"⚠️ **Nota metodologica**: il giudice ({judge_model}) ha generato "
            f"alcune delle risposte analizzate — possibile conflitto d'interesse.\n\n{report}"
        )

    return report
