import streamlit as st
import requests
import pandas as pd
import numpy as np
from google import genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro | Executive Hub", page_icon="🎯", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 1 & 2. ACQUISIZIONE DATI MIRATA (Calcio Europeo, Italiano & Altri) ---
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
    
    # Selezioniamo in modo mirato il calcio (dando priorità a campionati europei e internazionali)
    soccer_sports = [s['key'] for s in sports_data if "soccer" in s.get('key', '').lower()]
    
    matches_list = []
    # Scandagliamo fino a 12 leghe calcistiche per trovare match disponibili
    for sport_key in soccer_sports[:12]:
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
                totals_odds = {}
                for m in bookmakers[0].get("markets", []):
                    if m.get("key") == "h2h":
                        odds_h2h = {o["name"]: o["price"] for o in m.get("outcomes", [])}
                    elif m.get("key") == "totals":
                        for o in m.get("outcomes", []):
                            if o.get("point") == 2.5:
                                totals_odds[o["name"]] = o["price"]
                
                q1 = odds_h2h.get(home, 1.8)
                q2 = odds_h2h.get(away, 1.8)
                qx = odds_h2h.get("Draw", 3.0)
                
                matches_list.append({
                    "Lega": sport_title,
                    "Orario": commence_time.replace("T", " ")[:16] if commence_time else "Oggi",
                    "Match": f"{home} vs {away}",
                    "Quota_1": q1,
                    "Quota_X": qx if qx > 1.0 else 3.0,
                    "Quota_2": q2,
                    "Quota_Under_2.5": totals_odds.get("Under", 1.70),
                    "Quota_Over_2.5": totals_odds.get("Over", 2.00),
                    "Ha_Pareggio": qx > 1.0
                })
        except:
            continue
            
    return pd.DataFrame(matches_list)

# --- 3, 4 & 5. MODELLO MATEMATICO DI BACKGROUND ---
def apply_quantitative_intelligence(df):
    if df.empty: return df
    processed = []
    for _, row in df.iterrows():
        q1, qx, q2 = row['Quota_1'], row['Quota_X'], row['Quota_2']
        p1, px, p2 = 1/q1, 1/qx, 1/q2
        tot = p1 + px + p2
        np1, npx, np2 = p1/tot, px/tot, p2/tot
        
        max_p = max(np1, npx, np2)
        if max_p == np1:
            base_pick, conf = "1", int(np1 * 100)
        elif max_p == npx:
            base_pick, conf = "X", int(npx * 100)
        else:
            base_pick, conf = "2", int(np2 * 100)
            
        conf = min(90, max(45, conf))
        processed.append({
            "Lega": row['Lega'],
            "Orario": row['Orario'],
            "Match": row['Match'],
            "Quota_1": q1, "Quota_X": qx, "Quota_2": q2,
            "U_2.5": row['Quota_Under_2.5'], "O_2.5": row['Quota_Over_2.5'],
            "Esito_Matematico_1X2": f"{base_pick} ({conf}%)"
        })
    return pd.DataFrame(processed)

# --- 6, 7 & 8. INTERFACCIA E RAGIONAMENTO AVANZATO DELL'IA ---
st.title("🎯 Bet-Pro | Executive Hub")
st.markdown("Piattaforma di analisi dati di mercato, quote veritiere e intelligenza predittiva.")

if st.button("🚀 AVVIA ANALISI GLOBALE E COMPILA SCHEDINA", type="primary", use_container_width=True):
    with st.spinner("Elaborazione dati e simulazione scenari tattici in corso..."):
        df_raw = fetch_market_odds(ODDS_API_KEY)
        
        if df_raw.empty:
            st.warning("Nessun match calcistico disponibile al momento sui server delle quote.")
        else:
            df_analyzed = apply_quantitative_intelligence(df_raw)
            market_summary = df_analyzed.head(12).to_string(index=False)
            
            # Prompt avanzato per spingere l'IA a ragionare su classi di esito alternative e combo
            prompt = f"""
            Sei il capo analista di mercato e risk manager di Bet-Pro. Ecco i match di calcio con relative quote di mercato (1X2, Under/Over 2.5) e probabilità estratte in background:
            
            {market_summary}
            
            Compito di ragionamento avanzato:
            1. Analizza ogni match: se un segno 1X2 secco risulta troppo rischioso o incerto, valuta e proponi classi di esito alternative più sicure o intelligenti (es. Under/Over 1.5 o 3.5, Goal/No Goal, Doppia Chance 1X o X2, oppure Combo studiate).
            2. Costruisci una Schedina Consigliata del Giorno bilanciata e professionale, motivando brevemente per ogni match la scelta dell'esito (spiegando perché si è optato ad esempio per un Under anziché un 2 rischioso).
            3. Restituisci tutto pulito e formattato in Markdown.
            """
            
            ai_output = None
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(model="gemini-3.5-flash", contents=prompt)
                if response and response.text:
                    ai_output = response.text
            except Exception:
                ai_output = None
                
            if ai_output:
                st.subheader("📋 Schedina Consigliata del Giorno (con Analisi Esiti Alternativi)")
                st.markdown(ai_output)
            else:
                st.warning("⚠️ Servizio IA temporaneamente occupato. Ecco l'elaborazione matematica di base:")
                
            st.divider()
            st.subheader("📊 Tabella Analitica Completa dei Match")
            st.dataframe(df_analyzed, use_container_width=True)

st.info("ℹ️ Il sistema si aggiorna dinamicamente a ogni nuovo caricamento della pagina.")
