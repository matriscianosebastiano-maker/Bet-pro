import streamlit as st
import requests
import pandas as pd

# --- 1. SETUP E CONFIGURAZIONE ---
st.set_page_config(page_title="Bet-Pro | Intelligence", page_icon="🎯", layout="wide")

# Chiave Gemini di default (puoi lasciarla o fargliela inserire dalla sidebar)
DEFAULT_GEMINI_KEY = "AQ.Ab8RN6JgwZVuzMONM_Zmn_IlwL-PqY9-Sdu3Bxw8jxDNeAfBwg"

# --- 2. MOTORE DI ACQUISIZIONE QUOTE REALI (THE ODDS API) ---
@st.cache_data(ttl=300)
def fetch_real_odds_data(api_key):
    """Scarica le quote reali (1X2) da The Odds API."""
    if not api_key:
        return pd.DataFrame() # Ritorna vuoto se manca la chiave
        
    url = f"https://api.the-odds-api.com/v4/sports/upcoming/odds/?regions=eu&markets=h2h&bookmakers=pinnacle,bet365&apiKey={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame()
            
        data = response.json()
        matches_list = []
        
        for event in data:
            # Filtriamo solo calcio per coerenza (puoi rimuovere questo if per tutti gli sport)
            if "soccer" not in event.get("sport_key", ""):
                continue
                
            home_team = event.get("home_team")
            away_team = event.get("away_team")
            bookmakers = event.get("bookmakers", [])
            
            if not bookmakers: continue
            
            # Prendiamo il primo bookmaker disponibile per le quote
            markets = bookmakers[0].get("markets", [])
            h2h_market = next((m for m in markets if m["key"] == "h2h"), None)
            
            if h2h_market:
                outcomes = h2h_market.get("outcomes", [])
                
                # Estrazione quote sicura
                q1, qx, q2 = 0.0, 0.0, 0.0
                for outcome in outcomes:
                    if outcome["name"] == home_team: q1 = outcome["price"]
                    elif outcome["name"] == away_team: q2 = outcome["price"]
                    elif outcome["name"] == "Draw": qx = outcome["price"]
                
                if q1 > 0 and q2 > 0 and qx > 0:
                    matches_list.append({
                        "Lega": event.get("sport_title", "Calcio"),
                        "Match": f"{home_team} vs {away_team}",
                        "Quota_1": q1,
                        "Quota_X": qx,
                        "Quota_2": q2
                    })
                    
        return pd.DataFrame(matches_list)
        
    except Exception as e:
        return pd.DataFrame()

def generate_fallback_data():
    """Genera dati realistici di fallback se l'API non è configurata."""
    return pd.DataFrame([
        {"Lega": "Serie A", "Match": "Inter vs Monza", "Quota_1": 1.35, "Quota_X": 5.25, "Quota_2": 9.00},
        {"Lega": "Serie A", "Match": "Juventus vs Como", "Quota_1": 1.40, "Quota_X": 4.80, "Quota_2": 8.50},
        {"Lega": "Premier League", "Match": "Arsenal vs Aston Villa", "Quota_1": 1.75, "Quota_X": 3.90, "Quota_2": 4.50},
        {"Lega": "Serie A", "Match": "Napoli vs Roma", "Quota_1": 2.10, "Quota_X": 3.40, "Quota_2": 3.60}
    ])

# --- 3. MOTORE MATEMATICO (VIGORISH E KELLY) ---
def calculate_market_intelligence(df):
    if df.empty: return df
    
    # 1. Calcolo Probabilità Implicite
    df['Prob_1_Imp'] = 1 / df['Quota_1']
    df['Prob_X_Imp'] = 1 / df['Quota_X']
    df['Prob_2_Imp'] = 1 / df['Quota_2']
    
    # 2. Rimozione Aggio (Vigorish)
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
        
        # L'esito consigliato è quello con la probabilità matematica più alta
        best_choice = max(probs, key=probs.get)
        conf_val = probs[best_choice]
        
        # Calcolo Criterio di Kelly
        p = conf_val
        quota = quotes[best_choice]
        b = quota - 1
        q = 1 - p
        
        kelly = ((b * p - q) / b) * 100 if b > 0 else 0
        kelly_pct = max(0.0, round(kelly * 0.25, 2)) # Frazionato al 25% per un bankroll management difensivo
        
        best_outcomes.append(best_choice)
        confidences.append(int(conf_val * 100))
        kelly_stakes.append(kelly_pct)
        
    df['Esito Algoritmo'] = best_outcomes
    df['Confidenza (%)'] = confidences
    df['Kelly Stake (%)'] = kelly_stakes
    
    return df

