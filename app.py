import streamlit as st
import requests
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP ---
st.set_page_config(page_title="Bet-Pro | Intelligence", page_icon="🎯", layout="wide")
GEMINI_API_KEY = "AQ.Ab8RN6JgwZVuzMONM_Zmn_IlwL-PqY9-Sdu3Bxw8jxDNeAfBwg"

# --- 2. MOTORE DI ACQUISIZIONE DATI REALI (ESPN) ---
@st.cache_data(ttl=300)
def fetch_master_sports_data():
    matches_list = []
    
    # Endpoint reali ESPN
    endpoints = [
        {"sport": "soccer", "league": "ita.1", "name": "Serie A"},
        {"sport": "soccer", "league": "eng.1", "name": "Premier League"},
        {"sport": "soccer", "league": "esp.1", "name": "La Liga"},
        {"sport": "basketball", "league": "nba", "name": "NBA"}
    ]
    
    for ep in endpoints:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{ep['sport']}/{ep['league']}/scoreboard"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                for event in data.get("events", []):
                    match_name = event.get("name", "Match")
                    
                    # Estrazione squadre per pulizia nome
                    competitions = event.get("competitions", [{}])[0]
                    competitors = competitions.get("competitors", [])
                    home_team, away_team = "Home", "Away"
                    for c in competitors:
                        if c.get("homeAway") == "home":
                            home_team = c.get("team", {}).get("displayName", "Home")
                        elif c.get("homeAway") == "away":
                            away_team = c.get("team", {}).get("displayName", "Away")
                            
                    match_str = f"{home_team} vs {away_team}" if home_team != "Home" else match_name
                    
                    # Generazione quote simulate realistiche (da sostituire con The Odds API se hai la chiave)
                    import random
                    q1 = round(random.uniform(1.40, 3.50), 2)
                    q2 = round(random.uniform(1.80, 4.50), 2)
                    qx = round(random.uniform(2.90, 4.00), 2)
                    
                    matches_list.append({
                        "Lega": ep["name"], "Match": match_str,
                        "Quota_1": q1, "Quota_X": qx, "Quota_2": q2
                    })
        except Exception:
            continue
            
    # Fallback d'emergenza se ESPN è offline
    if not matches_list:
        matches_list = [
            {"Lega": "Serie A", "Match": "Nessun evento live ESPN", "Quota_1": 2.10, "Quota_X": 3.20, "Quota_2": 3.60}
        ]
        
    return pd.DataFrame(matches_list)

# --- 3. MOTORE MATEMATICO E KELLY ---
def calculate_market_intelligence(df):
    if df.empty: return df
    
    # Probabilità implicite
    df['Prob_1_Imp'] = 1 / df['Quota_1']
    df['Prob_X_Imp'] = 1 / df['Quota_X']
    df['Prob_2_Imp'] = 1 / df['Quota_2']
    
    # Rimozione Aggio
    total_prob = df['Prob_1_Imp'] + df['Prob_X_Imp'] + df['Prob_2_Imp']
    df['Prob_1_Norm'] = df['Prob_1_Imp'] / total_prob
    df['Prob_X_Norm'] = df['Prob_X_Imp'] / total_prob
    df['Prob_2_Norm'] = df['Prob_2_Imp'] / total_prob
    
    best_outcomes = []
    confidences = []
    kelly_stakes = []
    
    for _, row in df.iterrows():
        probs = {'1': row['Prob_1_Norm'], 'X': row['Prob_X_Norm'], '2': row['Prob_2_Norm']}
        quotes = {'1': row['Quota_1'], 'X': row['Quota_X'], '2': row['Quota_2']}
        
        best_choice = max(probs, key=probs.get)
        conf_val = probs[best_choice]
        
        # Calcolo Kelly
        p = conf_val
        quota = quotes[best_choice]
        b = quota - 1
        q = 1 - p
        
        kelly = ((b * p - q) / b) * 100 if b > 0 else 0
        kelly_pct = max(0.0, round(kelly * 0.5, 2)) # Frazionato al 50% per sicurezza
        
        best_outcomes.append(best_choice)
        confidences.append(int(conf_val * 100))
        kelly_stakes.append(kelly_pct)
        
    df['Esito Consigliato'] = best_outcomes
    df['Confidenza (%)'] = confidences
    df['Kelly Stake (%)'] = kelly_stakes
    
    return df

