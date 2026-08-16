import streamlit as st
from groq import Groq

st.set_page_config(page_title="Bet-Pro | Analista Scommesse IA", page_icon="📊", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

if "prompt_text" not in st.session_state:
    st.session_state["prompt_text"] = ""


def run_ai_bet_analysis(user_query: str, api_key: str) -> str:
    """Utilizza l'API di Groq con istruzioni rigorose per tornei a eliminazione e campionati."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = Groq(api_key=api_key.strip())

        system_prompt = (
            "Sei un analista quantitativo e bookmaker professionista, specializzato in scommesse sportive. "
            "Hai una conoscenza enciclopedica del calcio mondiale, dei regolamenti dei tornei (distinguendo "
            "rigorosamente tra Coppe a eliminazione diretta/turni preliminari e campionati a girone all'italiana) "
            "e delle dinamiche di palinsesto."
        )
        
        user_prompt = f"""Richiesta o palinsesto fornito dall'utente:
"{user_query}"

Istruzioni tassative per l'analisi:
1. **Contesto Competizione:** Se l'utente menziona la Coppa Italia o altri tornei a eliminazione diretta (turni preliminari, gare secche, supplementari ed eventuali calci di rigore), trattali come MATCH DA DEDURRE O DA INTERPRETARE COME GARE SECCHE O TURNI DI COPPA, non confonderli mai con la normale Serie A o con la classifica a punti. Specifica sempre la natura della coppa.
2. **Copertura dei Match:** Analizza rigorosamente TUTTE le partite inserite o richieste nel testo dall'utente, senza saltarne nessuna. Se il palinsesto è misto (es. Coppa Italia, Ligue 1, Eredivisie, Primeira Liga), suddividi l'output chiaramente per competizione.
3. **Formato Obbligatorio in Markdown** per ogni singola partita individuata:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione esatta])
* **Contesto Tattico & Formula:** (Specifica se è gara secca, andata/ritorno, e analizza lo stato di forma)
* **Classi di Esito:**
  * **Conservativa (Basso Rischio):** [Es. Passaggio Turno / 1X / Doppia Chance / DNB]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Gol-NoGol / Under-Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo / Multigol preciso / Margine di vittoria]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono analitico, rigoroso e privo di ambiguità."""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Errore durante la chiamata a Groq: {e}"


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Analista Scommesse IA")
st.caption("Sistema 100% IA autonomo alimentato da Groq (Llama 3.3) - Modulo Anti-Allucinazione Competizioni.")

st.subheader("Cosa vuoi analizzare oggi?")

col_a, col_b, col_c = st.columns(3)

with col_a:
    if st.button("Coppa Italia Oggi", use_container_width=True):
        st.session_state["prompt_text"] = "Analizza le partite di Coppa Italia in programma oggi, trattandole correttamente come tornei a eliminazione diretta / turni ufficiali con relative quote di passaggio turno e risultati esatti."
        st.rerun()

with col_b:
    if st.button("Community Shield", use_container_width=True):
        st.session_state["prompt_text"] = "Analizza la partita Arsenal vs Manchester City o l'evento di Supercoppa/Community Shield richiesto, evidenziando la natura di trofeo in gara secca."
        st.rerun()

with col_c:
    if st.button("Mix Palinsesto", use_container_width=True):
        st.session_state["prompt_text"] = "Analizza in modo esaustivo tutte le principali partite odierne in Europa suddividendole per campionato o coppa di riferimento (Coppa Italia, Ligue 1, Eredivisie, Primeira Liga), senza tralasciare alcun match."
        st.rerun()

user_input = st.text_area(
    "Oppure scrivi le partite / incolla il tuo palinsesto qui sotto:",
    key="prompt_text",
    placeholder="Es: Incolla qui l'elenco esatto delle partite del tuo palinsesto...",
    height=120
)

if st.button("Elabora Esiti con l'IA", type="primary", use_container_width=True):
    if not user_input.strip():
        st.warning("Inserisci prima un testo o seleziona una delle opzioni rapide sopra.")
    elif not GROQ_API_KEY:
        st.error("Assicurati di aver configurato GROQ_API_KEY nei Secrets di Streamlit.")
    else:
        with st.spinner("L'IA sta elaborando l'analisi quantitativa e strutturale dei match..."):
            result = run_ai_bet_analysis(user_input, GROQ_API_KEY)
            st.markdown(result)