# --- 4. CONNESSIONE GEMINI REST API CORRETTA ---
def get_gemini_market_intelligence(api_key, df_filtered):
    # Prepara la stringa di dati per l'IA
    df_ai = df_filtered.sort_values(by="Confidenza (%)", ascending=False).head(8)
    market_summary = df_ai[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Esito Algoritmo', 'Kelly Stake (%)']].to_string(index=False)
    
    prompt = f"""
    Agisci come un analista quantitativo di scommesse sportive. 
    Analizza queste partite processate con quote reali e Criterio di Kelly:
    
    {market_summary}
    
    Compiti:
    1. Evidenzia le 2 migliori selezioni dal punto di vista del rapporto rischio/rendimento.
    2. Spiega brevemente la logica matematica dietro queste scelte.
    
    Rispondi in Markdown, sii diretto, professionale e analitico.
    """
    
    # FIX: Utilizzo dell'endpoint corretto per evitare l'errore 404
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            testo = data['candidates'][0]['content']['parts'][0]['text']
            return testo, "Successo"
        else:
            return None, f"Errore API Server: {response.status_code} - {response.text}"
            
    except Exception as e:
        return None, f"Errore di Connessione: {str(e)}"

# --- 5. INTERFACCIA UTENTE ---
with st.sidebar:
    st.title("⚙️ Bet-Pro Config")
    st.markdown("---")
    
    st.subheader("Chiavi API")
    gemini_key_input = st.text_input("Gemini API Key", value=DEFAULT_GEMINI_KEY, type="password")
    odds_key_input = st.text_input("The Odds API Key", placeholder="Inserisci la chiave per dati reali", type="password")
    
    if odds_key_input:
        st.success("🟢 Feed Reale: The Odds API")
    else:
        st.warning("🟡 Feed: Dati Mockup Realistici")
        
    st.markdown("---")
    st.subheader("Filtri Quantitativi")
    min_conf = st.slider("Confidenza Minima (%)", min_value=30, max_value=85, value=45)

st.title("📊 Bet-Pro | Live Intelligence Hub")
st.markdown("Elaborazione quote reali con calcolo probabilità depurate dall'aggio e gestione Bankroll.")

# Generazione/Acquisizione Dati
with st.spinner("Acquisizione e calcolo quote di mercato..."):
    if odds_key_input:
        df_raw = fetch_real_odds_data(odds_key_input)
        if df_raw.empty:
            st.error("Errore nel download da The Odds API. Verifica la chiave. Carico dati di fallback.")
            df_raw = generate_fallback_data()
    else:
        df_raw = generate_fallback_data()
        
    df_analyzed = calculate_market_intelligence(df_raw)

# Filtro
df_filtered = df_analyzed[df_analyzed['Confidenza (%)'] >= min_conf]

# Layout Statistiche
col1, col2, col3 = st.columns(3)
col1.metric("Match Analizzati", len(df_raw))
col2.metric(f"Match Validi (>{min_conf}%)", len(df_filtered))
if not df_filtered.empty:
    col3.metric("Max Kelly Stake", f"{df_filtered['Kelly Stake (%)'].max()}%")

st.markdown("---")
st.subheader("📋 Palinsesto Elaborato")

if not df_filtered.empty:
    st.dataframe(
        df_filtered[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Esito Algoritmo', 'Confidenza (%)', 'Kelly Stake (%)']], 
        use_container_width=True, 
        hide_index=True
    )
    
    st.markdown("---")
    st.subheader("🧠 Interrogazione Motore AI")
    
    if st.button("🚀 Avvia Analisi Strategica (Gemini 1.5 Flash)", type="primary", use_container_width=True):
        if not gemini_key_input:
            st.error("Inserisci la chiave API di Gemini nella barra laterale.")
        else:
            with st.spinner("Elaborazione neurale in corso..."):
                ai_report, status = get_gemini_market_intelligence(gemini_key_input, df_filtered)
                if ai_report:
                    st.success(f"Analisi completata via REST API. ({status})")
                    st.markdown(f"> {ai_report}")
                else:
                    st.error(status)
else:
    st.warning("Nessun match supera i parametri quantitativi attuali. Abbassa la confidenza o attendi nuovi eventi.")
    
