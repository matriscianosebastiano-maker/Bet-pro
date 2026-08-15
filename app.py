import streamlit as st
import requests
import pandas as pd
import numpy as np
import math
from google import genai
from datetime import datetime, timezone, timedelta

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Bet-Pro | Executive Hub", page_icon="🎯", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 1. MOTORE DI ACQUISIZIONE DINAMICO TOTALE (Tutti gli sport/campionati) ---
@st.cache_data(ttl=300)
def fetch_all_available_odds(api_key):
    if not api_key:
        return pd.DataFrame()
        
    # 1. Recupera la lista completa di tutti gli sport/campionati attivi dall'API
    sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
    try:
        sports_res = requests.get(sports_url, timeout=5)
        if sports_res.status_code != 200:
            return pd.DataFrame()
        sports_data = sports_res.json()
    except:
        return pd.DataFrame()
        
    # Filtriamo solo le categorie di calcio (o espandibile ad altri sport)
    soccer_sports = [s['key'] for s in sports_data if "soccer" in s.get('key', '').lower()]
    
    matches_list = []
    now_utc = datetime.now(timezone.utc)
    time_from = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_to = (now_utc + timedelta(days=2)).strftime("%Y-%m-%dT23:59:59Z")
    
    # 2. Scansione massiva di ogni campionato di calcio trovato
    for sport_key in soccer_sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h,totals,btts&bookmakers=pinnacle,bet365&apiKey={api_key}&commenceTimeFrom={time_from}&commenceTimeTo={time_to}"
        try:
            response = requests.get(url, timeout=4)
            if response.status_code != 200:
                continue
            data = response.json()
            for event in data:
                home = event.get("home_team")
                away = event.get("away_team")
                sport_title = event.get("sport_title", "Calcio")
                bookmakers = event.get("bookmakers", [])
                if not bookmakers: continue
                markets = bookmakers[0].get("markets", [])
                
                # Estrazione quote 1X2
                h2h = next((m for m in markets if m["key"] == "h2h"), None)
                q1, qx, q2 = 0.0, 0.0, 0.0
                if h2h:
                    for o in h2h.get("outcomes", []):
                        if o["name"] == home: q1 = o["price"]
                        elif o["name"] == away: q2 = o["price"]
                        elif o["name"] == "Draw": qx = o["price"]
                
                # Estrazione quote Totals (Over/Under 2.5)
                totals = next((m for m in markets if m["key"] == "totals"), None)
                q_over = 0.0
                if totals:
                    over_o = next((o for o in totals.get("outcomes", []) if o["name"] == "Over" and o.get("point", 2.5) == 2.5), None)
                    if over_o: q_over = over_o.get("price", 0.0)

                # Estrazione quote BTTS (Goal/NoGoal)
                btts = next((m for m in markets if m["key"] == "btts"), None)
                q_goal = 0.0
                if btts:
                    yes_o = next((o for o in btts.get("outcomes", []) if o["name"] == "Yes"), None)
                    if yes_o: q_goal = yes_o.get("price", 0.0)

                if q1 > 0 and q2 > 0 and qx > 0:
                    matches_list.append({
                        "Lega": sport_title,
                        "Match": f"{home} vs {away}",
                        "Quota_1": q1,
                        "Quota_X": qx,
                        "Quota_2": q2,
                        "Q_Over": q_over,
                        "Q_Goal": q_goal
                    })
        except:
            continue
            
    return pd.DataFrame(matches_list)

def get_fallback_matches():
    return pd.DataFrame([
        {"Lega": "Serie A", "Match": "Inter vs Monza", "Quota_1": 1.35, "Quota_X": 5.25, "Quota_2": 9.00, "Q_Over": 1.70, "Q_Goal": 1.85},
        {"Lega": "Serie A", "Match": "Juventus vs Como", "Quota_1": 1.75, "Quota_X": 3.60, "Quota_2": 4.80, "Q_Over": 1.85, "Q_Goal": 1.70},
        {"Lega": "Premier League", "Match": "Manchester United vs Fulham", "Quota_1": 1.55, "Quota_X": 4.20, "Quota_2": 5.80, "Q_Over": 1.65, "Q_Goal": 1.75},
        {"Lega": "La Liga", "Match": "Villarreal vs Atletico Madrid", "Quota_1": 2.80, "Quota_X": 3.30, "Quota_2": 2.50, "Q_Over": 1.95, "Q_Goal": 1.70}
    ])

# --- 2. MODELLO MATEMATICO DI BACKGROUND (Poisson con esiti diversificati) ---
def poisson_prob(lmbda, k):
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)

