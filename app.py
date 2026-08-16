import streamlit as st
import requests
import pandas as pd
from google import genai

st.set_page_config(page_title="Bet-Pro | Palinsesto & Classi di Esito", page_icon="📊", layout="centered")

FOOTBALL_DATA_KEY = st.secrets.get("FOOTBALL_DATA_KEY", "")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")


@st.cache_data(ttl=3600)
def fetch_football_data_matches(api_key: str):
    """Recupera le partite in programma da Football-Data.org (10 req/min)."""
    if not api_key:
        return pd.DataFrame(), "Chiave FOOTBALL_DATA_KEY non trovata nei Secrets di Streamlit."

    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": api_key.strip()}

    try:
        res = requests.get(url, headers=headers, timeout=8)

        if res.status_code in [401, 403]:
            return pd.DataFrame(), "Chiave Football-Data non valida o non autorizzata."
        if res.status_code == 429:
            return pd.DataFrame(), "Limite frequenza superato (max 10 chiamate/minuto). Attendi 60 secondi."

        res.raise_for_status()
        data = res.json()
        matches_list = data.get("matches", [])

        matches = []
        for m in matches_list:
            comp = m.get("competition", {}).get("name", "—")
            home = m.get("homeTeam", {}).get("name", "")
            away = m.get("awayTeam", {}).get("name", "")
            date_utc = (m.get("utcDate", "") or "").replace("T", " ")[:16]

            if home and away:
                matches.append({
                    "Competizione": comp,
                    "Data_Ora_UTC": date_utc,
                    "Match": f"{home} vs {away}",
                    "Stato": m.get("status", "SCHEDULED")
                })

        if not matches:
            return pd.DataFrame(), "Nessuna partita in palinsesto trovata al momento."

        df = pd.DataFrame(matches).sort_values("Data_Ora_UTC").reset_index(drop=True)
        return df, None

    except requests.RequestException as e:
        return pd.DataFrame(), f"Errore di connessione a Football-Data: {e}"


def analyze_with_ai(df_matches: pd.DataFrame, api_key: str):
    """Analizza il palinsesto e associa classi di esito e risultati esatti probabilistici."""
    client = genai.Client(api_key=api_key)
    
    prompt = f"""Sei un analista quantitativo di scommesse sportive. Analizza il seguente palinsesto di partite ufficiali:

{df_matches.to_string(index=False)}

Per OGNI partita, stima il contesto tecnico-tattico e fornisci una risposta in Markdown strutturata così:

### ⚽ [Nome Match] ([Competizione])
* **Quadro Generale:** (Breve lettura del match e forza delle squadre)
* **Classi di Esito Associate:**
  * **Conservativa (Basso Rischio):** [Es. Doppia chance / DNB / Multigol conservativo]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Goal-NoGoal / Under/Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo esito + goal / Risultato a gruppi]
* **Cluster Risultati Esatti Coerenti:** [Indica i 3 risultati esatti (es. 1-0, 2-1, 1-1) statisticamente più probabilistici].

Mantieni un tono analitico, essenziale e basato solo sulla logica calcistica."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text if response else "Nessun output dall'IA."
    except Exception as e:
        return f"Errore durante l'elaborazione IA: {e}"


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Palinsesto Football-Data")
st.caption("Recupera i match ufficiali da Football-Data.org ed elabora classi di esito con l'IA.")

if "df_matches" not in st.session_state:
    st.session_state["df_matches"] = None

col1, col2 = st.columns([3, 1])
with col1:
    if st.button("🔍 Estrai Palinsesto Ufficiale", type="primary", use_container_width=True):
        with st.spinner("Connessione a Football-Data.org..."):
            df_fetched, error = fetch_football_data_matches(FOOTBALL_DATA_KEY)
            if error:
                st.error(error)
            else:
                st.session_state["df_matches"] = df_fetched
                st.success("Palinsesto scaricato con successo!")

with col2:
    if st.button("🔄 Svuota Cache", use_container_width=True):
        st.cache_data.clear()
        st.session_state["df_matches"] = None
        st.rerun()

if st.session_state["df_matches"] is not None and not st.session_state["df_matches"].empty:
    df_m = st.session_state["df_matches"]
    
    st.subheader("📋 Match in Palinsesto")
    st.dataframe(df_m, use_container_width=True)

    st.divider()
    st.subheader("🤖 Analisi IA: Classi di Esito e Risultati")
    
    if not GEMINI_API_KEY:
        st.warning("Aggiungi `GEMINI_API_KEY` nei Secrets per abilitare l'analisi intelligente.")
    else:
        if st.button("🧠 Elabora Classi di Esito per il Palinsesto", type="primary", use_container_width=True):
            with st.spinner("Analisi in corso sulle partite..."):
                analysis_output = analyze_with_ai(df_m, GEMINI_API_KEY)
                st.markdown(analysis_output)
            
