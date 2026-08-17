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

# --- LOGICA DI FETCHING INTELLIGENTE (ELITE + GLOBALE) ---
def fetch_fixtures_and_odds(api_key: str):
    if not api_key: return None, "❌ Errore: API_FOOTBALL_KEY non configurata."
    try:
        italy_tz = timezone(timedelta(hours=2))
        oggi_dt = datetime.now(italy_tz)
        
        dates_to_fetch = [
            oggi_dt.strftime("%Y-%m-%d"),
            (oggi_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        ]
        
        headers = {"x-rapidapi-host": "v3.football.api-sports.io", "x-rapidapi-key": api_key}
        
        all_fixtures = []
        odds_dict = {}
        
        for d_str in dates_to_fetch:
            url_f = f"https://v3.football.api-sports.io/fixtures?date={d_str}"
            url_o = f"https://v3.football.api-sports.io/odds?date={d_str}&bookmaker=8"
            
            resp_f = requests.get(url_f, headers=headers, timeout=10)
            resp_o = requests.get(url_o, headers=headers, timeout=10)
            
            if resp_f.status_code == 200:
                all_fixtures.extend(resp_f.json().get("response", []))
                
            if resp_o.status_code == 200:
                odds_raw = resp_o.json().get("response", [])
                for o in odds_raw:
                    f_id = o.get("fixture", {}).get("id")
                    bets = o.get("bookmakers", [{}])[0].get("bets", [])
                    winner = next((b for b in bets if b.get("id") == 1), None)
                    if winner and len(winner.get("values", [])) >= 3:
                        v = winner["values"]
                        odds_dict[f_id] = f"1: {v[0]['odd']} | X: {v[1]['odd']} | 2: {v[2]['odd']}"

        elite_matches = []
        global_matches = []
        
        elite_keywords = ["serie a", "serie b", "coppa italia", "supercoppa", "champions league", "europa league", "conference league", "premier league", "la liga", "bundesliga", "ligue 1"]

        for m in all_fixtures:
            f = m['fixture']
            if f['status']['short'] not in ['NS', 'TBD']:
                continue
                
            match_timestamp = f.get('timestamp', 0)
            match_time_str = datetime.fromtimestamp(match_timestamp, tz=timezone.utc).astimezone(italy_tz).strftime('%d/%m %H:%M') if match_timestamp > 0 else "N/D"
            
            home = m['teams']['home']['name']
            away = m['teams']['away']['name']
            league_name = m['league']['name']
            country = m['league']['country']
            f_id = f['id']
            
            odds_str = odds_dict.get(f_id, "Quote in aggiornamento (Stima Quantistica ELO)")
            match_line = f"[{match_time_str}] {home} vs {away} | L: {league_name} ({country}) | Quote: {odds_str}"
            
            is_elite = any(kw in league_name.lower() for kw in elite_keywords) or country.lower() in ["italy", "england", "spain", "germany", "france", "europe"]
            
            if is_elite:
                elite_matches.append(match_line)
            else:
                global_matches.append(match_line)
        
        combined_data = "--- PALINSESTO ELITE (ITALIA & EUROPA / COPPE) ---\n"
        if elite_matches:
            combined_data += "\n".join(elite_matches)
        else:
            combined_data += "Nessun match elite diretto trovato nelle prossime 48h."
            
        combined_data += "\n\n--- PALINSESTO GLOBALE ---\n" + "\n".join(global_matches[:80])
        
        return combined_data, None
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
        "Il tuo compito è generare DUE distinte strategie basate rigorosamente sui dati forniti.\n\n"
        "REQUISITO TASSATIVO PER OGNI SINGOLO EVENTO:\n"
        "Non devi mai limitarti a dire la quota o le squadre. Per OGNUNA delle 5 partite di entrambe le strategie devi indicare esplicitamente:\n"
        "- **Match e Orario**\n"
        "- **Classe di Esito (Pronostico preciso):** (es. Segno 1, X2, Over 1.5, Under 3.5, Goal, Combo 1X + Under 3.5)\n"
        "- **Quota Ufficiale o Stimata:** [Valore]\n"
        "- **Ragionamento Matematico / Statistico:** (Breve motivazione basata su Poisson, ELO o asimmetria tecnica)\n\n"
        "STRUTTURA DELL'OUTPUT:\n"
        "1. **STRATEGIA 1: Schedina Global Daily 50€** (5 eventi dal palinsesto globale, target quota totale 10-15x).\n"
        "2. **STRATEGIA 2: Specchietto Dedicato Elite (Italiane & Principali Europee / Coppe)** (Esattamente 5 eventi focalizzati su Serie A, Coppa Italia, coppe europee e top club. Se le quote non sono ancora caricate, stimale rigorosamente con i modelli di calcolo).\n\n"
        "Includi per entrambe le sezioni: la **Quota Totale Combinata**, il **Confidence Score (0-100%)** e il **Protocollo di Rischio** (Toro/Orso con puntata consigliata di 3€ o 5€)."
    )
    user_prompt = f"Ecco i dati divisi per sezioni (Oggi e Domani):\n{match_data}\nGenera le due strategie con le classi di esito complete e dettagliate."
    
    response = client.chat.completions.create(
        model="llama-3.1-70b-versatile",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.1
    )
    return response.choices[0].message.content

# --- UI STREAMLIT ---
st.title("⚙️ Bet-Pro | Quant Engine Alpha")

if st.button("🚀 Inizializza Motore Quantistico", type="primary"):
    with st.spinner("Estrazione Palinsesto Elite & Globale (Oggi & Domani)..."):
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
