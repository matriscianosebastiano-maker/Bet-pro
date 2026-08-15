import streamlit as st
import requests
import pandas as pd
import numpy as np
from google import genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro | Executive Hub", page_icon="🎯", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 1 & 2. ACQUISIZIONE MIRATA TOP CAMPIONATI EUROPEI & CALCIO ---
@st.cache_data(ttl=300)
def fetch_market_odds(api_key):
    if not api_key:
        return pd.DataFrame()
        
    # Elenco esplicito delle chiavi dei principali tornei europei e internazionali
    priority_leagues = [
        "soccer_italy_serie_a",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_france_ligue_1",
        "soccer_uefa_champs_league",
        "soccer_italy_serie_b",
        "soccer_efl_champ"
    ]
    
    matches_list = []
    for sport_key in priority_leagues:
        # Richiediamo i mercati h2h (1X2) e totals (Under/Over)
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h,totals&apiKey={api_key}"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code != 200: continue
            data = response.json()
            
            for event in data:
                home = event.get("home_team", "N/A")
                away = event.get("away_team", "N/A")
                sport_title = event.get("sport_title", sport_key.replace("soccer_", "").upper())
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
                
                q1 = odds_h2h.get(home, 1.80)
                q2 = odds_h2h.get(away, 1.80)
                qx = odds_h2h.get("Draw", 3.20)
                
                matches_list.append({
                    "Lega": sport_title,
                    "Orario": commence_time.replace("T", " ")[:16] if commence_time else "Oggi",
                    "Match": f"{home} vs {away}",
                    "Quota_1": q1,
                    "Quota_X": qx if qx > 1.0 else 3.20,
                    "Quota_2": q2,
                    "Quota_Under_2.5": totals_odds.get("Under", 1.75),
                    "Quota_Over_2.5": totals_odds.get("Over", 2.05),
                    "Ha_Pareggio": qx > 1.0
                })
        except:
            continue
            
    # Se per periodi di pausa estiva/soste i top campionati non hanno quote attive, facciamo un fallback sui match di calcio generali disponibili
    if not matches_list:
        fallback_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
        try:
            res = requests.get(fallback_url, timeout=5)
            if res.status_code == 200:
                all_sports = res.json()
                soccer_fallback = [s['key'] for s in all_sports if "soccer" in s.get('key', '').lower()][:5]
                for sport_key in soccer_fallback:
                    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h,totals&apiKey={api_key}"
                    resp = requests.get(url, timeout=4)
                    if resp.status_code != 200: continue
                    for event in resp.json():
                        home = event.get("home_team", "N/A")
                        away = event.get("away_team", "N/A")
                        commence_time = event.get("commence_time", "")
                        bookmakers = event.get("bookmakers", [])
                        if not bookmakers: continue
                        odds_h2h = {o["name"]: o["price"] for m in bookmakers[0].get("markets", []) if m.get("key") == "h2h" for o in m.get("outcomes", [])}
                        matches_list.append({
                            "Lega": event.get("sport_title", "Calcio Esteso"),
                            "Orario": commence_time.replace("T", " ")[:16] if commence_time else "Oggi",
                            "Match": f"{home} vs {away}",
                            "Quota_1": odds_h2h.get(home, 1.80),
                            "Quota_X": odds_h2h.get("Draw", 3.20),
                            "Quota_2": odds_h2h.get(away, 1.80),
                            "Quota_Under_2.5": 1.75,
                            "Quota_Over_2.5": 2.05,
                            "Ha_Pareggio": True
                        })
        except:
            pass

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
    with st.spinner("Scandagliando Serie A, Premier e campionati europei con modelli quantitativi..."):
        df_raw = fetch_market_odds(ODDS_API_KEY)
        
        if df_raw.empty:
            st.warning("Nessun match trovato al momento nei top campionati europei.")
        else:
            df_analyzed = apply_quantitative_intelligence(df_raw)
            market_summary = df_analyzed.head(12).to_string(index=False)
            
            # Prompt focalizzato su classi di esito alternative e gestione del rischio
            prompt = f"""
            Sei il capo analista di mercato e risk manager di Bet-Pro. Ecco i match dei principali campionati europei e italiani con relative quote e probabilità calcolate:
            
            {market_summary}
            
            Compito di ragionamento avanzato:
            1. Analizza i match con rigore matematico: se un segno 1X2 nasconde troppa incertezza o rischio, scartalo e converti la scelta su classi di esito alternative e sicure (es. Under 2.5 / Under 3.5 se la gara è bloccata, Goal/No Goal, Doppia Chance 1X o X2, oppure Combo intelligenti).
            2. Costruisci una Schedina Consigliata del Giorno bilanciata, indicando chiaramente il tipo di mercato scelto (non solo 1X2 ma anche Under/Over o DC), la quota stimata e una breve motivazione tecnica professionale.
            3. Restituisci l'output pulito e formattato in Markdown.
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
                st.subheader("📋 Schedina Consigliata del Giorno (con Mercati Alternativi)")
                st.markdown(ai_output)
            else:
                st.warning("⚠️ Servizio IA temporaneamente occupato. Ecco l'elaborazione matematica di base:")
                
            st.divider()
            st.subheader("📊 Tabella Analitica Completa dei Match")
            st.dataframe(df_analyzed, use_container_width=True)

st.info("ℹ️ Il sistema si aggiorna dinamicamente a ogni nuovo caricamento della pagina.")
    
