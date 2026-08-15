import streamlit as st
import requests
import pandas as pd
import numpy as np
import math
from google import genai
from datetime import datetime, timezone, timedelta

# --- 1. SETUP E CONFIGURAZIONE ---
st.set_page_config(page_title="Bet-Pro | Intelligence Hub", page_icon="🎯", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

# --- 2. MOTORE DI ACQUISIZIONE MULTI-LEGA (Oggi e Domani) ---
@st.cache_data(ttl=300)
def fetch_real_odds_data(api_key):
    """Scarica in background tutte le partite di calcio dai principali campionati."""
    if not api_key:
        return pd.DataFrame()
        
    # Elenco delle chiavi sport principali per coprire tutto il palinsesto europeo/internazionale
    soccer_keys = [
        "soccer_italy_serie_a",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_france_ligue_one",
        "soccer_uefa_champs_league"
    ]
    
    matches_list = []
    headers = {}
    
    now_utc = datetime.now(timezone.utc)
    # Impostiamo il range per catturare le partite da adesso fino a fine giornata di domani
    time_from = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_to = (now_utc + timedelta(days=2)).strftime("%Y-%m-%dT23:59:59Z")
    
    for sport_key in soccer_keys:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?regions=eu&markets=h2h,totals,btts&bookmakers=pinnacle,bet365&apiKey={api_key}&commenceTimeFrom={time_from}&commenceTimeTo={time_to}"
        try:
            response = requests.get(url, timeout=6)
            if response.status_code != 200:
                continue
                
            data = response.json()
            for event in data:
                home_team = event.get("home_team")
                away_team = event.get("away_team")
                commence_time = event.get("commence_time")
                
                # Formattazione data/ora locale evento
                try:
                    dt_obj = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
                    orario_str = dt_obj.astimezone().strftime("%d/%m %H:%M")
                except:
                    orario_str = "Data N/D"

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
                
                # Mercato Under/Over
                totals = next((m for m in markets if m["key"] == "totals"), None)
                over_desc = "N/A"
                if totals:
                    for o in totals.get("outcomes", []):
                        if o["name"] == "Over":
                            over_desc = f"O {o.get('point', 2.5)} ({o.get('price', 0)})"

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
                        "Data": orario_str,
                        "Match": f"{home_team} vs {away_team}",
                        "Quota_1": q1,
                        "Quota_X": qx,
                        "Quota_2": q2,
                        "Over/Under": over_desc,
                        "Q_Goal": q_goal
                    })
        except Exception:
            continue
            
    return pd.DataFrame(matches_list)

def generate_fallback_data():
    return pd.DataFrame([
        {"Lega": "Serie A", "Data": "Oggi 20:45", "Match": "Inter vs Monza", "Quota_1": 1.35, "Quota_X": 5.25, "Quota_2": 9.00, "Over/Under": "O 2.5 (1.70)", "Q_Goal": 1.85},
        {"Lega": "Serie A", "Data": "Dom 18:00", "Match": "Juventus vs Como", "Quota_1": 1.75, "Quota_X": 3.60, "Quota_2": 4.80, "Over/Under": "U 2.5 (1.85)", "Q_Goal": 1.70},
        {"Lega": "Premier League", "Data": "Dom 15:00", "Match": "Manchester United vs Fulham", "Quota_1": 1.55, "Quota_X": 4.20, "Quota_2": 5.80, "Over/Under": "O 2.5 (1.65)", "Q_Goal": 1.75}
    ])

# --- 3. MODELLO MATEMATICO IN BACKGROUND (Poisson & Kelly invisibili) ---
def poisson_probability(lmbda, k):
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)

def estimate_expected_goals(q1, qx, q2):
    p1, px, p2 = 1 / q1, 1 / qx, 1 / q2
    total = p1 + px + p2
    norm_p1, norm_p2 = p1 / total, p2 / total
    lambda_home = max(0.8, 1.45 + (norm_p1 - 0.33) * 2.2)
    lambda_away = max(0.6, 1.10 + (norm_p2 - 0.33) * 1.8)
    return round(lambda_home, 2), round(lambda_away, 2)

