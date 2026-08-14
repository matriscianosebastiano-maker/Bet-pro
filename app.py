import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timezone

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

# --- MOTORE MATEMATICO AVANZATO ---
@st.cache_data(ttl=600)
def fetch_advanced_odds():
    recommendations = []
    
    # Palinsesto Globale Esteso
    target_sports = [
        'soccer_italy_serie_a', 'soccer_epl', 'soccer_spain_la_liga', 'soccer_germany_bundesliga', 
        'soccer_france_ligue_one', 'soccer_uefa_champs_league', 'soccer_italy_serie_b',
        'soccer_usa_mls', 'soccer_brazil_campeonato', 'soccer_argentina_primera_division',
        'tennis_atp', 'tennis_wta', 'basketball_nba', 'baseball_mlb'
    ]
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, sport in enumerate(target_sports):
        status_text.text(f"📊 Analisi matematica in corso: {sport.replace('_', ' ').upper()}")
        progress_bar.progress((i + 1) / len(target_sports))
        
        odds_url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu,uk', 'markets': 'h2h,totals', 'oddsFormat': 'decimal'}
        
        try:
            res = requests.get(odds_url, params=params, timeout=8)
            if res.status_code == 200:
                events = res.json()
                for event in events:
                    home, away = event.get('home_team'), event.get('away_team')
                    bookmakers = event.get('bookmakers', [])
                    if not bookmakers: continue
                    
                    # Raggruppa i mercati per tipo (h2h o totals)
                    markets_dict = {}
                    for bookie in bookmakers:
                        for market in bookie.get('markets', []):
                            m_key = market['key']
                            if m_key not in markets_dict:
                                markets_dict[m_key] = []
                            markets_dict[m_key].append({'bookie': bookie['title'], 'outcomes': market['outcomes']})
                    
                    # Analizza ogni mercato
                    for market_key, bookies_data in markets_dict.items():
                        if len(bookies_data) < 2: continue # Servono almeno 2 bookies per fare media di mercato
                        
                        # Struttura per immagazzinare le quote per ogni esito
                        outcomes_data = {}
                        for bd in bookies_data:
                            for outcome in bd['outcomes']:
                                name = outcome.get('name')
                                price = float(outcome.get('price', 0))
                                if price <= 1.01: continue
                                
                                if name not in outcomes_data:
                                    outcomes_data[name] = {'prices': [], 'max_price': 0, 'max_bookie': ''}
                                
                                outcomes_data[name]['prices'].append(price)
                                if price > outcomes_data[name]['max_price']:
                                    outcomes_data[name]['max_price'] = price
                                    outcomes_data[name]['max_bookie'] = bd['bookie']
                        
                        # Calcolo Consensus True Probability (Media del mercato)
                        avg_implied_probs = {}
                        margin_sum = 0
                        for name, data in outcomes_data.items():
                            if not data['prices']: continue
                            avg_price = sum(data['prices']) / len(data['prices'])
                            implied = 1.0 / avg_price
                            avg_implied_probs[name] = implied
                            margin_sum += implied
                        
                        if margin_sum == 0: continue
                        
                        # Calcolo Valore ed Estrazione Pick
                        for name, data in outcomes_data.items():
                            if name not in avg_implied_probs: continue
                            
                            true_prob = avg_implied_probs[name] / margin_sum
                            max_price = data['max_price']
                            
                            # Calcolo Expected Value (EV)
                            ev = (max_price * true_prob) - 1
                            
                            # Filtro: teniamo tutto ciò che non è un disastro matematico (EV > -0.05) per garantire sempre opzioni
                            if ev > -0.05: 
                                # Calcolo Criterio di Kelly (Frazione di Stake)
                                kelly_fraction = max(0, ((true_prob * max_price) - 1) / (max_price - 1))
                                kelly_pct = round(kelly_fraction * 100, 2)
                                
                                recommendations.append({
                                    "Sport": sport.upper(),
                                    "Match": f"{home} vs {away}",
                                    "Mercato": market_key.upper(),
                                    "Selezione": name,
                                    "Quota Max": max_price,
                                    "Bookmaker": data['max_bookie'],
                                    "Prob Reale": f"{round(true_prob * 100, 1)}%",
                                    "EV": round(ev * 100, 2),
                                    "Kelly Stake": f"{kelly_pct}%"
                                })
                                
        except Exception as e:
            continue
            
    progress_bar.empty()
    status_text.empty()
    
    # Ordinamento per EV decrescente
    recommendations.sort(key=lambda x: x['EV'], reverse=True)
    
    # Rimuovi duplicati (stesso match, stessa selezione)
    seen = set()
    unique_recs = []
    for r in recommendations:
        identifier = f"{r['Match']}_{r['Selezione']}"
        if identifier not in seen:
            seen.add(identifier)
            unique_recs.append(r)
            
    return unique_recs[:15] # Ritorna le 15 migliori assolute

# --- UI PRINCIPALE ---
if st.button("🚀 Avvia Motore Matematico e IA", use_container_width=True, type="primary"):
    with st.spinner("Scansione globale, Line Shopping e De-vigging in corso..."):
        best_bets = fetch_advanced_odds()
        
    if not best_bets:
        st.warning("Mercato attualmente illeggibile. Riprova tra 30 minuti.")
    else:
        top_pick = best_bets[0]
        
        # --- SEZIONE TOP PICK ---
        st.markdown("---")
        st.markdown("## 🏆 TOP PICK ASSOLUTA")
        
        # Metriche in colonna per un look professionale
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Match", top_pick['Match'], top_pick['Sport'])
        col2.metric("Selezione & Quota", f"{top_pick['Selezione']} @ {top_pick['Quota Max']}", top_pick['Bookmaker'])
        col3.metric("Valore Atteso (EV)", f"+{top_pick['EV']}%" if top_pick['EV'] > 0 else f"{top_pick['EV']}%", delta_color="normal")
        col4.metric("Kelly Stake (Consigliato)", top_pick['Kelly Stake'])
        
        st.markdown("---")
        
        # --- TABELLA PALINSESTO COMPLETO ---
        st.markdown("### 📋 Palinsesto Value Bets")
        df = pd.DataFrame(best_bets[1:]) # Mostra tutte tranne la top pick che è già in alto
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # --- ANALISI IA CON CONTESTO MATEMATICO ---
        with st.spinner("L'IA sta elaborando la strategia sui dati calcolati..."):
            prompt = f"""
            Agisci come un Data Scientist specializzato in scommesse sportive. 
            Il mio algoritmo ha effettuato il de-vigging del mercato globale calcolando la probabilità reale, il valore atteso (EV) e lo stake tramite il criterio di Kelly.
            
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
