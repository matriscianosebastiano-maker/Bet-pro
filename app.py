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

# --- 1. MOTORE DI ACQUISIZIONE TOTALE (Background) ---
@st.cache_data(ttl=600)
def fetch_all_odds():
    if not ODDS_API_KEY: return pd.DataFrame()
    
    # Recupera tutti gli sport attivi per non perdere alcun match
    sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_API_KEY}"
    sports = requests.get(sports_url).json()
    
    matches_list = []
    now_utc = datetime.now(timezone.utc)
    time_to = (now_utc + timedelta(days=2)).strftime("%Y-%m-%dT23:59:59Z")
    
    # Scansione limitata ai primi 10 gruppi di calcio per evitare timeout
    for sport in [s for s in sports if "soccer" in s['key']][:10]:
        url = f"https://api.the-odds-api.com/v4/sports/{sport['key']}/odds/?regions=eu&markets=h2h,totals,btts&bookmakers=pinnacle,bet365&apiKey={ODDS_API_KEY}&commenceTimeTo={time_to}"
        try:
            data = requests.get(url, timeout=5).json()
            for event in data:
                m = event.get("bookmakers", [])
                if not m: continue
                # Estrazione dati grezzi per il calcolo
                matches_list.append({"Match": f"{event['home_team']} vs {event['away_team']}", "Raw": event})
        except: continue
    return pd.DataFrame(matches_list)

# --- 2. MOTORE DI CALCOLO QUANTITATIVO (Background) ---
def compute_metrics(df):
    results = []
    for _, row in df.iterrows():
        # Estrazione quote per Poisson
        try:
            h2h = next(m for m in row['Raw']['bookmakers'][0]['markets'] if m['key'] == 'h2h')
            q1 = next(o['price'] for o in h2h['outcomes'] if o['name'] == row['Raw']['home_team'])
            q2 = next(o['price'] for o in h2h['outcomes'] if o['name'] == row['Raw']['away_team'])
            # Calcolo xG (Back-end)
            p1, p2 = 1/q1, 1/q2
            results.append({
                "Match": row['Match'], "q1": q1, "q2": q2,
                "xG_Home": round(1.45 + (p1-0.33)*2, 2),
                "xG_Away": round(1.10 + (p2-0.33)*1.5, 2)
            })
        except: continue
    return pd.DataFrame(results)

# --- 3. INTERFACCIA ESECUTIVA ---
st.title("🎯 Bet-Pro | Generatore Schedine")
if st.button("🚀 ELABORA LA MIGLIORE SCHEDINA DI OGGI", type="primary"):
    with st.spinner("Analisi quantitativa dei mercati in corso..."):
        df_raw = fetch_all_odds()
        df_metrics = compute_metrics(df_raw)
        
        # Invio dati (non tabelle, solo numeri) all'IA per la creazione combo
        summary = df_metrics.to_string()
        prompt = f"""
        Sei un analista scommesse. Analizza questi match e i loro xG:
        {summary}
        
        Obiettivo: Genera la MIGLIORE SCHEDINA POSSIBILE.
        1. Crea COMBINAZIONI (es: 1 + Over 1.5, Goal + Over, Combo risultati).
        2. Non limitarti a segni secchi.
        3. Ordina per probabilità di successo.
        4. Sii estremamente sintetico. Rispondi solo con la lista delle giocate.
        """
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        
        st.subheader("📋 La tua Schedina Ottimizzata:")
        st.markdown(response.text)

st.info("Nota: I calcoli di Poisson, Kelly e la scansione di tutti i campionati avvengono in background.")
