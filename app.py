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

# --- LOGICA DI FETCHING INTELLIGENTE ---
def fetch_fixtures_and_odds(api_key: str):
    if not api_key: return None, "❌ Errore: API_FOOTBALL_KEY non configurata nei secrets."
    try:
        italy_tz = timezone(timedelta(hours=2))
        oggi_dt = datetime.now(italy_tz)
        dates_to_fetch = [oggi_dt.strftime("%Y-%m-%d"), (oggi_dt + timedelta(days=1)).strftime("%Y-%m-%d")]
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
            if f['status']['short'] not in ['NS', 'TBD']: continue
            match_timestamp = f.get('timestamp', 0)
            match_time_str = datetime.fromtimestamp(match_timestamp, tz=timezone.utc).astimezone(italy_tz).strftime('%d/%m %H:%M') if match_timestamp > 0 else "N/D"
            
            home = m['teams']['home']['name']
            away = m['teams']['away']['name']
            league_name = m['league']['name']
            country = m['league']['country']
            f_id = f['id']
            
            odds_str = odds_dict.get(f_id, "Quote in aggiornamento")
            match_line = f"[{match_time_str}] {home} vs {away} | L: {league_name} ({country}) | Quote: {odds_str}"
            
            is_elite = any(kw in league_name.lower() for kw in elite_keywords) or country.lower() in ["italy", "england", "spain", "germany", "france", "europe"]
            
            if is_elite: elite_matches.append(match_line)
            else: global_matches.append(match_line)
            
        combined_data = "--- PALINSESTO ELITE ---\n" + ("\n".join(elite_matches) if elite_matches else "Nessun match elite.") + "\n\n--- PALINSESTO GLOBALE ---\n" + "\n".join(global_matches[:60])
        return combined_data, None
    except Exception as e: return None, str(e)

# --- LOGICA DI SALVATAGGIO E REPORT ---
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

# --- MOTORE QUANTISTICO CON SELEZIONE DINAMICA ---
def get_best_available_model(client) -> str:
    """Interroga dinamicamente Groq per trovare un modello valido ed eviterà blocchi da deprecazione."""
    try:
        models = client.models.list()
        # Cerca prima un modello versatile da 70b
        for m in models.data:
            if "70b" in m.id and "versatile" in m.id:
                return m.id
        # Se non lo trova, prende il primo modello Llama disponibile
        for m in models.data:
            if "llama" in m.id:
                return m.id
        # Fallback estremo sul primo modello in lista
        if models.data:
            return models.data[0].id
    except Exception:
        pass
    return "llama-3.3-70b-versatile" # Ancora di salvataggio statica

def run_quant_engine(match_data: str, api_key: str) -> str:
    if not api_key:
        return "❌ ERRORE: La tua GROQ_API_KEY è vuota nei secrets di Streamlit."
    
    try:
        client = Groq(api_key=api_key.strip())
        selected_model = get_best_available_model(client)
        
        system_prompt = (
            "Sei il 'Quant Engine Alpha', IA per analisi sportiva istituzionale. "
            "REQUISITO: Indipendentemente dal modello, fornisci SEMPRE per 5 eventi: Match, Classe Esito, Quota, Motivazione Statistica."
            "STRUTTURA: 1. Strategia Global Daily, 2. Strategia Elite. Concludi con Confidence Score e Protocollo di Rischio."
        )
        safe_match_data = match_data[:3500] if match_data else "Nessun dato."
        user_prompt = f"Ecco i dati:\n{safe_match_data}\nGenera due strategie con esiti completi."

        response = client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.1
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ ERRORE CRITICO GROQ: {str(e)}"

# --- UI STREAMLIT ---
st.title("⚙️ Bet-Pro | Quant Engine Alpha")

if st.button("🚀 Inizializza Motore Quantistico", type="primary"):
    with st.spinner("Estrazione e Analisi Quantistica in corso..."):
        data, err = fetch_fixtures_and_odds(API_FOOTBALL_KEY)
        if err: st.error(err)
        else:
            result = run_quant_engine(data, GROQ_API_KEY)
            st.session_state["analysis_result"] = result
            if "❌" not in result:
                save_bet_to_history({"date": datetime.now(), "result": result})

if st.session_state.get("analysis_result"):
    st.markdown(st.session_state["analysis_result"])

# Sidebar con funzioni avanzate
st.sidebar.markdown("---")
if st.sidebar.button("📧 Invia Report Settimanale"):
    st.sidebar.info(send_weekly_report())

if os.path.exists(HISTORY_FILE):
    st.sidebar.subheader("📊 Storico Recente")
    st.sidebar.dataframe(pd.read_csv(HISTORY_FILE).tail(3))
