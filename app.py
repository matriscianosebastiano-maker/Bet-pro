import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timezone

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro AI Engine", page_icon="🤖", layout="centered")
st.title("🤖 Bet-Pro AI Engine")
st.markdown("Analisi EV+ e intelligenza artificiale in tempo reale.")

# --- CHIAVI API ---
try:
    ODDS_KEY = st.secrets["ODDS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-pro')
except Exception:
    st.error("⚠️ Chiavi API non configurate correttamente nei Secrets di Streamlit.")
    st.stop()

# --- MOTORE DI RICERCA DATI (Cache per non bruciare crediti) ---
@st.cache_data(ttl=600)
def fetch_odds():
    recommendations = []
    
    # Lista estesa e globale: copre Europa, Sud America, USA, Asia e vari sport (Garantisce match a qualsiasi ora)
    target_sports = [
        'soccer_italy_serie_a', 'soccer_epl', 'soccer_spain_la_liga', 
        'soccer_germany_bundesliga', 'soccer_france_ligue_one',
        'soccer_usa_mls', 'soccer_brazil_campeonato', 'soccer_argentina_primera_division',
        'soccer_mexico_ligamx', 'soccer_japan_j_league',
        'tennis_atp', 'tennis_wta', 'baseball_mlb', 'basketball_wnba'
    ]
    
    progress_text = st.empty()
    
    for sport in target_sports:
        # Aggiorna l'utente su cosa sta scansionando
        progress_text.text(f"🔍 Ricerca in corso: {sport.replace('_', ' ').upper()}...")
        
        odds_url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu,uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
        
        try:
            res = requests.get(odds_url, params=params, timeout=5)
            if res.status_code == 200:
                events = res.json()
                for event in events:
                    home, away = event.get('home_team'), event.get('away_team')
                    bookmakers = event.get('bookmakers', [])
                    if not bookmakers: continue
                    
                    markets = bookmakers[0].get('markets', [])
                    if not markets: continue
                    outcomes = markets[0].get('outcomes', [])
                    
                    if len(outcomes) < 2: continue
                    prices = [float(o.get('price', 0)) for o in outcomes if float(o.get('price', 0)) > 1.05]
                    if len(prices) < 2: continue
                    
                    margin = sum([1.0/p for p in prices])
                    for o in outcomes:
                        p = float(o.get('price', 0))
                        if p <= 1.05: continue
                        prob_real = round(((1.0/p) / margin) * 100, 1)
                        ev = round(((p * (prob_real / 100)) - 1) * 100, 2)
                        
                        # Filtro allargato: prende quote ottime e quote accettabili per non lasciare l'app vuota
                        if ev > -2.0: 
                            recommendations.append({
                                "Match": f"{home} vs {away}",
                                "Sport": sport.upper(),
                                "Pronostico": o.get('name'),
                                "Quota": p,
                                "Prob.%": prob_real,
                                "EV%": ev
                            })
        except Exception:
            continue # Se un campionato fallisce o non ha quote, passa semplicemente al prossimo
            
    progress_text.empty() # Pulisce il testo a fine ricerca
    
    # Ordina dal valore atteso più alto al più basso
    recommendations.sort(key=lambda x: x['EV%'], reverse=True)
    return recommendations[:15] # Mostra i top 15 eventi globali

# --- AZIONE PRINCIPALE ---
if st.button("🔄 Scansiona Palinsesto Globale e Genera Analisi AI", use_container_width=True):
    with st.spinner("Avvio del motore di ricerca globale..."):
        best_bets = fetch_odds()
        
    if not best_bets:
        st.warning("Nessuna quota interessante trovata in questo momento, neanche nei mercati internazionali. Riprova più tardi.")
    else:
        st.success(f"Trovate {len(best_bets)} opportunità in giro per il mondo!")
        
        # Mostra la tabella dei dati
        df = pd.DataFrame(best_bets)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # --- IL SUPER PROMPT ---
        with st.spinner("L'Intelligenza Artificiale sta scrivendo l'analisi strategica..."):
            prompt = f"""
            Agisci come un analista di betting sportivo professionista (tono serio, esperto, molto sintetico).
            Il mio software matematico ha appena scansionato il mondo e ha estratto queste quote (ordinate per Valore Atteso EV):
            {best_bets}
            
            Scrivi un'analisi di massimo 4-5 righe per l'utente. 
            Indica quale tra questi match reputi il più solido in termini di rapporto rischio/rendimento, indipendentemente dallo sport.
            Sconsiglia di giocare tutto in una singola multipla.
            Non usare formattazioni eccessive.
            """
            
            try:
                response = model.generate_content(prompt)
                st.markdown("### 🧠 Analisi Strategica dell'IA")
                st.info(response.text)
            except Exception as e:
                st.error("Errore nella generazione dell'analisi IA.")
