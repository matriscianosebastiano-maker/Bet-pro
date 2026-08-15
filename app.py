import streamlit as st
import requests
import pandas as pd
import numpy as np
import math
from google import genai

# --- 1. SETUP E CONFIGURAZIONE ---
st.set_page_config(page_title="Bet-Pro | Intelligence Hub", page_icon="🎯", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 2. MOTORE DI ACQUISIZIONE MERCATI REALI (1X2, Totals, BTTS) ---
@st.cache_data(ttl=300)
def fetch_real_odds_data(api_key):
    """Scarica i mercati reali (1X2, Totals, BTTS) da The Odds API."""
    if not api_key:
        return pd.DataFrame()
        
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?regions=eu&markets=h2h,totals,btts&bookmakers=pinnacle,bet365&apiKey={api_key}"
    
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
            
            # Mercato 1X2 (H2H)
            h2h = next((m for m in markets if m["key"] == "h2h"), None)
            q1, qx, q2 = 0.0, 0.0, 0.0
            if h2h:
                for o in h2h.get("outcomes", []):
                    if o["name"] == home_team: q1 = o["price"]
                    elif o["name"] == away_team: q2 = o["price"]
                    elif o["name"] == "Draw": qx = o["price"]
            
            # Mercato Under/Over (Totals)
            totals = next((m for m in markets if m["key"] == "totals"), None)
            over_desc = "N/A"
            over_line_val = 2.5
            if totals:
                for o in totals.get("outcomes", []):
                    if o["name"] == "Over":
                        over_line_val = o.get('point', 2.5)
                        over_desc = f"O {over_line_val} ({o.get('price', 0)})"

            # Mercato Goal/NoGoal (BTTS)
            btts = next((m for m in markets if m["key"] == "btts"), None)
            q_goal = 0.0
            if btts:
                yes_outcome = next((o for o in btts.get("outcomes", []) if o["name"] == "Yes"), None)
                if yes_outcome:
                    q_goal = yes_outcome.get("price", 0.0)

            if q1 > 0 and q2 > 0 and qx > 0:
                matches_list.append({
                    "Lega": event.get("sport_title", "Calcio"),
                    "Match": f"{home_team} vs {away_team}",
                    "Quota_1": q1,
                    "Quota_X": qx,
                    "Quota_2": q2,
                    "Over/Under": over_desc,
                    "Over_Line": over_line_val,
                    "Q_Goal": q_goal
                })
                    
        return pd.DataFrame(matches_list)
        
    except Exception as e:
        return pd.DataFrame()

def generate_fallback_data():
    return pd.DataFrame([
        {"Lega": "Serie A (MOCK)", "Match": "Inter vs Monza", "Quota_1": 1.35, "Quota_X": 5.25, "Quota_2": 9.00, "Over/Under": "O 2.5 (1.70)", "Over_Line": 2.5, "Q_Goal": 1.85},
        {"Lega": "Serie A (MOCK)", "Match": "Juventus vs Como", "Quota_1": 1.75, "Quota_X": 3.60, "Quota_2": 4.80, "Over/Under": "U 2.5 (1.85)", "Over_Line": 2.5, "Q_Goal": 1.70}
    ])

# --- 3. MODELLO MATEMATICO E PREDITTIVO DI POISSON BI-VARIATO ---
def poisson_probability(lmbda, k):
    """Calcola la probabilità di k eventi con distribuzione di Poisson."""
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)

def estimate_expected_goals(q1, qx, q2):
    """Estima gli xG (lambda casa e trasferta) invertendo le quote di mercato 1X2."""
    p1 = 1 / q1
    px = 1 / qx
    p2 = 1 / q2
    total = p1 + px + p2
    norm_p1, norm_p2 = p1 / total, p2 / total
    
    # Euristica matematica di conversione quote in xG bilanciati
    # xG Casa stimato in base alla forza del favorito
    lambda_home = max(0.8, 1.45 + (norm_p1 - 0.33) * 2.2)
    lambda_away = max(0.6, 1.10 + (norm_p2 - 0.33) * 1.8)
    return round(lambda_home, 2), round(lambda_away, 2)

