import streamlit as st
import requests
import pandas as pd

# --- 1. SETUP E CONFIGURAZIONE ---
st.set_page_config(page_title="Bet-Pro | Intelligence", page_icon="🎯", layout="wide")

DEFAULT_GEMINI_KEY = "AQ.Ab8RN6JgwZVuzMONM_Zmn_IlwL-PqY9-Sdu3Bxw8jxDNeAfBwg"

# --- 2. MOTORE DI ACQUISIZIONE ESTESO (1X2, UNDER/OVER, HANDICAP) ---
@st.cache_data(ttl=300)
def fetch_real_odds_data(api_key):
    """Scarica quote 1X2, Spread (Handicap) e Totals (Under/Over) da The Odds API."""
    if not api_key:
        return pd.DataFrame()
        
    # Richiediamo esplicitamente h2h (1X2), spreads (handicap) e totals (under/over)
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?regions=eu&markets=h2h,spreads,totals&bookmakers=pinnacle,bet365&apiKey={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame()
            
        data = response.json()
        matches_list = []
        
        for event in data:
            home_team = event.get("home_team")
            away_team = event.get("away_team")
            bookmakers = event.get("bookmakers", [])
            
            if not bookmakers: continue
            markets = bookmakers[0].get("markets", [])
            
            # 1. Estrazione Mercato 1X2 (H2H)
            h2h = next((m for m in markets if m["key"] == "h2h"), None)
            q1, qx, q2 = 0.0, 0.0, 0.0
            if h2h:
                for o in h2h.get("outcomes", []):
                    if o["name"] == home_team: q1 = o["price"]
                    elif o["name"] == away_team: q2 = o["price"]
                    elif o["name"] == "Draw": qx = o["price"]
            
            # 2. Estrazione Mercato Under/Over (Totals - es. Linea 2.5)
            totals = next((m for m in markets if m["key"] == "totals"), None)
            over_val, under_val, over_price, under_price = "N/A", "N/A", 0.0, 0.0
            if totals:
                for o in totals.get("outcomes", []):
                    if o["name"] == "Over":
                        over_val = f"O {o.get('point', 2.5)}"
                        over_price = o.get("price", 0.0)
                    elif o["name"] == "Under":
                        under_val = f"U {o.get('point', 2.5)}"
                        under_price = o.get("price", 0.0)

            # 3. Estrazione Mercato Handicap (Spreads)
            spreads = next((m for m in markets if m["key"] == "spreads"), None)
            handicap_str = "N/A"
            if spreads:
                # Prendiamo la linea di spread della squadra di casa come riferimento principale
                home_spread = next((o for o in spreads.get("outcomes", []) if o["name"] == home_team), None)
                if home_spread:
                    point = home_spread.get("point", 0)
                    price = home_spread.get("price", 0)
                    handicap_str = f"{home_team} ({point}) @ {price}"

            if q1 > 0 and q2 > 0 and qx > 0:
                matches_list.append({
                    "Lega": event.get("sport_title", "Calcio"),
                    "Match": f"{home_team} vs {away_team}",
                    "Quota_1": q1,
                    "Quota_X": qx,
                    "Quota_2": q2,
                    "Under/Over Principale": f"{over_val} ({over_price})" if over_price > 0 else "N/A",
                    "Handicap": handicap_str
                })
                    
        return pd.DataFrame(matches_list)
        
    except Exception as e:
        return pd.DataFrame()

def generate_fallback_data():
    return pd.DataFrame([
        {"Lega": "Serie A (MOCK)", "Match": "Inter vs Monza", "Quota_1": 1.35, "Quota_X": 5.25, "Quota_2": 9.00, "Under/Over Principale": "O 2.5 (1.70)", "Handicap": "Inter (-1.5) @ 2.05"},
        {"Lega": "Serie A (MOCK)", "Match": "Juventus vs Como", "Quota_1": 1.40, "Quota_X": 4.80, "Quota_2": 8.50, "Under/Over Principale": "O 2.5 (1.75)", "Handicap": "Juventus (-1.5) @ 2.15"}
    ])

# --- 3. MOTORE MATEMATICO ---
def calculate_market_intelligence(df):
    if df.empty: return df
    
    df['Prob_1_Imp'] = 1 / df['Quota_1']
    df['Prob_X_Imp'] = 1 / df['Quota_X']
    df['Prob_2_Imp'] = 1 / df['Quota_2']
    
    total_prob = df['Prob_1_Imp'] + df['Prob_X_Imp'] + df['Prob_2_Imp']
    df['Prob_1_Norm'] = df['Prob_1_Imp'] / total_prob
    df['Prob_X_Norm'] = df['Prob_X_Imp'] / total_prob
    df['Prob_2_Norm'] = df['Prob_2_Imp'] / total_prob
    
    best_outcomes, confidences, kelly_stakes = [], [], []
    
    for _, row in df.iterrows():
        probs = {'1': row['Prob_1_Norm'], 'X': row['Prob_X_Norm'], '2': row['Prob_2_Norm']}
        quotes = {'1': row['Quota_1'], 'X': row['Quota_X'], '2': row['Quota_2']}
        
        best_choice = max(probs, key=probs.get)
        conf_val = probs[best_choice]
        
        p = conf_val
        quota = quotes[best_choice]
        b = quota - 1
        q = 1 - p
        
        kelly = ((b * p - q) / b) * 100 if b > 0 else 0
        kelly_pct = max(0.0, round(kelly * 0.25, 2))
        
        best_outcomes.append(best_choice)
        confidences.append(int(conf_val * 100))
        kelly_stakes.append(kelly_pct)
        
    df['Esito Algoritmo'] = best_outcomes
    df['Confidenza (%)'] = confidences
    df['Kelly Stake (%)'] = kelly_stakes
    
    return df

# --- 4. CONNESSIONE GEMINI REST API (FIX URL CORRETTO) ---
def get_gemini_market_intelligence(api_key, df_filtered, model_name):
    df_ai = df_filtered.sort_values(by="Confidenza (%)", ascending=False).head(10)
    market_summary = df_ai[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Under/Over Principale', 'Handicap', 'Esito Algoritmo', 'Kelly Stake (%)']].to_string(index=False)
    
    prompt = f"""
    Agisci come un analista quantitativo di scommesse sportive. 
    Analizza queste partite processate con quote 1X2, Under/Over, Handicap e Criterio di Kelly:
    
    {market_summary}
    
    Compiti:
    1. Evidenzia le 2 migliori selezioni complessive (valutando anche i mercati di spread o totali se rilevanti).
    2. Spiega brevemente la logica matematica e di rischio dietro queste scelte.
    
    Rispondi in Markdown, sii diretto e professionale.
    """
    
    # URL CORRETTO: rimosso il suffisso '-latest' che causava l'errore 404
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            testo = data['candidates'][0]['content']['parts'][0]['text']
            return testo, "Successo"
        else:
            return None, f"Errore API {response.status_code}: {response.text}"
    except Exception as e:
        return None, f"Errore di Connessione: {str(e)}"

# --- 5. INTERFACCIA UTENTE ---
with st.sidebar:
    st.title("⚙️ Bet-Pro Config")
    st.markdown("---")
    
    st.subheader("1. Modello IA")
    selected_model = st.selectbox("Seleziona Modello", ("gemini-1.5-flash", "gemini-pro"))
    gemini_key_input = st.text_input("Gemini API Key", value=DEFAULT_GEMINI_KEY, type="password")
    
    st.markdown("---")
    st.subheader("2. Dati Sportivi")
    odds_key_input = st.text_input("The Odds API Key", placeholder="Inserisci chiave", type="password")
    
    st.markdown("---")
    st.subheader("3. Filtri")
    min_conf = st.slider("Confidenza Minima (%)", min_value=30, max_value=85, value=40)

st.title("📊 Bet-Pro | Advanced Intelligence Hub")

if not odds_key_input:
    st.error("⚠️ Inserisci la chiave di The Odds API nella barra laterale per sbloccare tutti gli eventi reali e i mercati avanzati.")

with st.spinner("Sincronizzazione mercati (1X2, Under/Over, Handicap)..."):
    if odds_key_input:
        df_raw = fetch_real_odds_data(odds_key_input)
        if df_raw.empty:
            st.warning("Nessun dato trovato con la chiave inserita. Caricati dati di test.")
            df_raw = generate_fallback_data()
    else:
        df_raw = generate_fallback_data()
        
    df_analyzed = calculate_market_intelligence(df_raw)

df_filtered = df_analyzed[df_analyzed['Confidenza (%)'] >= min_conf]

col1, col2, col3 = st.columns(3)
col1.metric("Match Totali", len(df_raw))
col2.metric(f"Match Validi (>{min_conf}%)", len(df_filtered))
if not df_filtered.empty:
    col3.metric("Max Kelly Stake", f"{df_filtered['Kelly Stake (%)'].max()}%")

st.markdown("---")
st.subheader("📋 Palinsesto Multi-Mercato Elaborato")

if not df_filtered.empty:
    st.dataframe(
        df_filtered[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Under/Over Principale', 'Handicap', 'Esito Algoritmo', 'Confidenza (%)', 'Kelly Stake (%)']], 
        use_container_width=True, 
        hide_index=True
    )
    
    st.markdown("---")
    st.subheader("🧠 Interrogazione Motore AI")
    
    if st.button(f"🚀 Avvia Analisi Strategica con {selected_model}", type="primary", use_container_width=True):
        if not gemini_key_input:
            st.error("Inserisci la chiave API di Gemini.")
        else:
            with st.spinner(f"Elaborazione in corso con {selected_model}..."):
                ai_report, status = get_gemini_market_intelligence(gemini_key_input, df_filtered, selected_model)
                if ai_report:
                    st.success("Analisi completata con successo.")
                    st.markdown(f"> {ai_report}")
                else:
                    st.error(status)
else:
    st.warning("Nessun match supera i parametri attuali.")
            
