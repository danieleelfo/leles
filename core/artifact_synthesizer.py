"""
core/artifact_synthesizer.py
============================
Modulo per la sintesi finale della simulazione e generazione dei file in AI_TMP.
Prende i frammenti sparsi dalle iterazioni e ricompone file completi.
"""

import os
import re
import logging
from core.db import get_connection
from core.llm import query_model

logger = logging.getLogger(__name__)


def get_full_run_transcript(run_id: int) -> str:
    """Estrae l'intera trascrizione cronologica della simulazione."""
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT 
            i.iteration_number,
            a.name AS agent_name,
            m.name AS model_name,
            msg.response
        FROM emergence.messages msg
        JOIN emergence.iterations i ON msg.iteration_id = i.id
        JOIN emergence.agents a ON msg.agent_id = a.id
        JOIN emergence.models m ON msg.model_id = m.id
        WHERE i.run_id = %s
        ORDER BY i.iteration_number ASC, msg.id ASC;
    """
    cur.execute(query, (run_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    lines = []
    for r in rows:
        lines.append(f"[Iterazione {r[0]}] {r[1]} ({r[2]}):\n{r[3]}\n" + "-"*40)
    return "\n".join(lines)


def parse_and_save_artifacts(llm_response: str, output_dir: str = "AI_TMP") -> list:
    """
    Analizza l'output del Synthesizer, estrae i blocchi di codice marcati
    e li salva come file fisici e completi nella cartella target.
    """
    os.makedirs(output_dir, exist_ok=True)
    saved_files = []

    # Regex robusta: tollera spazi, apici facoltativi e varianti di maiuscole/minuscole
    # Esempio supportato: === FILE: src/main.py === ```python ... ```
    pattern = r"===\s*FILE:\s*['\"]?([^\s'\"]+)['\"]?\s*===\s*```(?:\w+)?\n(.*?)```"
    matches = re.findall(pattern, llm_response, re.DOTALL | re.IGNORECASE)

    if matches:
        for filename, code in matches:
            filename = filename.strip()
            filepath = os.path.join(output_dir, filename)
            
            # Crea eventuali sottocartelle (es. AI_TMP/src/utils.py)
            parent_dir = os.path.dirname(filepath)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code.strip() + "\n")
            
            saved_files.append(filepath)
            logger.info(f"💾 File salvato con successo: {filepath}")
    else:
        # Fallback: Se il modello non usa il tag preciso, salviamo l'intera sintesi in un file markdown
        fallback_path = os.path.join(output_dir, "final_synthesis.md")
        with open(fallback_path, "w", encoding="utf-8") as f:
            f.write(llm_response)
        saved_files.append(fallback_path)
        logger.warning(f"⚠️ Impossibile parsing automatico dei singoli file. Salvata sintesi globale in: {fallback_path}")

    return saved_files


def generate_final_artifacts(
    run_id: int,
    model_name: str = "qwen2.5",
    output_dir: str = "AI_TMP"
) -> str:
    """
    Task orchestratore per la produzione degli artefatti finali.
    """
    logger.info(f"🚀 Avvio Generazione Artefatti Finali per Run ID: {run_id}")
    
    transcript = get_full_run_transcript(run_id)
    if not transcript:
        raise ValueError(f"Nessun dato trovato per la Run ID {run_id}")

    system_prompt = """
Sei il Lead Software Engineer e Integratore Finale di un team multi-agente.
Il tuo unico compito è prendere l'intera discussione avvenuta tra Planner, Builder, Critic e Observer, 
risolvere le criticità emerse e produrre i FILE DI CODICE FINALI E COMPLETI.

REGOLE TASSATIVE DI FORMATTAZIONE OUTPUT:
1. NON produrre spezzoni di codice, diff o placeholder come `# ... resto del codice invariato ...`.
2. Ogni file deve essere INTEGRALE, AUTONOMO e pronto per l'esecuzione.
3. Per OGNI file che crei o modifichi, DEVI usare ESATTAMENTE questo formato:

=== FILE: nome_file.ext ===
```lingua
// codice completo da riga 1 alla fine
        Esempio:
        === FILE: app/main.py ===
        ```python
        def main():
            print("Sistema avviato con successo")

        if __name__ == "__main__":
            main()
        ```
        """

    prompt = f"""
=== TRASCRIZIONE DISCUSSIONE TEAM (RUN ID: {run_id}) ===
{transcript}

=== OBIETTIVO ===
Basandoti su tutti i suggerimenti, refactoring e correzioni proposti dal team nelle varie iterazioni, 
sintetizza il lavoro e genera la versione DEFINITIVA dei file di progetto.
"""

    logger.info(f"🧠 Generazione codice finale in corso tramite il modello {model_name}...")
    
    result = query_model(
        model_name=model_name,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.2
    )

    llm_response = result["response"]

    print("\n" + "="*80)
    print(f"📦 ARTEFATTI FINALI GENERATI DALL'INTEGRATORE (RUN {run_id})")
    print("="*80)
    print(llm_response)
    print("="*80 + "\n")

    saved_files = parse_and_save_artifacts(llm_response, output_dir=output_dir)
    
    return f"Generazione completata. File creati in '{output_dir}': {saved_files}"
