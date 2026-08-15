import streamlit as st
import requests
import pandas as pd
import numpy as np
from google import genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro | Executive Hub", page_icon="🎯", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 1 & 2. ACQUISIZIONE DATI MULTI-SPORT DA THE ODDS API ---
@st.cache_data(ttl=300)
def fetch_market_odds(api_key):
    if not api_key:
        return pd.DataFrame()
        
    sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
    try:
        sports_res = requests.get(sports_url, timeout=10)
        if sports_res.status_code != 200: return pd.DataFrame()
        sports_data = sports_res.json()
    except:
        return pd.DataFrame()
    
    soccer_sports = [s['key'] for s in sports_data if "soccer" in s.get('key', '').lower()]
    other_sports = [s['key'] for s in sports_data if any(x in s.get('key', '').lower() for x in ['basketball', 'tennis']) and s.get('active')]
    selected_sports = soccer_sports[:6] + other_sports[:2]
    
    matches_list = []
    for sport_key in selected_sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h,totals&apiKey={api_key}"
        try:
            response = requests.get(url, timeout=4)
            if response.status_code != 200: continue
            data = response.json()
            
            for event in data:
                home = event.get("home_team", "N/A")
                away = event.get("away_team", "N/A")
                sport_title = event.get("sport_title", "Sport")
                commence_time = event.get("commence_time", "")
                
                bookmakers = event.get("bookmakers", [])
                if not bookmakers: continue
                
                odds_h2h = {}
                for m in bookmakers[0].get("markets", []):
                    if m.get("key") == "h2h":
                        odds_h2h = {o["name"]: o["price"] for o in m.get("outcomes", [])}
                
                q1 = odds_h2h.get(home, 1.5)
                q2 = odds_h2h.get(away, 1.5)
                qx = odds_h2h.get("Draw", 0.0)
                
                matches_list.append({
                    "Lega": sport_title,
                    "Orario": commence_time.replace("T", " ")[:16] if commence_time else "Oggi",
                    "Match": f"{home} vs {away}",
                    "Quota_1": q1,
                    "Quota_X": qx if qx > 0 else 1.0,
                    "Quota_2": q2,
                    "Ha_Pareggio": qx > 0
                })
        except:
            continue
            
    return pd.DataFrame(matches_list)

# --- 3, 4 & 5. MOTORE DI CALCOLO QUANTITATIVO ---
def apply_quantitative_intelligence(df):
    if df.empty: return df
    processed = []
    for _, row in df.iterrows():
        q1, qx, q2 = row['Quota_1'], row['Quota_X'], row['Quota_2']
        has_draw = row['Ha_Pareggio']
        
        if has_draw:
            p1, px, p2 = 1/q1, 1/qx, 1/q2
            tot = p1 + px + p2
            np1, npx, np2 = p1/tot, px/tot, p2/tot
            max_p = max(np1, npx, np2)
            if max_p == np1:
                esito, conf = "1 (Fisso)", int(np1 * 100)
            elif max_p == npx:
                esito, conf = "X (Pareggio)", int(npx * 100)
            else:
                esito, conf = "2 (Fisso)", int(np2 * 100)
        else:
            p1, p2 = 1/q1, 1/q2
            tot = p1 + p2
            np1, np2 = p1/tot, p2/tot
            if np1 >= np2:
                esito, conf = f"1 ({row['Match'].split(' vs ')[0]})", int(np1 * 100)
            else:
                esito, conf = f"2 ({row['Match'].split(' vs ')[1]})", int(np2 * 100)
                
        conf = min(92, max(50, conf))
        processed.append({
            "Lega": row['Lega'],
            "Orario": row['Orario'],
            "Match": row['Match'],
            "Esito_Consigliato": esito,
            "Confidenza": f"{conf}%"
        })
    return pd.DataFrame(processed)

# --- 6, 7 & 8. INTERFACCIA E GESTIONE SICURA DEGLI ERRORI SERVER ---
st.title("🎯 Bet-Pro | Executive Hub")
st.markdown("Piattaforma di analisi dati di mercato, quote veritiere e intelligenza predittiva.")

if st.button("🚀 AVVIA ANALISI GLOBALE E COMPILA SCHEDINA", type="primary", use_container_width=True):
    with st.spinner("Elaborazione dati e interrogazione modelli in corso..."):
        df_raw = fetch_market_odds(ODDS_API_KEY)
        
        if df_raw.empty:
            st.warning("Nessun match live trovato al momento. Riprova più tardi.")
        else:
            df_analyzed = apply_quantitative_intelligence(df_raw)
            market_summary = df_analyzed.head(10).to_string(index=False)
            
            prompt = f"""
            Sei il risk manager di Bet-Pro. Analizza questi match calcolati in background:
            {market_summary}
            Crea una Schedina Consigliata del Giorno bilanciata, indicando quote stimate e brevi motivazioni tecniche in Markdown.
            """
            
            ai_output = None
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(model="gemini-3.5-flash", contents=prompt)
                if response and response.text:
                    ai_output = response.text
            except Exception as e:
                ai_output = None  # Gestione silenziata del ServerError per evitare blocchi dell'app
                
            if ai_output:
                st.subheader("📋 Schedina Consigliata del Giorno")
                st.markdown(ai_output)
            else:
                st.warning("⚠️ Servizio IA temporaneamente occupato. Ecco comunque l'elaborazione quantitativa automatica dei match:")
                
            st.divider()
            st.subheader("📊 Tabella Analitica Completa dei Match")
            st.dataframe(df_analyzed, use_container_width=True)

st.info("ℹ️ Il sistema si aggiorna dinamicamente a ogni nuovo caricamento della pagina.")
