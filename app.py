import streamlit as st
import requests
import pandas as pd
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
                    "Match": f"{home_team} vs {away_team}",
                    "Quota_1": q1,
                    "Quota_X": qx,
                    "Quota_2": q2,
                    "Over/Under": over_desc,
                    "Q_Goal": q_goal
                })
                    
        return pd.DataFrame(matches_list)
        
    except Exception as e:
        return pd.DataFrame()

def generate_fallback_data():
    return pd.DataFrame([
        {"Lega": "Serie A (MOCK)", "Match": "Inter vs Monza", "Quota_1": 1.35, "Quota_X": 5.25, "Quota_2": 9.00, "Over/Under": "O 2.5 (1.70)", "Q_Goal": 1.85},
        {"Lega": "Serie A (MOCK)", "Match": "Juventus vs Como", "Quota_1": 1.75, "Quota_X": 3.60, "Quota_2": 4.80, "Over/Under": "U 2.5 (1.85)", "Q_Goal": 1.70}
    ])

# --- 3. MOTORE MATEMATICO E CLASSI DI ESITO CON COMBO LOGICHE ---
def calculate_market_intelligence(df):
    if df.empty: return df
    
    # Calcolo probabilità implicite e normalizzate (lavagna 1X2)
    df['P1'] = 1 / df['Quota_1']
    df['PX'] = 1 / df['Quota_X']
    df['P2'] = 1 / df['Quota_2']
    
    total_prob = df['P1'] + df['PX'] + df['P2']
    df['Prob_1_Norm'] = df['P1'] / total_prob
    df['Prob_X_Norm'] = df['PX'] / total_prob
    df['Prob_2_Norm'] = df['P2'] / total_prob
    
    scelte_esito, confidenze, kelly_stakes, consigli = [], [], [], []
    
    for _, row in df.iterrows():
        probs = {'1 (Casa)': row['Prob_1_Norm'], 'X (Pareggio)': row['Prob_X_Norm'], '2 (Ospite)': row['Prob_2_Norm']}
        quotes = {'1 (Casa)': row['Quota_1'], 'X (Pareggio)': row['Quota_X'], '2 (Ospite)': row['Quota_2']}
        
        best_choice = max(probs, key=probs.get)
        conf_val = probs[best_choice]
        
        q_goal = row.get('Q_Goal', 0.0)
        q1 = row['Quota_1']
        
        # --- Logica Combo Universale e Classi di Esito Avanzate ---
        if q1 < 1.45:
            # Favorito netto: la quota secca è bassa, si opta per la Combo di protezione
            esito_consigliato = "1 + Over 1.5 (Combo)"
            consiglio = f"Favorito netto ({q1}): quota 1 bassa, meglio la Combo per alzare il valore."
            # Stima di confidenza ponderata sulla spinta del favorito
            conf_val = max(conf_val, 0.72)
        elif q1 > 1.70 and q_goal > 0 and q_goal < 1.75:
            # Incontro aperto: entrambe le squadre segnano con buona probabilità
            esito_consigliato = "Goal (BTTS)"
            consiglio = f"Alta probabilità di reti da ambo i lati (Quota Goal: {q_goal})."
            conf_val = max(conf_val, 0.65)
        else:
            # Singola di valore standard sul segno più probabile
            esito_consigliato = f"Singola {best_choice}"
            consiglio = f"Valore lineare ottimale sul mercato 1X2."

        p = conf_val
        # Associamo una quota stimata di riferimento per il calcolo del Kelly
        quota_rif = (q1 * 1.30) if "Combo" in esito_consigliato else (q_goal if "Goal" in esito_consigliato else quotes[best_choice])
        
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
    df['Analisi Mercato'] = consigli
    
    return df

# --- 4. INTERROGAZIONE GEMINI SDK (google-genai) ---
def get_gemini_market_intelligence(api_key, df_filtered, model_name):
    df_ai = df_filtered.sort_values(by="Confidenza (%)", ascending=False).head(10)
    market_summary = df_ai[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Over/Under', 'Esito Consigliato', 'Kelly Stake (%)']].to_string(index=False)
    
    prompt = f"""
    Agisci come un esperto di scommesse sportive e analista professionista di mercati calcistici.
    Esamina i seguenti dati odierni integrati con logiche di Combo (es. 1 + Over 1.5) e mercati Goal/NoGoal:
    
    {market_summary}
    
    Fornisci indicazioni operative precise per le scommesse di OGGI:
    1. Seleziona la singola, la combo o la giocata in singola più solida basandoti sulle classi di esito ottimizzate.
    2. Spiega la gestione del rischio e perché la scelta della Combo o del Goal prevale sul semplice segno secco.
    
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
    min_conf = st.slider("Confidenza Minima (%)", min_value=30, max_value=85, value=40)

st.title("📊 Bet-Pro | Advanced Intelligence Hub")

# Sincronizzazione dati
with st.spinner("Sincronizzazione mercati e quote in corso..."):
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
col1.metric("Match Totali", len(df_raw))
col2.metric(f"Match Validi (>{min_conf}%)", len(df_filtered))
if not df_filtered.empty:
    col3.metric("Max Kelly Stake", f"{df_filtered['Kelly Stake (%)'].max()}%")

st.markdown("---")
st.subheader("📋 Palinsesto Avanzato (Combo, Goal/NoGoal & 1X2)")

if not df_filtered.empty:
    st.dataframe(
        df_filtered[['Lega', 'Match', 'Quota_1', 'Quota_X', 'Quota_2', 'Over/Under', 'Esito Consigliato', 'Confidenza (%)', 'Kelly Stake (%)', 'Analisi Mercato']], 
        use_container_width=True, 
        hide_index=True
    )
    
    st.markdown("---")
    st.subheader("🎯 Strategia e Pronostici per la Giocata odierna")
    
    if st.button(f"🚀 Genera Schedina e Analisi con {selected_model}", type="primary", use_container_width=True):
        if not GEMINI_API_KEY:
            st.error("Chiave API di Gemini mancante nei Secrets.")
        else:
            with st.spinner(f"Analisi tattica in corso con {selected_model}..."):
                ai_report, status = get_gemini_market_intelligence(GEMINI_API_KEY, df_filtered, selected_model)
                if ai_report:
                    st.success("Analisi completata con successo.")
                    st.markdown(f"> {ai_report}")
                else:
                    st.error(status)
else:
    st.warning("Nessun match rispetta i criteri di confidenza impostati.")
    
