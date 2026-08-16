import streamlit as st
import requests
import json

st.set_page_config(page_title="Bet-Pro | Assistente IA 100%", page_icon="📊", layout="centered")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

if "prompt_text" not in st.session_state:
    st.session_state["prompt_text"] = ""


def run_ai_bet_analysis(user_query: str, api_key: str) -> str:
    """Invia il prompt a Gemini tramite la REST API ufficiale (Interactions / v1beta)."""
    if not api_key:
        return "❌ Errore: GEMINI_API_KEY non presente nei Secrets di Streamlit."

    api_key = api_key.strip()
    
    prompt = f"""Sei un analista quantitativo e statistico specializzato in scommesse sportive.
Richiesta/Palinsesto utente:
"{user_query}"

Istruzioni:
1. Analizza i match indicati ed elabora i pronostici.
2. Per OGNI partita individuata, fornisci l'analisi strutturata in Markdown:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione])
* **Contesto Tattico:** (Breve quadro statistico e di forma)
* **Classi di Esito:**
  * **Conservativa (Basso Rischio):** [Es. 1X / Doppia Chance / DNB]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Gol-NoGol / Under-Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo / Multigol preciso]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono analitico, diretto e privo di fronzoli."""

    # Tentativo 1: Chiamata diretta v1beta con alias modello aggiornato
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        pass

    # Tentativo 2: Fallback su alias gemini-2.0-flash-exp / gemini-1.5-flash
    for alt_model in ["gemini-2.0-flash-exp", "gemini-1.5-flash"]:
        url_alt = f"https://generativelanguage.googleapis.com/v1beta/models/{alt_model}:generateContent?key={api_key}"
        try:
            res = requests.post(url_alt, headers=headers, data=json.dumps(payload), timeout=15)
            if res.status_code == 200:
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            continue

    return "❌ Errore di comunicazione con Gemini. Verifica che la chiave API sia attiva su Google AI Studio."


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Analista Scommesse IA")
st.caption("Sistema 100% IA autonomo. Nessun limite da API esterne, copertura globale su qualsiasi partita e coppa.")

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
    elif not GEMINI_API_KEY:
        st.error("Assicurati di aver configurato GEMINI_API_KEY nei Secrets di Streamlit.")
    else:
        with st.spinner("L'IA sta elaborando l'analisi quantitativa dei match..."):
            result = run_ai_bet_analysis(user_input, GEMINI_API_KEY)
            st.markdown(result)