def calculate_market_intelligence(df):
    if df.empty: 
        return df
    
    # Calcolo probabilità implicite e normalizzate (lavagna 1X2)
    df['P1'] = 1 / df['Quota_1']
    df['PX'] = 1 / df['Quota_X']
    df['P2'] = 1 / df['Quota_2']
    
    total_prob = df['P1'] + df['PX'] + df['P2']
    df['Prob_1_Norm'] = df['P1'] / total_prob
    df['Prob_X_Norm'] = df['PX'] / total_prob
    df['Prob_2_Norm'] = df['P2'] / total_prob
    
    scelte_esito = []
    confidences = []
    kelly_stakes = []
    consigli = []
    xg_casa_list = []
    xg_ospite_list = []
    
    for _, row in df.iterrows():
        q1, qx, q2 = row['Quota_1'], row['Quota_X'], row['Quota_2']
        q_goal = row.get('Q_Goal', 0.0)
        
        # 1. Calcolo xG tramite modello Poisson/Mercato
        lam_h, lam_a = estimate_expected_goals(q1, qx, q2)
        xg_casa_list.append(lam_h)
        xg_ospite_list.append(lam_a)
        
        # 2. Simulazione della matrice dei risultati (fino a 5 gol per squadra)
        prob_home_win = 0
        prob_draw = 0
        prob_away_win = 0
        prob_over_15 = 0
        prob_btts = 0
        
        for h in range(6):
            for a in range(6):
                p_score = poisson_probability(lam_h, h) * poisson_probability(lam_a, a)
                if h > a: prob_home_win += p_score
                elif h == a: prob_draw += p_score
                else: prob_away_win += p_score
                
                if (h + a) > 1.5:
                    prob_over_15 += p_score
                if h > 0 and a > 0:
                    prob_btts += p_score

        # 3. Decision Engine basato su probabilità congiunte (Combo & Valore)
        # Probabilità della Combo 1 + Over 1.5 = P(Casa vince) * P(Over 1.5 | Casa vince) approssimata congiuntamente
        prob_combo_1_ov15 = prob_home_win * prob_over_15
        
        if q1 < 1.45 and prob_combo_1_ov15 > 0.55:
            esito_consigliato = "1 + Over 1.5 (Combo)"
            conf_val = max(prob_combo_1_ov15, row['Prob_1_Norm'])
            consiglio = f"xG Stimati [H: {lam_h} - A: {lam_a}]. Modello Poisson valida la Combo ad alta probabilità."
        elif q1 > 1.65 and q_goal > 0 and prob_btts > 0.52:
            esito_consigliato = "Goal (BTTS)"
            conf_val = prob_btts
            consiglio = f"xG Stimati [H: {lam_h} - A: {lam_a}]. Incrocio reti stimato al {int(prob_btts*100)}%."
        else:
            # Scelta basata sul massimo valore di probabilità normalizzata tra 1, X, 2
            probs_dict = {'1 (Casa)': row['Prob_1_Norm'], 'X (Pareggio)': row['Prob_X_Norm'], '2 (Ospite)': row['Prob_2_Norm']}
            best_choice = max(probs_dict, key=probs_dict.get)
            esito_consigliato = f"Singola {best_choice}"
            conf_val = probs_dict[best_choice]
            consiglio = f"xG Stimati [H: {lam_h} - A: {lam_a}]. Efficienza lineare su mercato 1X2."

        p = conf_val
        # Determinazione quota di riferimento per il criterio di Kelly
        if "Combo" in esito_consigliato:
            quota_rif = q1 * 1.32 # stima media moltiplicatore combo
        elif "Goal" in esito_consigliato:
            quota_rif = q_goal if q_goal > 0 else 1.80
        else:
            if "1" in esito_consigliato: quota_rif = q1
            elif "X" in esito_consigliato: quota_rif = qx
            else: quota_rif = q2
            
        b = quota_rif - 1
        q = 1 - p
        kelly = ((b * p - q) / b) * 100 if b > 0 else 0
        kelly_pct = max(0.0, round(kelly * 0.25, 2))

        scelte_esito.append(esito_consigliato)
        confidences.append(int(conf_val * 100))
        kelly_stakes.append(kelly_pct)
        consigli.append(consiglio)
        
    df['xG_Casa'] = xg_casa_list
    df['xG_Ospite'] = xg_ospite_list
    df['Esito Consigliato'] = scelte_esito
    df['Confidenza (%)'] = confidences
    df['Kelly Stake (%)'] = kelly_stakes
    df['Analisi Mercato'] = consigli
    
    return df