def calculate_market_intelligence(df):
    if df.empty: 
        return df
    
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
    
    for _, row in df.iterrows():
        q1, qx, q2 = row['Quota_1'], row['Quota_X'], row['Quota_2']
        q_goal = row.get('Q_Goal', 0.0)
        
        lam_h, lam_a = estimate_expected_goals(q1, qx, q2)
        
        prob_home_win = 0
        prob_over_15 = 0
        prob_btts = 0
        
        for h in range(6):
            for a in range(6):
                p_score = poisson_probability(lam_h, h) * poisson_probability(lam_a, a)
                if h > a: prob_home_win += p_score
                if (h + a) > 1.5: prob_over_15 += p_score
                if h > 0 and a > 0: prob_btts += p_score

        prob_combo_1_ov15 = prob_home_win * prob_over_15
        
        if q1 < 1.45 and prob_combo_1_ov15 > 0.55:
            esito_consigliato = "1 + Over 1.5 (Combo)"
            conf_val = max(prob_combo_1_ov15, row['Prob_1_Norm'])
            consiglio = "Favorito netto: Combo consigliata per massimizzare il rendimento."
        elif q1 > 1.65 and q_goal > 0 and prob_btts > 0.52:
            esito_consigliato = "Goal (BTTS)"
            conf_val = prob_btts
            consiglio = "Ottima spinta offensiva stimata da ambo i lati."
        else:
            probs_dict = {'1 (Casa)': row['Prob_1_Norm'], 'X (Pareggio)': row['Prob_X_Norm'], '2 (Ospite)': row['Prob_2_Norm']}
            best_choice = max(probs_dict, key=probs_dict.get)
            esito_consigliato = f"Segno {best_choice[0]}"
            conf_val = probs_dict[best_choice]
            consiglio = "Analisi di valore lineare sul mercato principale."

        p = conf_val
        if "Combo" in esito_consigliato: quota_rif = q1 * 1.32
        elif "Goal" in esito_consigliato: quota_rif = q_goal if q_goal > 0 else 1.80
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
        
    df['Esito Consigliato'] = scelte_esito
    df['Confidenza (%)'] = confidences
    df['Kelly Stake (%)'] = kelly_stakes
    df['Analisi Sintetica'] = consigli
    
    return df

# --- 4. INTERROGAZIONE GEMINI SDK ---
def get_gemini_market_intelligence(api_key, df_filtered, model_name):
    df_ai = df_filtered.sort_values(by="Confidenza (%)", ascending=False).head(10)
    market_summary = df_ai[['Lega', 'Data', 'Match', 'Esito Consigliato', 'Confidenza (%)', 'Kelly Stake (%)']].to_string(index=False)
    
    prompt = f"""
    Agisci come un esperto di betting professionista. Esamina le seguenti giocate filtrate per oggi e domani:
    
    {market_summary}
    
    Fornisci una schedina sintetica e dritta al punto con i consigli operativi di oggi. Sii chiaro, professionale e in Markdown.
    """
    
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model_name, contents=prompt)
        if response and response.text:
            return response.text, "Successo"
        else:
            return None, "Risposta vuota."
    except Exception as e:
        return None, f"Errore: {str(e)}"

# --- 5. INTERFACCIA UTENTE PULITA ---
with st.sidebar:
    st.title("⚙️ Filtri Rapidi")
    st.markdown("---")
    selected_model = st.selectbox("Modello IA", ("gemini-3.6-flash", "gemini-3.5-flash"))
    min_conf = st.slider("Affidabilità Minima (%)", min_value=30, max_value=80, value=45)
    st.markdown("---")
    if ODDS_API_KEY:
        st.success("🟢 Palinsesto Live Connesso")
    else:
        st.warning("🟡 Modalità Dati di Test")

st.title("🎯 Bet-Pro | I Pronostici di Oggi e Domani")

with st.spinner("Ricerca partite in corso..."):
    if ODDS_API_KEY:
        df_raw = fetch_real_odds_data(ODDS_API_KEY)
        if df_raw.empty:
            df_raw = generate_fallback_data()
    else:
        df_raw = generate_fallback_data()
        
    df_analyzed = calculate_market_intelligence(df_raw)

df_filtered = df_analyzed[df_analyzed['Confidenza (%)'] >= min_conf]

col1, col2 = st.columns(2)
col1.metric("Partite Analizzate", len(df_raw))
col2.metric("Giocate Consigliate", len(df_filtered))

st.markdown("---")
st.subheader("📋 Suggerimenti di Gioca & Pronostici")

if not df_filtered.empty:
    # Mostriamo solo le informazioni utili all'utente finale (senza formule o xG)
    st.dataframe(
        df_filtered[['Lega', 'Data', 'Match', 'Esito Consigliato', 'Confidenza (%)', 'Kelly Stake (%)', 'Analisi Sintetica']], 
        use_container_width=True, 
        hide_index=True
    )
    
    st.markdown("---")
    if st.button("🚀 Genera Schedina Consigliata con IA", type="primary", use_container_width=True):
        if not GEMINI_API_KEY:
            st.error("Chiave API di Gemini mancante.")
        else:
            with st.spinner("Elaborazione schedina in corso..."):
                ai_report, status = get_gemini_market_intelligence(GEMINI_API_KEY, df_filtered, selected_model)
                if ai_report:
                    st.success("Schedina generata con successo!")
                    st.markdown(f"> {ai_report}")
                else:
                    st.error(status)
else:
    st.warning("Nessuna partita rispecchia i filtri di affidabilità impostati. Abbassa la soglia nella barra laterale.")
        
