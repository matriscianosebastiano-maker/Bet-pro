import streamlit as st
import requests
import pandas as pd
import numpy as np
import math
from google import genai
from datetime import datetime, timezone, timedelta

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Bet-Pro | Executive Hub", page_icon="🎯", layout="centered")
# Assicurati di avere GEMINI_API_KEY e ODDS_API_KEY configurati nei tuoi st.secrets
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 1. MOTORE DI ACQUISIZIONE BILANCIATO ---
@st.cache_data(ttl=300)
def fetch_all_available_odds(api_key):
    if not api_key: return pd.DataFrame()
        
    sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
    try:
        sports_res = requests.get(sports_url, timeout=10)
        sports_data = sports_res.json() if sports_res.status_code == 200 else []
    except: return pd.DataFrame()
    
    # Priorità: Calcio (soccer) + Altri sport popolari
    soccer_sports = [s['key'] for s in sports_data if "soccer" in s.get('key', '').lower()]
    other_sports = [s['key'] for s in sports_data if any(x in s.get('key', '').lower() for x in ['basketball', 'tennis']) and s.get('active')]
    
    selected_sports = soccer_sports[:10] + other_sports[:3]
    
    matches_list = []
    for sport_key in selected_sports: 
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h&apiKey={api_key}"
        try:
            response = requests.get(url, timeout=4)
            if response.status_code != 200: continue
            data = response.json()
            for event in data:
                home, away = event.get("home_team"), event.get("away_team")
                bookmakers = event.get("bookmakers", [])
                if not bookmakers: continue
                odds = {o["name"]: o["price"] for o in bookmakers[0]["markets"][0]["outcomes"]}
                
                matches_list.append({
                    "Lega": event.get("sport_title"),
                    "Match": f"{home} vs {away}",
                    "Quota_1": odds.get(home, 0.0),
                    "Quota_X": odds.get("Draw", 1.0),
                    "Quota_2": odds.get(away, 0.0),
                    "Ha_Pareggio": "Draw" in odds
                })
        except: continue
    return pd.DataFrame(matches_list)

# --- 2. LOGICA DI CALCOLO BACKEND ---
def compute_background_intelligence(df):
    if df.empty: return df
    analyzed = []
    for _, row in df.iterrows():
        q1, qx, q2 = row['Quota_1'], row['Quota_X'], row['Quota_2']
        if row['Ha_Pareggio']:
            p1, px, p2 = 1/q1, 1/qx, 1/q2
            tot = p1 + px + p2
            best_p = max(p1/tot, px/tot, p2/tot)
            esito = "Segno 1" if p1/tot == best_p else ("Segno X" if px/tot == best_p else "Segno 2")
        else:
            p1, p2 = 1/q1, 1/q2
            best_p = max(p1/(p1+p2), p2/(p1+p2))
            esito = f"Vincitore: {row['Match'].split(' vs ')[0] if p1/(p1+p2) == best_p else row['Match'].split(' vs ')[1]}"
        
        analyzed.append({
            "Lega": row['Lega'], "Match": row['Match'],
            "Esito": esito, "Confidenza": int(best_p * 100)
        })
    return pd.DataFrame(analyzed)

# --- 3. INTERFACCIA E OUTPUT ---
st.title("🎯 Bet-Pro | Executive Hub")
if st.button("🚀 ELABORA LA MIGLIORE SCHEDINA", type="primary", use_container_width=True):
    with st.spinner("Analisi quantitativa in corso..."):
        df_raw = fetch_all_available_odds(ODDS_API_KEY)
        df_processed = compute_background_intelligence(df_raw)
        
        if not df_processed.empty:
            prompt = f"Analizza questi match e crea la schedina ottimizzata: {df_processed.to_string(index=False)}. Includi esiti combinati, sii sintetico e professionale."
            
            # Modello stabile gemini-1.5-flash
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            
            st.subheader("📋 Schedina Ottimizzata:")
            st.markdown(response.text)
        else:
            st.error("Nessun dato disponibile.")
            
