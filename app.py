import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro AI Engine", page_icon="🎯", layout="wide")
st.title("🎯 Bet-Pro AI Engine | Algoritmo EV+ & Kelly Criterion")
st.markdown("Motore matematico avanzato: *Consensus De-Vigging, Line Shopping e Ottimizzazione Kelly.*")

# --- CHIAVI API ---
try:
    ODDS_KEY = st.secrets["ODDS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-pro')
except Exception:
    st.error("⚠️ Chiavi API non configurate correttamente nei Secrets di Streamlit.")
    st.stop()

# --- MOTORE MATEMATICO AVANZATO E RESILIENTE ---
@st.cache_data(ttl=300)
def fetch_advanced_odds():
    recommendations = []
    
    # Lista mirata dei campionati principali ad altissima copertura dati
    target_sports = [
        'soccer_italy_serie_a', 'soccer_epl', 'soccer_spain_la_liga', 
        'soccer_germany_bundesliga', 'soccer_france_ligue_one', 
        'soccer_uefa_champs_league', 'soccer_usa_mls',
        'tennis_atp', 'basketball_nba', 'baseball_mlb'
    ]
    
    status_box = st.empty()
    
    for sport in target_sports:
        status_box.text(f"📊 Analisi flussi di quota per: {sport.replace('_', ' ').upper()}...")
        
        odds_url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu,uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
        
        try:
            res = requests.get(odds_url, params=params, timeout=6)
            
            if res.status_code == 429:
                st.warning("⚠️ Limite di richieste esaurito per The Odds API (Quota mensile superata).")
                return []
            
            if res.status_code == 200:
                events = res.json()
                for event in events:
                    home, away = event.get('home_team'), event.get('away_team')
                    bookmakers = event.get('bookmakers', [])
                    if len(bookmakers) < 2: continue # Servono almeno 2 bookmakers per il confronto di mercato
                    
                    outcomes_data = {}
                    for bookie in bookmakers:
                        b_title = bookie.get('title')
                        markets = bookie.get('markets', [])
                        for m in markets:
                            if m.get('key') == 'h2h':
                                for o in m.get('outcomes', []):
                                    name = o.get('name')
                                    price = float(o.get('price', 0))
                                    if price <= 1.01: continue
                                    
                                    if name not in outcomes_data:
                                        outcomes_data[name] = {'prices': [], 'max_price': 0, 'max_bookie': ''}
                                    
                                    outcomes_data[name]['prices'].append(price)
                                    if price > outcomes_data[name]['max_price']:
                                        outcomes_data[name]['max_price'] = price
                                        outcomes_data[name]['max_bookie'] = b_title
                    
                    # Calcolo Consensus True Probability (Media di mercato)
                    avg_implied_probs = {}
                    margin_sum = 0
                    for name, data in outcomes_data.items():
                        if not data['prices']: continue
                        avg_price = sum(data['prices']) / len(data['prices'])
                        implied = 1.0 / avg_price
                        avg_implied_probs[name] = implied
                        margin_sum += implied
                    
                    if margin_sum == 0: continue
                    
                    # Calcolo EV e Criterio di Kelly
                    for name, data in outcomes_data.items():
                        if name not in avg_implied_probs: continue
                        
                        true_prob = avg_implied_probs[name] / margin_sum
                        max_price = data['max_price']
                        if max_price == 0: continue
                        
                        ev = (max_price * true_prob) - 1
                        
                        # Soglia flessibile per intercettare opportunità di valore
                        if ev > -0.08: 
                            kelly_fraction = max(0, ((true_prob * max_price) - 1) / (max_price - 1))
                            kelly_pct = round(kelly_fraction * 100, 2)
                            
                            recommendations.append({
                                "Sport": sport.upper(),
                                "Match": f"{home} vs {away}",
                                "Mercato": "1X2 (H2H)",
                                "Selezione": name,
                                "Quota Max": max_price,
                                "Bookmaker": data['max_bookie'],
                                "Prob Reale": f"{round(true_prob * 100, 1)}%",
                                "EV": round(ev * 100, 2),
                                "Kelly Stake": f"{kelly_pct}%"
                            })
        except Exception:
            continue
            
    status_box.empty()
    
    # Ordinamento per EV decrescente
    recommendations.sort(key=lambda x: x['EV'], reverse=True)
    
    # Pulizia duplicati
    seen = set()
    unique_recs = []
    for r in recommendations:
        identifier = f"{r['Match']}_{r['Selezione']}"
        if identifier not in seen:
            seen.add(identifier)
            unique_recs.append(r)
            
    return unique_recs[:15]

# --- UI PRINCIPALE ---
if st.button("🚀 Avvia Motore Matematico e IA", use_container_width=True, type="primary"):
    with st.spinner("Scansione flussi di mercato e calcolo probabilità in corso..."):
        best_bets = fetch_advanced_odds()
        
    if not best_bets:
        st.warning("Nessuna quota disponibile o limite API raggiunto. Riprova tra qualche minuto.")
    else:
        top_pick = best_bets[0]
        
        # --- SEZIONE TOP PICK ---
        st.markdown("---")
        st.markdown("## 🏆 TOP PICK ASSOLUTA")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Match", top_pick['Match'], top_pick['Sport'])
        col2.metric("Selezione & Quota", f"{top_pick['Selezione']} @ {top_pick['Quota Max']}", top_pick['Bookmaker'])
        col3.metric("Valore Atteso (EV)", f"+{top_pick['EV']}%" if top_pick['EV'] > 0 else f"{top_pick['EV']}%")
        col4.metric("Kelly Stake (Consigliato)", top_pick['Kelly Stake'])
        
        st.markdown("---")
        
        # --- TABELLA PALINSESTO COMPLETO ---
        st.markdown("### 📋 Palinsesto Value Bets")
        if len(best_bets) > 1:
            df = pd.DataFrame(best_bets[1:])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Visualizzata la Top Pick unica disponibile al momento.")
        
        # --- ANALISI IA CON CONTESTO MATEMATICO ---
        with st.spinner("L'IA sta elaborando la strategia sui dati calcolati..."):
            prompt = f"""
            Agisci come un Data Scientist specializzato in scommesse sportive. 
            Il mio algoritmo ha effettuato il de-vigging del mercato calcolando la probabilità reale, il valore atteso (EV) e lo stake tramite il criterio di Kelly.
            
            Ecco la TOP PICK matematica in assoluto: {top_pick}
            Ecco le altre alternative valide: {best_bets[1:5]}
            
            Scrivi un brief strategico (max 5 righe):
            1. Sottolinea perché la Top Pick ha senso dal punto di vista probabilistico, menzionando i concetti di EV e Stake Kelly.
            2. Fornisci un consiglio cinico su come gestire il bankroll evitando multiple.
            Sii estremamente diretto e tecnico. Nessuna formattazione inutile.
            """
            
            try:
                response = model.generate_content(prompt)
                st.markdown("### 🧠 Analisi Strategica dell'IA (Data-Driven)")
                st.info(response.text)
            except Exception as e:
                st.error("Errore nella generazione dell'analisi IA.")
