import streamlit as st
import requests
import pandas as pd
import numpy as np
from google import genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro | Executive Hub", page_icon="🎯", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 1 & 2. ACQUISIZIONE GLOBALE UNIFICATA (Campionati, Coppe e Trofei) ---
@st.cache_data(ttl=300)
def fetch_all_world_soccer_odds(api_key):
    if not api_key:
        return pd.DataFrame()
        
    # 1. Recuperiamo la lista di tutti gli sport/competizioni disponibili
    sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
    try:
        sports_res = requests.get(sports_url, timeout=10)
        if sports_res.status_code != 200: return pd.DataFrame()
        sports_data = sports_res.json()
    except:
        return pd.DataFrame()
    
    # Isoliamo qualsiasi chiave di competizione calcistica presente nel palinsesto mondiale
    soccer_keys = [s['key'] for s in sports_data if "soccer" in s.get('key', '').lower()]
    
    matches_list = []
    # Scandagliamo le competizioni attive (campionati, coppe nazionali, coppe internazionali e trofei)
    for sport_key in soccer_keys[:30]:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h,totals&apiKey={api_key}"
        try:
            response = requests.get(url, timeout=3)
            if response.status_code != 200: continue
            data = response.json()
            
            for event in data:
                home = event.get("home_team", "N/A")
                away = event.get("away_team", "N/A")
                sport_title = event.get("sport_title", sport_key.replace("soccer_", "").upper())
                commence_time = event.get("commence_time", "")
                
                formatted_time = commence_time.replace("T", " ")[:16] if commence_time else "In corso / Oggi"
                
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
                    "Competizione": sport_title,
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
            
    df = pd.DataFrame(matches_list)
    if not df.empty:
        df = df.sort_values(by="Data_Ora").reset_index(drop=True)
    return df

# --- 3, 4 & 5. MODELLO MATEMATICO QUANTITATIVO ---
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
            "Competizione": row['Competizione'],
            "Data_Ora": row['Data_Ora'],
            "Match": row['Match'],
            "Quota_1": q1, "Quota_X": qx, "Quota_2": q2,
            "U_2.5": row['Quota_Under_2.5'], "O_2.5": row['Quota_Over_2.5'],
            "Esito_Matematico": f"{base_pick} ({conf}%)"
        })
    return pd.DataFrame(processed)

# --- 6, 7 & 8. INTERFACCIA E SCHEDINA PROFESSIONALE ---
st.title("🎯 Bet-Pro | Executive Hub")
st.markdown("Piattaforma globale di analisi dati per campionati, coppe, trofei e intelligenza predittiva.")

if st.button("🚀 AVVIA ANALISI GLOBALE E COMPILA SCHEDINA", type="primary", use_container_width=True):
    with st.spinner("Scandagliando coppe, trofei e campionati mondiali in corso..."):
        df_raw = fetch_all_world_soccer_odds(ODDS_API_KEY)
        
        if df_raw.empty:
            st.warning("⚠️ Nessun match o coppa attiva trovata al momento sui server globali.")
        else:
            df_analyzed = apply_quantitative_intelligence(df_raw)
            market_summary = df_analyzed.head(15).to_string(index=False)
            
            prompt = f"""
            Sei il risk manager e capo analista di Bet-Pro. Ecco i match disponibili tra coppe, trofei e campionati internazionali, ordinati per data e orario con relative quote:
            
            {market_summary}
            
            DIRETTIVE OPERATIVE:
            1. COERENZA CRONOLOGICA: Costruisci una schedina multipla selezionando eventi con date e orari logicamente concatenabili.
            2. FOCUS SU COPPE E TROFEI: Dai la giusta importanza ai turni di coppa o trofei, valutando la tensione agonistica e i potenziali rischi di match bloccati.
            3. COMBO E MERCATI ALTERNATIVI OBBLIGATORI: Vietato limitarsi al segno secco 1X2 se rischioso. Per ogni match della schedina compila una COMBO o un esito alternativo professionale (es. 1X + Under 3.5, X2 + Over 1.5, Goal + Over 2.5, Under 2.5).
            4. RESTITUZIONE: Fornisci l'output pulito in Markdown indicando: Competizione, Partita, Data/Ora, Esito Consigliato (con Combo o opzione laterale), Quota stimata, Motivazione sintetica e Quota Totale della schedina.
            """
            
            ai_output = None
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(
                    model="gemini-3.5-flash", 
                    contents=prompt
                )
                if response and response.text:
                    ai_output = response.text
            except Exception:
                ai_output = None
                
            if ai_output:
                st.subheader("📋 Schedina Consigliata (Coppe, Trofei e Campionati)")
                st.markdown(ai_output)
            else:
                st.warning("⚠️ L'analisi IA ha richiesto troppo tempo. Riprova subito premendo il tasto.")
                
            st.divider()
            st.subheader("📊 Tabella Analitica Completa")
            st.dataframe(df_analyzed, use_container_width=True)

st.info("ℹ️ Il sistema si aggiorna dinamicamente a ogni nuovo caricamento della pagina.")
        
