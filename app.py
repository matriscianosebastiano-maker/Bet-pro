import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="Bet-Pro | Assistente IA 100%", page_icon="📊", layout="centered")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

def run_ai_bet_analysis(user_query: str, api_key: str) -> str:
    """Utilizza Gemini con Google Search per analizzare i match e ricavare esiti probabilistici."""
    if not api_key:
        return "Errore: GEMINI_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = genai.Client(api_key=api_key.strip())
        
        prompt = f"""Sei un analista quantitativo e statistico specializzato in scommesse sportive.
Richiesta/Palinsesto utente:
"{user_query}"

Istruzioni:
1. Recupera le informazioni live e aggiornate sui match indicati (orari, stato di forma, competizioni).
2. Per OGNI partita individuata, fornisci l'analisi strutturata in Markdown:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione])
* **Contesto Tattico:** (Breve quadro statistico e di forma)
* **Classi di Esito:**
  * **Conservativa (Basso Rischio):** [Es. 1X / Doppia Chance / DNB]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Gol-NoGol / Under-Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo / Multigol preciso]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono analitico, diretto e privo di fronzoli."""

        config = types.GenerateContentConfig(
            tools=[{"google_search": {}}]
        )

        for model_id in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=config
                )
                if response and response.text:
                    return response.text
            except Exception:
                continue

        return "Errore nell'elaborazione con i modelli disponibili."

    except Exception as e:
        return f"Errore durante l'elaborazione dell'IA: {e}"


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Analista Scommesse IA")
st.caption("Sistema 100% IA autonomo. Nessun limite da API esterne, copertura globale su qualsiasi partita e coppa.")

st.subheader("Cosa vuoi analizzare oggi?")

col_a, col_b, col_c = st.columns(3)
quick_input = None

with col_a:
    if st.button("Coppa Italia Oggi", use_container_width=True):
        quick_input = "Analizza tutte le partite di Coppa Italia in programma oggi con relativi esiti e risultati esatti."
with col_b:
    if st.button("Community Shield", use_container_width=True):
        quick_input = "Analizza la partita di oggi Arsenal vs Manchester City fornendo le classi di esito e i risultati esatti."
with col_c:
    if st.button("Mix Palinsesto", use_container_width=True):
        quick_input = "Analizza le principali partite di oggi in Europa (Coppa Italia, Ligue 1, Eredivisie, Primeira Liga)."

user_input = st.text_area(
    "Oppure scrivi le partite / incolla il tuo palinsesto qui sotto:",
    value=quick_input if quick_input else "",
    placeholder="Es: Lazio vs Mantova, Genoa vs Ascoli, Frosinone vs Juve Stabia...",
    height=120
)

if st.button("Elabora Esiti con l'IA", type="primary", use_container_width=True):
    if not user_input.strip():
        st.warning("Inserisci prima un testo o seleziona una delle opzioni rapide sopra.")
    elif not GEMINI_API_KEY:
        st.error("Assicurati di aver configurato GEMINI_API_KEY nei Secrets di Streamlit.")
    else:
        with st.spinner("L'IA sta cercando i dati aggiornati ed elaborando i pronostici..."):
            result = run_ai_bet_analysis(user_input, GEMINI_API_KEY)
            st.markdown(result)
            