# --- 4. INTERROGAZIONE GEMINI SDK (google-genai) ---
def get_gemini_market_intelligence(api_key, df_filtered, model_name):
    df_ai = df_filtered.sort_values(by="Confidenza (%)", ascending=False).head(10)
    market_summary = df_ai[['Lega', 'Match', 'xG_Casa', 'xG_Ospite', 'Esito Consigliato', 'Confidenza (%)', 'Kelly Stake (%)']].to_string(index=False)
    
    prompt = f"""
    Agisci come un analista quantitativo di scommesse sportive ed esperto di modelli di Poisson.
    Esamina i seguenti dati predittivi odierni calcolati tramite xG e probabilità congiunte:
    
    {market_summary}
    
    Fornisci indicazioni operative precise per le scommesse di OGGI:
    1. Commenta la solidità delle previsioni basandoti sui valori di xG stimati e sulle Combo raccomandate.
    2. Definisci la gestione del bankroll tramite i parametri di confidenza matematica.
    
    Sii diretto, tecnico e operativo in Markdown.
    """
    
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        if response and response.text:
            return response.text, "Successo"
        else:
            return None, "Risposta vuota dal modello."
    except Exception as e:
        return None, f"Errore SDK Gemini: {str(e)}"

# --- 5. INTERFACCIA UTENTE STREAMLIT ---
with st.sidebar:
    st.title("⚙️ Bet-Pro Config")
    st.markdown("---")
    
    st.subheader("1. Modello IA")
    selected_model = st.selectbox("Seleziona Modello", ("gemini-3.6-flash", "gemini-3.5-flash"))
    
    st.markdown("---")
    st.subheader("2. Stato Connessioni")
    if GEMINI_API_KEY:
        st.success("🟢 Gemini API: Configurata")
    else:
        st.error("🔴 Gemini API: Mancante nei Secrets")
        
    if ODDS_API_KEY:
        st.success("🟢 The Odds API: Configurata")
    else:
        st.warning("🟡 The Odds API: Mancante (Uso dati mock)")

    st.markdown("---")
    st.subheader("3. Filtri")
    min_conf = st.slider("Confidenza Predittiva Minima (%)", min_value=30, max_value=85, value=40)

st.title("📊 Bet-Pro | Advanced Predictive Intelligence")

# Sincronizzazione dati
with st.spinner("Sincronizzazione mercati e calcolo Poisson xG in corso..."):
    if ODDS_API_KEY:
        df_raw = fetch_real_odds_data(ODDS_API_KEY)
        if df_raw.empty:
            st.warning("Nessun match trovato oggi o chiave non valida. Caricati dati di test.")
            df_raw = generate_fallback_data()
    else:
        df_raw = generate_fallback_data()
        
    df_analyzed = calculate_market_intelligence(df_raw)

df_filtered = df_analyzed[df_analyzed['Confidenza (%)'] >= min_conf]

col1, col2, col3 = st.columns(3)
col1.metric("Match Analizzati", len(df_raw))
col2.metric(f"Match a Valore (>{min_conf}%)", len(df_filtered))
if not df_filtered.empty:
    col3.metric("Max Kelly Stake", f"{df_filtered['Kelly Stake (%)'].max()}%")

st.markdown("---")
st.subheader("📋 Palinsesto Quantitativo (xG, Poisson & Combo)")

if not df_filtered.empty:
    st.dataframe(
        df_filtered[['Lega', 'Match', 'xG_Casa', 'xG_Ospite', 'Over/Under', 'Esito Consigliato', 'Confidenza (%)', 'Kelly Stake (%)', 'Analisi Mercato']], 
        use_container_width=True, 
        hide_index=True
    )
    
    st.markdown("---")
    st.subheader("🎯 Strategia Quantitativa e Pronostici odierni")
    
    if st.button(f"🚀 Genera Report Predittivo con {selected_model}", type="primary", use_container_width=True):
        if not GEMINI_API_KEY:
            st.error("Chiave API di Gemini mancante nei Secrets.")
        else:
            with st.spinner(f"Elaborazione quantitativa in corso con {selected_model}..."):
                ai_report, status = get_gemini_market_intelligence(GEMINI_API_KEY, df_filtered, selected_model)
                if ai_report:
                    st.success("Analisi completata con successo.")
                    st.markdown(f"> {ai_report}")
                else:
                    st.error(status)
else:
    st.warning("Nessun match rispetta i criteri di confidenza predittiva impostati.")
        
