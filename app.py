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

# --- LOGICA DI FETCHING A CASCATA (ZERO ERRORI / ZERO PALINSESTO VUOTO) ---
def fetch_fixtures_and_odds(api_key: str):
    if not api_key: 
        return None, "❌ Errore: API_FOOTBALL_KEY non configurata nei Secrets."
    try:
        italy_tz = timezone(timedelta(hours=2))
        oggi_dt = datetime.now(italy_tz)
        
        date_from = oggi_dt.strftime("%Y-%m-%d")
        date_to = (oggi_dt + timedelta(days=7)).strftime("%Y-%m-%d")
        
        headers = {"x-rapidapi-host": "v3.football.api-sports.io", "x-rapidapi-key": api_key.strip()}
        all_fixtures = []
        
        # TENTATIVO 1: Intervallo date (Oggi -> +7 giorni)
        url_range = f"https://v3.football.api-sports.io/fixtures?from={date_from}&to={date_to}"
        try:
            resp = requests.get(url_range, headers=headers, timeout=10)
            if resp.status_code == 200:
                all_fixtures = resp.json().get("response", [])
        except Exception:
            pass
            
        # TENTATIVO 2: Se vuoto, usa l'endpoint ?next=50 per forzare il recupero dei prossimi match
        if not all_fixtures:
            url_next = "https://v3.football.api-sports.io/fixtures?next=50"
            try:
                resp = requests.get(url_next, headers=headers, timeout=10)
                if resp.status_code == 200:
                    all_fixtures = resp.json().get("response", [])
            except Exception:
                pass

        if not all_fixtures:
            return None, "⚠️ Impossibile recuperare partite dal palinsesto. Verifica la chiave API o la quota disponibile."

        elite_matches = []
        global_matches = []
        elite_keywords = ["serie a", "serie b", "coppa italia", "supercoppa", "champions league", "europa league", "conference league", "premier league", "la liga", "bundesliga", "ligue 1"]

        # Filtro flessibile: se ci sono match con stato 'NS' o 'TBD' li usiamo, altrimenti prendiamo tutto ciò che arriva per evitare blocchi
        filtered_fixtures = [m for m in all_fixtures if m.get('fixture', {}).get('status', {}).get('short') in ['NS', 'TBD']]
        if not filtered_fixtures:
            filtered_fixtures = all_fixtures  # Fallback di sicurezza estrema

        for m in filtered_fixtures:
            f = m['fixture']
            match_timestamp = f.get('timestamp', 0)
            match_time_str = datetime.fromtimestamp(match_timestamp, tz=timezone.utc).astimezone(italy_tz).strftime('%d/%m %H:%M') if match_timestamp > 0 else "N/D"
            
            home = m.get('teams', {}).get('home', {}).get('name', 'Casa')
            away = m.get('teams', {}).get('away', {}).get('name', 'Ospite')
            league_data = m.get('league', {})
            league_name = league_data.get('name', 'Campionato')
            country = league_data.get('country', 'Internazionale')
            f_id = f.get('id')
            
            # Recupero quote associate (opzionale con fallback rapido)
            odds_str = "Quote da stimare tramite modelli ELO/Poisson"
            if f_id:
                try:
                    url_o = f"https://v3.football.api-sports.io/odds?fixture={f_id}&bookmaker=8"
                    resp_o = requests.get(url_o, headers=headers, timeout=3)
                    if resp_o.status_code == 200:
                        odds_raw = resp_o.json().get("response", [])
                        if odds_raw:
                            bets = odds_raw[0].get("bookmakers", [{}])[0].get("bets", [])
                            winner = next((b for b in bets if b.get("id") == 1), None)
                            if winner and len(winner.get("values", [])) >= 3:
                                v = winner["values"]
                                odds_str = f"1: {v[0]['odd']} | X: {v[1]['odd']} | 2: {v[2]['odd']}"
                except Exception:
                    pass

            match_line = f"[{match_time_str}] {home} vs {away} | L: {league_name} ({country}) | Quote: {odds_str}"
            
            is_elite = any(kw in league_name.lower() for kw in elite_keywords) or country.lower() in ["italy", "england", "spain", "germany", "france", "europe"]
            
            if is_elite:
                elite_matches.append(match_line)
            else:
                global_matches.append(match_line)
        
        combined_data = "--- PALINSESTO ELITE (ITALIA & EUROPA / COPPE) ---\n"
        combined_data += "\n".join(elite_matches) if elite_matches else "Nessun match elite diretto nel periodo, utilizza la selezione globale."
        combined_data += "\n\n--- PALINSESTO GLOBALE ---\n" + "\n".join(global_matches[:70])
        
        return combined_data, None
    except Exception as e: 
        return None, f"❌ Errore critico nel fetching: {str(e)}"

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
        return "❌ ERRORE: GROQ_API_KEY non presente nei Secrets."
        
    client = Groq(api_key=api_key.strip())
    
    system_prompt = (
        "Sei il 'Quant Engine Alpha', un'analisi sportiva istituzionale.\n"
        "REQUISITO FONDAMENTALE: Utilizza ESCLUSIVAMENTE i dati reali delle partite presenti nel palinsesto fornito. È severamente vietato inventare o simulare match.\n\n"
        "STRUTTURA RIGIDA DI OUTPUT:\n"
        "1. **STRATEGIA 1: Schedina Global Daily 50€** (Eventi basati sul palinsesto globale).\n"
        "2. **STRATEGIA 2: Specchietto Dedicato Elite (Italiane & Principali Europee / Coppe)** (Eventi focalizzati su Serie A, Coppe e Top Club).\n\n"
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
    with st.spinner("Estrazione Palinsesto Reale in corso..."):
        data, err = fetch_fixtures_and_odds(API_FOOTBALL_KEY)
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
    