# --- 4. INTEGRAZIONE GEMINI AI CON FALLBACK INFALLIBILE ---
def get_gemini_market_intelligence(api_key, df_filtered):
    genai.configure(api_key=api_key)
    
    # Prepara solo i migliori 10 eventi per non confondere l'AI
    df_ai = df_filtered.sort_values(by="Confidenza (%)", ascending=False).head(10)
    market_summary = df_ai[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Esito Consigliato', 'Kelly Stake (%)']].to_string()
    
    prompt = f"""
    Agisci come un Quantitative Sports Trader. Analizza i seguenti eventi sportivi:
    
    {market_summary}
    
    1. 🎯 Analisi Esiti: Commenta le 2 migliori "Value Bet" in base alla confidenza e al Kelly Stake.
    2. ⚠️ Gestione Rischio: Dai un rapido consiglio su come frazionare il bankroll oggi.
    
    Rispondi in Markdown in modo professionale, distaccato e sintetico.
    """
    
    # TENTATIVO 1: Usa il modello aggiornato
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text, "Successo"
    except Exception as e_flash:
        # TENTATIVO 2 (PARACADUTE): Se Streamlit ha librerie vecchie, usa il modello legacy universale
        try:
            model_fallback = genai.GenerativeModel('gemini-pro')
            response = model_fallback.generate_content(prompt)
            return response.text, "Successo (Modello Base)"
        except Exception as e_pro:
            return None, f"Errore critico Gemini: {str(e_pro)}"

# --- 5. INTERFACCIA UTENTE ---
with st.sidebar:
    st.title("⚙️ Bet-Pro Settings")
    st.success("🔑 API Gemini Integrata")
    st.info("📡 Feed Reale: ESPN Global")
    st.markdown("---")
    min_conf = st.slider("Confidenza Minima Algoritmo (%)", min_value=35, max_value=80, value=45)

st.title("📊 Bet-Pro | Live Intelligence Hub")
st.markdown("Analisi del palinsesto globale con calcolo probabilità depurate dall'aggio e Kelly Stake.")

# Caricamento e filtro dati
with st.spinner("Sincronizzazione eventi dal mondo (ESPN)..."):
    df_raw = fetch_master_sports_data()
    df_analyzed = calculate_market_intelligence(df_raw)

df_filtered = df_analyzed[df_analyzed['Confidenza (%)'] >= min_conf]

# Metriche
col1, col2 = st.columns(2)
col1.metric("Match Totali Trovati", len(df_raw))
col2.metric(f"Match Validi (>{min_conf}%)", len(df_filtered))

st.subheader("📋 Palinsesto Quantitativo")
if not df_filtered.empty:
    st.dataframe(
        df_filtered[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Esito Consigliato', 'Confidenza (%)', 'Kelly Stake (%)']], 
        use_container_width=True, hide_index=True
    )
    
    st.markdown("---")
    st.subheader("🧠 Analisi Strategica Avanzata (Gemini AI)")
    
    if st.button("🚀 Interpella Gemini per Analisi Strategica", type="primary", use_container_width=True):
        with st.spinner("Elaborazione neurale delle Value Bet in corso..."):
            ai_report, status = get_gemini_market_intelligence(GEMINI_API_KEY, df_filtered)
            if ai_report:
                st.success(f"Analisi completata. ({status})")
                st.markdown(f"> {ai_report}")
            else:
                st.error(status)
else:
    st.warning("Nessun match supera la soglia di confidenza minima. Abbassa lo slider nella barra laterale.")
    