def compute_background_intelligence(df):
    if df.empty: return df
    
    analyzed = []
    for _, row in df.iterrows():
        q1, qx, q2 = row['Quota_1'], row['Quota_X'], row['Quota_2']
        q_over = row['Q_Over']
        q_goal = row['Q_Goal']
        
        # Inversione quote per calcolo xG stimato
        p1, px, p2 = 1/q1, 1/qx, 1/q2
        tot_p = p1 + px + p2
        np1, npx, np2 = p1/tot_p, px/tot_p, p2/tot_p
        
        lam_h = max(0.7, 1.35 + (np1 - 0.33) * 2.0)
        lam_a = max(0.6, 1.10 + (np2 - 0.33) * 1.8)
        
        # Simulazione Poisson 6x6
        p_home, p_draw, p_away, p_over, p_btts = 0, 0, 0, 0, 0
        for h in range(6):
            for a in range(6):
                p_score = poisson_prob(lam_h, h) * poisson_prob(lam_a, a)
                if h > a: p_home += p_score
                elif h == a: p_draw += p_score
                else: p_away += p_score
                if (h + a) > 2.5: p_over += p_score
                if h > 0 and a > 0: p_btts += p_score
                
        # Logica di diversificazione esiti intelligente
        options = []
        if np1 > 0.60:
            options.append(("1 + Over 1.5 (Combo)", int(np1 * p_over * 100) + 15))
        elif np2 > 0.45:
            options.append(("Segno 2", int(np2 * 100)))
        elif abs(np1 - np2) < 0.10 and qx > 3.20:
            options.append(("Segno X (Pareggio)", int(p_draw * 100)))
        
        if q_goal > 1.65 and p_btts > 0.53:
            options.append(("Goal (BTTS)", int(p_btts * 100)))
            
        if q_over > 1.70 and p_over > 0.50:
            options.append(("Over 2.5", int(p_over * 100)))
            
        # Fallback su esito con probabilità maggiore se la lista è vuota
        if not options:
            best_p = max(np1, npx, np2)
            esito_fb = "Segno 1" if best_p == np1 else ("Segno X" if best_p == npx else "Segno 2")
            options.append((esito_fb, int(best_p * 100)))
            
        # Scegliamo l'opzione con la confidenza migliore per il match
        best_option = max(options, key=lambda x: x[1])
        
        analyzed.append({
            "Lega": row['Lega'],
            "Match": row['Match'],
            "Esito Consigliato": best_option[0],
            "Confidenza": min(92, max(45, best_option[1])),
            "xG_Casa": round(lam_h, 2),
            "xG_Ospite": round(lam_a, 2)
        })
        
    return pd.DataFrame(analyzed)

# --- 3. INTERFACCIA UTENTE ESECUTIVA ---
st.title("🎯 Bet-Pro | Generatore Schedine")
st.markdown("Scansione globale di tutti i campionati e calcoli quantitativi in background.")

if st.button("🚀 ELABORA LA MIGLIORE SCHEDINA DI OGGI", type="primary", use_container_width=True):
    with st.spinner("Scansione di tutti i campionati mondiali ed elaborazione Poisson in corso..."):
        if ODDS_API_KEY:
            df_raw = fetch_all_available_odds(ODDS_API_KEY)
            if df_raw.empty:
                df_raw = get_fallback_matches()
        else:
            df_raw = get_fallback_matches()
            
        df_processed = compute_background_intelligence(df_raw)
        
        if not df_processed.empty:
            top_picks = df_processed.sort_values(by="Confidenza", ascending=False).head(10)
            summary_str = top_picks.to_string(index=False)
            
            prompt = f"""
            Sei un algoritmo esperto di betting quantitativo. Ecco i match analizzati in background con i relativi dati xG e tipologie di scommessa diversificate:
            
            {summary_str}
            
            Genera la schedina finale ottimizzata per oggi e domani. 
            Regole tassative:
            1. Varia i pronostici (usa segni secchi, Over/Under, Goal/NoGoal e Combo differenti a seconda del match, evitati i doppioni monotoni).
            2. Fornisci direttamente la schedina pronta con quota stimata e motivazione tecnica ultrashort.
            3. Niente tabelle o formule, solo il pronostico operativo pulito in Markdown.
            """
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
            
            if response and response.text:
                st.subheader("📋 La tua Schedina Ottimizzata:")
                st.markdown(response.text)
            else:
                st.error("Errore nella generazione della risposta da parte dell'IA.")
        else:
            st.error("Nessun match disponibile al momento.")

st.info("ℹ️ I motori di calcolo (xG, Poisson e diversificazione dei mercati) operano interamente in background.")
