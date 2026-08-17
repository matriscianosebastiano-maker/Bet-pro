import streamlit as st
import requests
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from groq import Groq
import os

st.set_page_config(page_title="Bet-Pro | Quant Engine Alpha", page_icon="⚙️", layout="wide")

# --- CONFIGURAZIONE ---
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
API_FOOTBALL_KEY = st.secrets.get("API_FOOTBALL_KEY", "")
EMAIL_USER = st.secrets.get("EMAIL_USER", "")
EMAIL_PASS = st.secrets.get("EMAIL_PASS", "")
HISTORY_FILE = "bet_history.csv"

# --- LOGICA DI FETCHING ---
def fetch_fixtures_and_odds(api_key: str):
    if not api_key: return None, "❌ Errore: API_FOOTBALL_KEY non configurata."
    try:
        italy_tz = timezone(timedelta(hours=2))
        oggi = datetime.now(italy_tz).strftime("%Y-%m-%d")
        headers = {"x-rapidapi-host": "v3.football.api-sports.io", "x-rapidapi-key": api_key}
        
        # Recupero dati
        url_f = f"https://v3.football.api-sports.io/fixtures?date={oggi}"
        url_o = f"https://v3.football.api-sports.io/odds?date={oggi}&bookmaker=8"
        
        fixtures = requests.get(url_f, headers=headers, timeout=10).json().get("response", [])
        odds_raw = requests.get(url_o, headers=headers, timeout=10).json().get("response", [])
        
        odds_dict = {}
        for o in odds_raw:
            f_id = o.get("fixture", {}).get("id")
            bets = o.get("bookmakers", [{}])[0].get("bets", [])
            winner = next((b for b in bets if b.get("id") == 1), None)
            if winner and len(winner.get("values", [])) >= 3:
                v = winner["values"]
                odds_dict[f_id] = f"1: {v[0]['odd']} | X: {v[1]['odd']} | 2: {v[2]['odd']}"

        match_list = []
        for m in fixtures:
            f = m['fixture']
            if f['status']['short'] in ['NS', 'TBD'] and f['id'] in odds_dict:
                match_list.append(f"{m['teams']['home']['name']} vs {m['teams']['away']['name']} | L: {m['league']['name']} | Quote: {odds_dict[f['id']]}")
        
        return "\n".join(match_list[:70]), None
    except Exception as e: return None, str(e)

# --- LOGICA DI BACKTESTING E REPORT ---
def save_bet_to_history(data_dict):
    df = pd.DataFrame([data_dict])
    if os.path.exists(HISTORY_FILE): df.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    else: df.to_csv(HISTORY_FILE, mode='w', header=True, index=False)

def send_weekly_report():
    if not os.path.exists(HISTORY_FILE): return "Nessuno storico trovato."
    df = pd.read_csv(HISTORY_FILE)
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "📈 Report Settimanale Bet-Pro Quant Engine"
    msg.attach(MIMEText(f"Log attività:\n\n{df.to_html()}", 'html'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        return "Report inviato con successo."
    except Exception as e: return f"Errore invio: {e}"

# --- MOTORE QUANTISTICO ---
def run_quant_engine(match_data: str, api_key: str) -> str:
    client = Groq(api_key=api_key.strip())
    system_prompt = (
        "Sei il 'Quant Engine Alpha', un'IA per l'analisi sportiva istituzionale. "
        "IL TUO OBBLIGO: Fornire una schedina da 5 eventi ad alta probabilità.\n"
        "STRUTTURA OBBLIGATORIA DEL REPORT:\n"
        "1. ELITE FOCUS (Serie A, Coppa Italia, Premier, Liga, Bundesliga, Ligue 1): Analizza specificamente le squadre italiane e le top europee. Valuta la loro condizione in modo secco e tecnico.\n"
        "2. SCHEDINA DAILY 50€: 5 eventi selezionati con quote medie 1.50-1.80 (Quota totale obiettivo 10-15x).\n"
        "3. PROTOCOLLO RISCHIO: Valuta se il mercato è 'Toro' (punta 5€) o 'Orso' (punta 3€).\n"
        "Sii sintetico, analitico e professionale."
    )
    user_prompt = f"Analizza il palinsesto globale e genera la Strategia:\n{match_data}"
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.1
    )
    return response.choices[0].message.content

# --- UI STREAMLIT ---
st.title("⚙️ Bet-Pro | Quant Engine Alpha")

if st.button("🚀 Inizializza Motore Quantistico"):
    with st.spinner("Analisi Elite & Globale in corso..."):
        data, err = fetch_fixtures_and_odds(API_FOOTBALL_KEY)
        if err: st.error(err)
        else:
            result = run_quant_engine(data, GROQ_API_KEY)
            st.session_state["analysis_result"] = result
            save_bet_to_history({"date": datetime.now(), "result": result})

if st.session_state.get("analysis_result"):
    st.markdown(st.session_state["analysis_result"])

st.sidebar.markdown("---")
if st.sidebar.button("📧 Invia Report Settimanale"):
    st.sidebar.info(send_weekly_report())

if os.path.exists(HISTORY_FILE):
    st.sidebar.subheader("📊 Storico Recente")
    st.sidebar.dataframe(pd.read_csv(HISTORY_FILE).tail(3))
    
