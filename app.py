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
FOOTBALL_DATA_API_KEY = st.secrets.get("FOOTBALL_DATA_API_KEY", "") or st.secrets.get("API_FOOTBALL_KEY", "")
EMAIL_USER = st.secrets.get("EMAIL_USER", "")
EMAIL_PASS = st.secrets.get("EMAIL_PASS", "")
HISTORY_FILE = "bet_history.csv"

# --- LOGICA DI FETCHING CON FOOTBALL-DATA.ORG V4 ---
def fetch_fixtures_and_odds(api_key: str):
    if not api_key: 
        return None, "❌ Errore: Token API per football-data.org non configurato nei Secrets."
    try:
        italy_tz = timezone(timedelta(hours=2))
        oggi_dt = datetime.now(italy_tz)
        
        date_from = oggi_dt.strftime("%Y-%m-%d")
        date_to = (oggi_dt + timedelta(days=3)).strftime("%Y-%m-%d")
        
        # Endpoint ufficiale football-data.org v4
        url = f"https://api.football-data.org/v4/matches?dateFrom={date_from}&dateTo={date_to}"
        headers = {"X-Auth-Token": api_key.strip()}
        
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None, f"❌ Errore API football-data.org (Status {resp.status_code}): {resp.text}"
            
        data = resp.json()
        matches = data.get("matches", [])
        
        if not matches:
            return None, "⚠️ Nessuna partita trovata nel palinsesto di football-data.org per i prossimi giorni."

        elite_matches = []
        global_matches = []
        elite_keywords = ["serie a", "serie b", "coppa italia", "supercoppa", "champions league", "europa league", "conference league", "premier league", "la liga", "bundesliga", "ligue 1"]

        for m in matches:
            status = m.get('status')
            if status not in ['TIMED', 'SCHEDULED']:
                continue
                
            utc_date_str = m.get('utcDate', '')
            match_time_str = "N/D"
            if utc_date_str:
                try:
                    dt_utc = datetime.fromisoformat(utc_date_str.replace('Z', '+00:00'))
                    match_time_str = dt_utc.astimezone(italy_tz).strftime('%d/%m %H:%M')
                except Exception:
                    pass
            
            home = m.get('homeTeam', {}).get('name', 'Sconosciuta')
            away = m.get('awayTeam', {}).get('name', 'Sconosciuta')
            competition = m.get('competition', {})
            league_name = competition.get('name', 'Campionato')
            country = competition.get('area', {}).get('name', 'Internazionale')
            
            odds_info = m.get('odds', {})
            if odds_info and 'homeWin' in odds_info:
                odds_str = f"1: {odds_info.get('homeWin')} | X: {odds_info.get('draw')} | 2: {odds_info.get('awayWin')}"
            else:
                odds_str = "Quote da stimare tramite modelli ELO/Poisson"
                
            match_line = f"[{match_time_str}] {home} vs {away} | L: {league_name} ({country}) | Quote: {odds_str}"
            
            is_elite = any(kw in league_name.lower() for kw in elite_keywords) or country.lower() in ["italy", "england", "spain", "germany", "france", "europe"]
            
            if is_elite:
                elite_matches.append(match_line)
            else:
                global_matches.append(match_line)
        
        combined_data = "--- PALINSESTO ELITE (ITALIA & EUROPA / COPPE) ---\n"
        combined_data += "\n".join(elite_matches) if elite_matches else "Nessun match elite diretto trovato nel periodo."
        combined_data += "\n\n--- PALINSESTO GLOBALE ---\n" + "\n".join(global_matches[:70])
        
        return combined_data, None
    except Exception as e: 
        return None, f"❌ Errore durante il recupero dei dati: {str(e)}"

# --- LOGICA DI REPORT E STORICO ---
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

# --- MOTORE QUANTISTICO CON FALLBACK MODELLI ---
def run_quant_engine(match_data: str, api_key: str) -> str:
    if not api_key:
        return "❌ ERRORE: GROQ_API_KEY non presente."
        
    client = Groq(api_key=api_key.strip())
    
    system_prompt = (
        "Sei il 'Quant Engine Alpha', un'analisi sportiva istituzionale.\n"
        "REQUISITO FONDAMENTALE: Utilizza ESCLUSIVAMENTE i dati reali delle partite presenti nel palinsesto fornito. È severamente vietato inventare o simulare match.\n\n"
        "STRUTTURA RIGIDA DI OUTPUT:\n"
        "1. **STRATEGIA 1: Schedina Global Daily 50€** (5 eventi basati sul palinsesto globale).\n"
        "2. **STRATEGIA 2: Specchietto Dedicato Elite (Italiane & Principali Europee / Coppe)** (5 eventi focalizzati su Serie A, Coppe e Top Club).\n\n"
        "Per ogni partita indica: Match e Orario, Classe di Esito (Pronostico preciso), Quota Ufficiale o Stimata, e Ragionamento Matematico / Statistico basato su Poisson/ELO.\n"
        "Includi sempre Quota Totale Combinata, Confidence Score (0-100%) e Protocollo di Rischio (Toro/Orso con puntata consigliata)."
    )
    
    user_prompt = f"Ecco i dati reali estratti:\n{match_data}\nGenera le due strategie basandoti unicamente su questi incontri reali."
    
    models = ["llama-3.3-70b-versatile", "qwen-2.5-32b", "llama3-70b-8192"]
    
    for model_name in models:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception:
            continue
            
    return "❌ Errore di connessione a Groq su tutti i modelli. Riprova tra qualche secondo."

# --- UI STREAMLIT ---
st.title("⚙️ Bet-Pro | Quant Engine Alpha")

if st.button("🚀 Inizializza Motore Quantistico", type="primary"):
    with st.spinner("Estrazione Palinsesto da football-data.org in corso..."):
        data, err = fetch_fixtures_and_odds(FOOTBALL_DATA_API_KEY)
        if err: 
            st.error(err)
        else:
            result = run_quant_engine(data, GROQ_API_KEY)
            st.session_state["analysis_result"] = result
            if "❌" not in result:
                save_bet_to_history({"date": datetime.now(), "result": result})

if st.session_state.get("analysis_result"):
    st.markdown(st.session_state["analysis_result"])

st.sidebar.markdown("---")
if st.sidebar.button("📧 Invia Report Settimanale"):
    st.sidebar.info(send_weekly_report())

if os.path.exists(HISTORY_FILE):
    st.sidebar.subheader("📊 Storico Recente")
    st.sidebar.dataframe(pd.read_csv(HISTORY_FILE).tail(3))
    
