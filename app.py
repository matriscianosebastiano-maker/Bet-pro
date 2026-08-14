import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro AI | Algorithmic Analysis", page_icon="📈", layout="wide")
st.title("📈 Bet-Pro AI | Analisi Algoritmica delle Quote Live")
st.markdown("Acquisizione dati dai principali provider europei ed elaborazione pronostici basata su calcoli matematici e probabilità.")

# --- API E CONFIG ---
try:
    ODDS_KEY = st.secrets["ODDS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"Errore Configurazione: {e}")
    st.stop()

# --- ACQUISIZIONE DATI (Senza Scraping, tramite pipeline dati ufficiale) ---
@st.cache_data(ttl=300)
def get_odds_data():
    # Questa funzione acquisisce le quote dai bookmaker che offrono le migliori linee in Europa
    url = f"https://api.the-odds-api.com/v4/sports/soccer_italy_serie_a/odds/?apiKey={ODDS_KEY}&regions=eu&markets=h2h,totals&oddsFormat=decimal"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            processed = []
            for event in data:
                home, away = event['home_team'], event['away_team']
                for bookie in event.get('bookmakers', []):
                    for market in bookie.get('markets', []):
                        for outcome in market.get('outcomes', []):
                            processed.append({
                                "Match": f"{home} vs {away}",
                                "Mercato": market['key'].upper(),
                                "Esito": outcome['name'],
                                "Quota": outcome['price']
                            })
            return pd.DataFrame(processed)
    except:
        return pd.DataFrame()
    return pd.DataFrame()

# --- ANALISI IA ---
if st.button("🚀 Acquisisci Quote ed Elabora Pronostici", use_container_width=True, type="primary"):
    with st.spinner("Acquisizione quote in corso..."):
        df = get_odds_data()
        
    if not df.empty:
        # Passiamo i dati all'IA per l'analisi algoritmica
        st.subheader("🤖 Analisi Algoritmica IA")
        with st.spinner("L'IA sta analizzando le quote e calcolando l'esito più probabile..."):
            # Prendiamo un campione per non eccedere i limiti di token
            sample = df.head(10).to_json()
            prompt = f"""
            Analizza queste quote di mercato calcistico: {sample}
            
            Per ogni match, basandoti sulla quota e sul mercato (H2H o Totals):
            1. Calcola matematicamente l'esito più probabile.
            2. Fornisci un 'Confidence Score' (da 1 a 10).
            3. Spiega brevemente il perché (es. 'Valore statistico nella quota').
            
            Rispondi solo con una tabella Markdown.
            """
            result = model.generate_content(prompt)
            st.markdown(result.text)
            
        st.subheader("📋 Dataset Acquisito")
        st.dataframe(df, use_container_width=True)
    else:
        st.error("Impossibile acquisire le quote in questo momento.")
