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

# --- 1. MOTORE DI ACQUISIZIONE MULTI-SPORT (Tutti gli sport) ---
@st.cache_data(ttl=300)
def fetch_all_available_odds(api_key):
    if not api_key:
        return pd.DataFrame()
        
    sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
    try:
        sports_res = requests.get(sports_url, timeout=10)
        if sports_res.status_code != 200:
            return pd.DataFrame()
        sports_data = sports_res.json()
    except:
        return pd.DataFrame()
    
    all_sports = [s['key'] for s in sports_data if s.get('active')]
    
    matches_list = []
    for sport_key in all_sports[:15]: 
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h&apiKey={api_key}"
        try:
            response = requests.get(url, timeout=3)
            if response.status_code != 200: continue
            data = response.json()
            
            for event in data:
                home = event.get("home_team", "N/A")
                away = event.get("away_team", "N/A")
                sport_title = event.get("sport_title", "Sport")
                
                bookmakers = event.get("bookmakers", [])
                if not bookmakers: continue
                markets = bookmakers[0].get("markets", [])
                if not markets: continue
                
                outcomes = markets[0].get("outcomes", [])
                odds = {o["name"]: o["price"] for o in outcomes}
                
                q1 = odds.get(home, 0.0)
                q2 = odds.get(away, 0.0)
                qx = odds.get("Draw", 1.0) # 1.0 se lo sport non prevede il pareggio
                
                if q1 > 0 and q2 > 0:
                    matches_list.append({
                        "Lega": sport_title,
                        "Match": f"{home} vs {away}",
                        "Quota_1": q1,
                        "Quota_X": qx,
                        "Quota_2": q2,
                        "Ha_Pareggio": qx > 1.0
                    })
        except:
            continue
            
    return pd.DataFrame(matches_list)

def get_fallback_matches():
    return pd.DataFrame([
        {"Lega": "Serie A", "Match": "Inter vs Monza", "Quota_1": 1.35, "Quota_X": 5.25, "Quota_2": 9.00, "Ha_Pareggio": True},
        {"Lega": "Tennis (ATP)", "Match": "Sinner vs Alcaraz", "Quota_1": 1.75, "Quota_X": 1.0, "Quota_2": 2.10, "Ha_Pareggio": False},
        {"Lega": "NBA", "Match": "Lakers vs Celtics", "Quota_1": 1.90, "Quota_X": 1.0, "Quota_2": 1.90, "Ha_Pareggio": False}
    ])

# --- 2. MODELLO MATEMATICO DI BACKGROUND (Unificato per qualsiasi sport) ---
def compute_background_intelligence(df):
    if df.empty: return df
    
    analyzed = []
    for _, row in df.iterrows():
        q1, qx, q2 = row['Quota_1'], row['Quota_X'], row['Quota_2']
        has_draw = row['Ha_Pareggio']
        
        if has_draw:
            p1, px, p2 = 1/q1, 1/qx, 1/q2
            tot_p = p1 + px + p2
            np1, npx, np2 = p1/tot_p, px/tot_p, p2/tot_p
            
            options = []
            if np1 > 0.55:
                options.append(("Segno 1", int(np1 * 100)))
            elif np2 > 0.45:
                options.append(("Segno 2", int(np2 * 100)))
            else:
                best_p = max(np1, npx, np2)
                esito_fb = "Segno 1" if best_p == np1 else ("Segno X" if best_p == npx else "Segno 2")
                options.append((esito_fb, int(best_p * 100)))
            
            best_option = max(options, key=lambda x: x[1])
            esito = best_option[0]
            conf = min(92, max(45, best_option[1]))
        else:
            # Sport senza pareggio (Tennis, Basket, ecc.)
            p1, p2 = 1/q1, 1/q2
            tot_p = p1 + p2
            np1, np2 = p1/tot_p, p2/tot_p
            
            if np1 >= np2:
                esito = f"Vincitore: {row['Match'].split(' vs ')[0]}"
                conf = int(np1 * 100)
            else:
                esito = f"Vincitore: {row['Match'].split(' vs ')[1]}"
                conf = int(np2 * 100)
            conf = min(92, max(45, conf))
            
        analyzed.append({
            "Lega": row['Lega'],
            "Match": row['Match'],
            "Esito Consigliato": esito,
            "Confidenza": conf
        })
        
    return pd.DataFrame(analyzed)

# --- 3. INTERFACCIA UTENTE ESECUTIVA ---
st.title("🎯 Bet-Pro | Generatore Schedine Multi-Sport")
st.markdown("Scansione globale di tutti gli sport (Calcio, Tennis, Basket, ecc.) e calcoli in background.")

if st.button("🚀 ELABORA LA MIGLIORE SCHEDINA DI OGGI", type="primary", use_container_width=True):
    with st.spinner("Scansione di tutti gli sport mondiali ed elaborazione in corso..."):
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
            Sei un algoritmo esperto di betting quantitativo. Ecco i match analizzati in background (inclusi vari sport come Calcio, Tennis, Basket):
            
            {summary_str}
            
            Genera la schedina finale multi-sport ottimizzata per oggi e domani. 
            Regole tassative:
            1. Varia i pronostici e sfrutta anche gli altri sport se presenti (es. Tennis, Basket).
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

st.info("ℹ️ I motori di calcolo e la scansione multi-sport operano interamente in background.")
                
