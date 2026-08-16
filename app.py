import streamlit as st
import requests
import pandas as pd
from google import genai

st.set_page_config(page_title="Bet-Pro | Analisi Palinsesto", page_icon="📊", layout="centered")

FOOTBALL_DATA_KEY = st.secrets.get("FOOTBALL_DATA_KEY", "")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")


@st.cache_data(ttl=3600)
def fetch_matches(api_key: str):
    """Estrae le partite dal palinsesto di Football-Data.org."""
    if not api_key:
        return pd.DataFrame(), "Chiave FOOTBALL_DATA_KEY non configurata nei Secrets."

    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": api_key.strip()}

    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code in [401, 403]:
            return pd.DataFrame(), "Chiave API Football-Data non valida."
        if res.status_code == 429:
            return pd.DataFrame(), "Troppe richieste. Attendi 1 minuto."

        res.raise_for_status()
        matches_list = res.json().get("matches", [])

        matches = []
        for m in matches_list:
            home = m.get("homeTeam", {}).get("name", "")
            away = m.get("awayTeam", {}).get("name", "")
            if home and away:
                matches.append({
                    "Competizione": m.get("competition", {}).get("name", "—"),
                    "Data_Ora": (m.get("utcDate", "") or "").replace("T", " ")[:16],
                    "Match": f"{home} vs {away}"
                })

        if not matches:
            return pd.DataFrame(), "Nessun match in palinsesto al momento."

        return pd.DataFrame(matches).reset_index(drop=True), None

    except Exception as e:
        return pd.DataFrame(), f"Errore connessione: {e}"


def analyze_matches(df: pd.DataFrame, api_key: str):
    """Analizza il palinsesto in ingresso ed elabora gli esiti tramite IA."""
    client = genai.Client(api_key=api_key)
    
    prompt = f"""Sei un esperto di analisi sportiva. Ricevi in ingresso questo palinsesto di partite:

{df.to_string(index=False)}

Per ciascuna partita elenca gli esiti più probabili secondo questa struttura semplice:

### ⚽ [Match] ([Competizione])
* **Esito Consigliato:** [1 / X / 2 / Doppia Chance]
* **Gol / NoGol:** [Es. Gol o NoGol con motivazione sintetica]
* **Under / Over 2.5:** [Es. Over 2.5 o Under 2.5]
* **Risultato Esatto Ipotizzabile:** [Es. 2-1]
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        return response.text if response else "Nessuna risposta generata."
    except Exception as e:
        return f"Errore analisi IA: {e}"


# ---------------- INTERFACCIA ----------------

st.title("📊 Bet-Pro | Analisi Palinsesto IA")
st.caption("Estrae i match in ingresso ed elabora gli esiti attraverso l'IA.")

if "df_matches" not in st.session_state:
    st.session_state["df_matches"] = None

col1, col2 = st.columns([3, 1])
with col1:
    if st.button("🔍 Carica Palinsesto Match", type="primary", use_container_width=True):
        with st.spinner("Download palinsesto..."):
            df, err = fetch_matches(FOOTBALL_DATA_KEY)
            if err:
                st.error(err)
            else:
                st.session_state["df_matches"] = df
                st.success("Palinsesto caricato!")

with col2:
    if st.button("🔄 Reset", use_container_width=True):
        st.cache_data.clear()
        st.session_state["df_matches"] = None
        st.rerun()

if st.session_state["df_matches"] is not None and not st.session_state["df_matches"].empty:
    st.subheader("📋 Match in Ingresso")
    st.dataframe(st.session_state["df_matches"], use_container_width=True)

    st.divider()
    if not GEMINI_API_KEY:
        st.warning("Inserisci `GEMINI_API_KEY` nei Secrets per attivare l'IA.")
    else:
        if st.button("🧠 Elabora Esiti con IA", type="primary", use_container_width=True):
            with st.spinner("Elaborazione esiti in corso..."):
                res = analyze_matches(st.session_state["df_matches"], GEMINI_API_KEY)
                st.markdown(res)
                
