import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro AI Engine Pro", page_icon="📈", layout="wide")
st.title("📈 Bet-Pro AI Engine | Analisi Globale Full Market")
st.markdown("Analisi massiva di tutti gli eventi quotati. Il motore processa i dati aggregati dai principali provider europei (incluso il segmento Eurobet-equivalent).")

# --- CHIAVI API ---
try:
    ODDS_KEY = st.secrets["ODDS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"⚠️ Errore di configurazione API: {e}")
    st.stop()

# --- MOTORE DI ANALISI MASSIVA ---
@st.cache_data(ttl=300)
def fetch_full_market_data():
    all_events = []
    
    # Lista estesa di mercati per copertura totale
    try:
        sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_KEY}"
        res_sports = requests.get(sports_url, timeout=5)
        active_sports = [s['key'] for s in res_sports.json() if s.get('active', True)]
    except:
        active_sports = ['soccer_epl', 'soccer_italy_serie_a', 'soccer_spain_la_liga', 'basketball_nba']

    # Scansione mercati (h2h = 1X2, spreads = Handicap, totals = Under/Over)
    target_markets = 'h2h,spreads,totals'
    
    for sport in active_sports[:20]: # Aumentato range per coprire più eventi
        odds_url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': target_markets, 'oddsFormat': 'decimal'}
        
        try:
            res = requests.get(odds_url, params=params, timeout=10)
            if res.status_code == 200:
                events = res.json()
                for event in events:
                    home, away = event.get('home_team'), event.get('away_team')
                    for bookie in event.get('bookmakers', []):
                        for m in bookie.get('markets', []):
                            m_type = m.get('key')
                            for o in m.get('outcomes', []):
                                all_events.append({
                                    "Sport": sport,
                                    "Match": f"{home} vs {away}",
                                    "Mercato": m_type,
                                    "Selezione": o.get('name'),
                                    "Quota": o.get('price'),
                                    "Punto": o.get('point', 'N/A')
                                })
        except: continue
        
    return pd.DataFrame(all_events)

# --- UI E LOGICA IA ---
if st.button("🚀 Avvia Scansione Massiva Totale", use_container_width=True, type="primary"):
    with st.spinner("Indicizzazione di tutti i mercati e calcolo probabilità in corso..."):
        df = fetch_full_market_data()
        
    if not df.empty:
        st.success(f"Analizzati {len(df)} mercati sportivi attivi.")
        
        # Filtro per l'utente
        st.subheader("📊 Selezione Eventi per Analisi IA")
        
        # Prendiamo un campione rappresentativo per l'analisi IA per non sovraccaricare il token limit
        sample_data = df.head(15).to_string() 
        
        with st.spinner("L'IA sta elaborando i pronostici per i mercati rilevati..."):
            prompt = f"""
            Analizza i seguenti dati di scommesse (Quote e Mercati) e fornisci un pronostico per ciascuno:
            
            Dati:
            {sample_data}
            
            Per ogni riga, genera una tabella con:
            1. Evento
            2. Selezione (Mercato)
            3. Analisi IA (es. 'Alta probabilità', 'Quota di valore', 'Rischio elevato')
            4. Esito Previsto (Sintetico)
            
            Rispondi in formato Tabella Markdown.
            """
            
            response = model.generate_content(prompt)
            st.markdown("### 🤖 Pronostici & Analisi Esiti dell'IA")
            st.markdown(response.text)
            
            st.divider()
            st.subheader("Tutti i Dati Mercato")
            st.dataframe(df, use_container_width=True)
            
    else:
        st.warning("Nessun dato disponibile.")
