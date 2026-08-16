import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Bet-Pro | Assistente IA 100%", page_icon="📊", layout="centered")

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")

if "prompt_text" not in st.session_state:
    st.session_state["prompt_text"] = ""


def run_ai_bet_analysis(user_query: str, api_key: str) -> str:
    """Utilizza l'API di OpenAI per elaborare l'analisi quantitativa dei match."""
    if not api_key:
        return "❌ Errore: OPENAI_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = OpenAI(api_key=api_key.strip())

        system_prompt = """Sei un analista quantitativo e statistico specializzato in scommesse sportive.
Il tuo compito è analizzare i match forniti ed elaborare pronostici probabilistici strutturati."""

        user_prompt = f"""Richiesta/Palinsesto utente:
"{user_query}"

Istruzioni:
1. Analizza le partite e fornisci per ognuna una scheda tecnica in formato Markdown.
2. Usa esattamente la seguente struttura per ogni partita:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione])
* **Contesto Tattico:** (Breve quadro statistico e di forma)
* **Classi di Esito:**
  * **Conservativa (Basso Rischio):** [Es. 1X / Doppia Chance / DNB]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Gol-NoGol / Under-Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo / Multigol preciso]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono analitico, diretto e privo di fronzoli."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Errore durante la chiamata a OpenAI: {e}"


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Analista Scommesse IA")
st.caption("Sistema 100% IA autonomo alimentato da OpenAI GPT-4o-mini.")

st.subheader("Cosa vuoi analizzare oggi?")

col_a, col_b, col_c = st.columns(3)

with col_a:
    if st.button("Coppa Italia Oggi", use_container_width=True):
        st.session_state["prompt_text"] = "Analizza tutte le partite di Coppa Italia in programma oggi con relativi esiti e risultati esatti."
        st.rerun()

with col_b:
    if st.button("Community Shield", use_container_width=True):
        st.session_state["prompt_text"] = "Analizza la partita di oggi Arsenal vs Manchester City fornendo le classi di esito e i risultati esatti."
        st.rerun()

with col_c:
    if st.button("Mix Palinsesto", use_container_width=True):
        st.session_state["prompt_text"] = "Analizza le principali partite di oggi in Europa (Coppa Italia, Ligue 1, Eredivisie, Primeira Liga)."
        st.rerun()

user_input = st.text_area(
    "Oppure scrivi le partite / incolla il tuo palinsesto qui sotto:",
    key="prompt_text",
    placeholder="Es: Lazio vs Mantova, Genoa vs Ascoli, Frosinone vs Juve Stabia...",
    height=120
)

if st.button("Elabora Esiti con l'IA", type="primary", use_container_width=True):
    if not user_input.strip():
        st.warning("Inserisci prima un testo o seleziona una delle opzioni rapide sopra.")
    elif not OPENAI_API_KEY:
        st.error("Assicurati di aver configurato OPENAI_API_KEY nei Secrets di Streamlit.")
    else:
        with st.spinner("L'IA sta elaborando l'analisi quantitativa dei match..."):
            result = run_ai_bet_analysis(user_input, OPENAI_API_KEY)
            st.markdown(result)
            
