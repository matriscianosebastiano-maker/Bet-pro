import streamlit as st
import requests
import pandas as pd
import numpy as np
from google import genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro | Executive Hub", page_icon="🎯", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 1 & 2. ACQUISIZIONE DATI CON ORARI E LEGHE ---
@st.cache_data(ttl=300)
def fetch_market_odds(api_key):
    if not api_key:
        return pd.DataFrame()
        
    priority_leagues = [
        "soccer_italy_serie_a",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_france_ligue_1",
        "soccer_uefa_champs_league"
    ]
    
    matches_list = []
    for sport_key in priority_leagues:
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
                
                # Pulizia formato data/ora (es. 2026-08-22 16:30)
                formatted_time = commence_time.replace("T", " ")[:16] if commence_time else "Da definire"
                
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
                    "Data_Ora": formatted_time,
                    "Match": f"{home} vs {away}",
                    "Quota_1": q1,
                    "Quota_X": qx if qx > 1.0 else 3.20,
                    "Quota_2": q2,
                    "Quota_Under_2.5": totals_odds.get("Under", 1.75),
                    "Quota_Over_2.5": totals_odds.get("Over", 2.05)
                })
        except:
            continue
            
    return pd.DataFrame(matches_list)

# --- 3, 4 & 5. MODELLO MATEMATICO ---
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
            "Data_Ora": row['Data_Ora'],
            "Match": row['Match'],
            "Quota_1": q1, "Quota_X": qx, "Quota_2": q2,
            "U_2.5": row['Quota_Under_2.5'], "O_2.5": row['Quota_Over_2.5'],
            "Esito_Matematico": f"{base_pick} ({conf}%)"
        })
    return pd.DataFrame(processed)

# --- 6, 7 & 8. INTERFACCIA E SCHEDINA CON COMBO E CRONOLOGIA TEMPORALE ---
st.title("🎯 Bet-Pro | Executive Hub")
st.markdown("Piattaforma di analisi dati di mercato, quote veritiere e intelligenza predittiva.")

if st.button("🚀 AVVIA ANALISI GLOBALE E COMPILA SCHEDINA", type="primary", use_container_width=True):
    with st.spinner("Analisi cronologica e generazione combinazioni di mercato in corso..."):
        df_raw = fetch_market_odds(ODDS_API_KEY)
        
        if df_raw.empty:
            st.warning("Nessun match trovato al momento sui server.")
        else:
            df_analyzed = apply_quantitative_intelligence(df_raw)
            market_summary = df_analyzed.head(15).to_string(index=False)
            
            # Prompt ottimizzato e alleggerito per evitare timeout, con obbligo di Combo e coerenza temporale
            prompt = f"""
            Sei il risk manager di Bet-Pro. Ecco i match disponibili con data, ora e quote:
            
            {market_summary}
            
            REGOLE TASSATIVE PER LA RISPOSTA:
            1. COERENZA TEMPORALE: Seleziona gli eventi tenendo conto di quando giocano (orari e date compatibili per una schedina multipla logica).
            2. COMBO E MERCATI ALTERNATIVI: Non limitarti ai segni fissi 1X2. Per ogni match della schedina devi applicare classi di esito avanzate o COMBO obbligatorie (es. 1X + Under 3.5, X2 + Over 1.5, Goal + Over 2.5, ecc.) laddove il segno secco è rischioso.
            3. Struttura l'output in Markdown pulito mostrando: Partita, Orario, Esito Consigliato (con Combo o Doppia Chance), Quota stimata e Motivazione tecnica. Calcola la quota totale della schedina.
            """
            
            ai_output = None
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                # Utilizzo di configurazione pulita ed evitiamo payload pesanti
                response = client.models.generate_content(
                    model="gemini-3.5-flash", 
                    contents=prompt
                )
                if response and response.text:
                    ai_output = response.text
            except Exception as e:
                ai_output = None
                
            if ai_output:
                st.subheader("📋 Schedina Consigliata del Giorno (con Combo e Orari)")
                st.markdown(ai_output)
            else:
                st.error("⚠️ Si è verificato un timeout con l'API di Gemini. Riprova tra un istante a ripremere il pulsante per completare l'analisi.")
                
            st.divider()
            st.subheader("📊 Tabella Analitica Completa dei Match")
            st.dataframe(df_analyzed, use_container_width=True)

st.info("ℹ️ Il sistema si aggiorna dinamicamente a ogni nuovo caricamento della pagina.")
