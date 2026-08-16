import streamlit as st
from groq import Groq

st.set_page_config(page_title="Bet-Pro | Analista Scommesse IA", page_icon="📊", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

if "prompt_text" not in st.session_state:
    st.session_state["prompt_text"] = ""


def run_ai_bet_analysis(user_query: str, api_key: str) -> str:
    """Utilizza l'API di Groq applicando l'analisi quantitativa rigorosa sui match reali forniti."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = Groq(api_key=api_key.strip())

        system_prompt = (
            "Sei un analista quantitativo e bookmaker professionista, specializzato in scommesse sportive. "
            "Il tuo compito è elaborare pronostici statistici e quote basandoti ESATTAMENTE e unicamente sui match "
            "forniti dall'utente, trattando correttamente le coppe come partite a eliminazione diretta (gara secca)."
        )
        
        user_prompt = f"""Palinsesto reale fornito dall'utente:
"{user_query}"

Istruzioni tassative:
1. Analizza **esclusivamente** le partite elencate nel testo sopra, senza aggiungerne altre o confonderle con la Serie A.
2. Per ciascuna partita, fornisci la scheda tecnica in formato Markdown:

### [Squadra Casa] vs [Squadra Ospite]
* **Contesto Tattico & Formula:** (Analisi di forma e specificando che trattasi di gara a eliminazione diretta)
* **Classi di Esito:**
  * **Conservativa (Basso Rischio):** [Es. Passaggio Turno / 1X / Doppia Chance]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Gol-NoGol / Under-Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo / Risultato con scarto]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono rigoroso, professionale e privo di invenzioni."""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Errore durante la chiamata a Groq: {e}"


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Analista Scommesse IA")
st.caption("Sistema di analisi quantitativa mirata su palinsesto reale.")

st.subheader("Incolla o seleziona il palinsesto ufficiale:")

# Pulsante rapido pre-compilato con le partite reali estratte dalla tua ricerca Google
if st.button("Carica Partite Coppa Italia di Oggi (Frosinone, Genoa, Lazio)", use_container_width=True):
    st.session_state["prompt_text"] = "Frosinone vs Juve Stabia (Coppa Italia), Genoa vs Ascoli (Coppa Italia), Lazio vs Mantova (Coppa Italia)"
    st.rerun()

user_input = st.text_area(
    "Partite da analizzare (modificabili a piacimento):",
    key="prompt_text",
    placeholder="Es: Frosinone vs Juve Stabia, Genoa vs Ascoli, Lazio vs Mantova...",
    height=100
)

if st.button("Elabora Analisi Statistica", type="primary", use_container_width=True):
    if not user_input.strip():
        st.warning("Inserisci o seleziona le partite da analizzare.")
    elif not GROQ_API_KEY:
        st.error("Configura GROQ_API_KEY nei Secrets di Streamlit.")
    else:
        with st.spinner("Elaborazione quote e scenari tattici in corso..."):
            result = run_ai_bet_analysis(user_input, GROQ_API_KEY)
            st.markdown(result)
