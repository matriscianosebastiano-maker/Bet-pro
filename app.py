import streamlit as st
import requests
from datetime import datetime, timezone, timedelta
from groq import Groq

st.set_page_config(page_title="Bet-Pro | Progetto Extra Money", page_icon="📈", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
API_FOOTBALL_KEY = st.secrets.get("API_FOOTBALL_KEY", "")

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = ""

def fetch_fixtures_and_odds(api_key: str):
    """Recupera l'intero palinsesto mondiale e le quote Bet365 per la scansione globale."""
    if not api_key:
        return None, "❌ Errore: API_FOOTBALL_KEY non configurata nei secrets."

    try:
        italy_tz = timezone(timedelta(hours=2))
        oggi_italia = datetime.now(italy_tz)
        today_str = oggi_italia.strftime("%Y-%m-%d")
        
        headers = {
            "x-rapidapi-host": "v3.football.api-sports.io",
            "x-rapidapi-key": api_key
        }
        
        # 1. Recupero Partite Globali del Giorno
        url_fixtures = "https://v3.football.api-sports.io/fixtures"
        resp_fixtures = requests.get(url_fixtures, headers=headers, params={"date": today_str}, timeout=15)
        if resp_fixtures.status_code != 200:
            return None, f"Errore API Fixtures (HTTP {resp_fixtures.status_code})"
        
        fixtures_data = resp_fixtures.json().get("response", [])
        
        # 2. Recupero Quote (Bookmaker 8 = Bet365) per il palinsesto mondiale
        url_odds = "https://v3.football.api-sports.io/odds"
        resp_odds = requests.get(url_odds, headers=headers, params={"date": today_str, "bookmaker": 8}, timeout=15)
        odds_data = resp_odds.json().get("response", [])
        
        odds_dict = {}
        for odd_item in odds_data:
            fix_id = odd_item.get("fixture", {}).get("id")
            bookmakers = odd_item.get("bookmakers", [])
            if fix_id and bookmakers:
                bets = bookmakers[0].get("bets", [])
                match_winner_odds = next((bet for bet in bets if bet.get("id") == 1), None)
                if match_winner_odds:
                    values = match_winner_odds.get("values", [])
                    if len(values) >= 3:
                        odds_dict[fix_id] = f"1: {values[0]['odd']} | X: {values[1]['odd']} | 2: {values[2]['odd']}"

        valid_matches = []
        current_timestamp = int(datetime.now().timestamp())
        
        for match in fixtures_data:
            fixture = match.get("fixture", {})
            fix_id = fixture.get("id")
            teams = match.get("teams", {})
            league = match.get("league", {})
            
            match_timestamp = fixture.get("timestamp", 0)
            status_short = fixture.get("status", {}).get("short", "")
            
            if match_timestamp <= current_timestamp or status_short not in ["NS", "TBD"]:
                continue
                
            home = teams.get("home", {}).get("name", "Sconosciuta")
            away = teams.get("away", {}).get("name", "Sconosciuta")
            league_name = league.get("name", "Competizione Sconosciuta")
            country = league.get("country", "Mondo")
            
            match_dt_utc = datetime.fromtimestamp(match_timestamp, tz=timezone.utc)
            match_dt_italy = match_dt_utc.astimezone(italy_tz)
            match_time = match_dt_italy.strftime('%H:%M')
            
            match_odds = odds_dict.get(fix_id, "Quote non disponibili")
            
            valid_matches.append(f"[{match_time}] {home} vs {away} - {league_name} ({country}) | Quote: {match_odds}")
            
        if not valid_matches:
            return None, "Tutte le partite del palinsesto odierno sono concluse o non disponibili."
            
        return "\n".join(valid_matches[:60]), None

    except Exception as e:
        return None, f"Errore di sistema: {str(e)}"

def run_project_ai_analysis(match_data: str, api_key: str) -> str:
    """Modello focalizzato sulla 'Singola del Giorno' e sul piano di crescita da 30€/settimana."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente."

    try:
        client = Groq(api_key=api_key.strip())
        
        system_prompt = (
            "Sei il Lead Quantitative Strategist di un fondo di investimento sportivo orientato al progetto 'Extra Money'. "
            "L'utente ha un budget fisso di 30€ alla settimana (circa 4-5€ al giorno) e vuole **una sola giocata mirata al giorno** (Singola o Combo a bassissimo rischio) pescata dall'intero palinsesto mondiale. Niente schedine multiple o accumulatori a rischio.\n"
            "REGOLE TASSATIVE DEL PROGETTO:\n"
            "1. RICERCA DEL VALORE ASSOLUTO: Setaccia tutto il mondo (Europa, Americhe, Scandinavia, Est Europa) e individua l'UNICA vera imperfezione di mercato della giornata.\n"
            "2. MONEY MANAGEMENT SETTIMANALE: Con un budget di 30€ settimanali, stabilisci la puntata esatta (es. 4€ o 5€) per la singola selezionata.\n"
            "3. FOCUS SULLA CONTINUITÀ: Spiega in modo razionale e freddo perché quella partita ha il più alto valore atteso (EV+) rispetto a tutte le altre in programma.\n"
            "4. TONO PROFESSIONALE: Zero fuffa da tipster, parla solo il linguaggio dei dati, delle probabilità e della gestione del rischio."
        )
        
        user_prompt = f"""Ecco il palinsesto globale mondiale di oggi con le relative quote di mercato:
-----------------
{match_data}
-----------------

Istruzioni per l'output:
Seleziona **una e una sola** partita (la migliore in assoluto per il progetto Extra Money) ed elabora la strategia in questo formato Markdown:

### 🎯 La Singola del Giorno (Progetto Extra Money)
* **Match Selezionato:** [Squadra Casa] vs [Squadra Ospite] ([Competizione, Nazione]) - Ore [Orario]
* **Analisi Quantitativa & Motivazionale:** (Perché questa è l'occasione migliore del palinsesto mondiale odierno?)
* **Tipologia di Giocata (Value Bet):** [Es. Over 1.5 / 1X + Under 3.5 / Segno pulito] a Quota [Quota]
* **Gestione del Bankroll (Budget 30€/settimana):** 
  * 💰 **Puntata Consigliata per oggi:** [Es. 5.00€]
  * 📈 **Potenzialeritorno:** [Calcolo vincita lorda/netta]
* **Piano Operativo Settimanale:** (Un breve promemoria su come gestire la cassa e mantenere la disciplina nei prossimi giorni)." """

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.15
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Errore IA: {e}"

# ---------------- INTERFERCCIA ----------------

st.title("📈 Bet-Pro | Progetto Extra Money")
st.caption("Gestione Bankroll (30€/settimana) + Selezione Globale della 'Singola del Giorno'.")
st.markdown("---")

if st.button("🚀 Scansiona il Palinsesto Mondiale e Genera la Singola", type="primary", use_container_width=True):
    with st.spinner("Analisi globale dei campionati mondiali e delle quote in corso..."):
        raw_data, err = fetch_fixtures_and_odds(API_FOOTBALL_KEY)
        
        if err or not raw_data:
            st.error(err)
        else:
            with st.spinner("L'algoritmo sta calcolando l'opportunità a minor rischio per il tuo budget..."):
                result = run_project_ai_analysis(raw_data, GROQ_API_KEY)
                st.session_state["analysis_result"] = result

if st.session_state["analysis_result"]:
    st.markdown("---")
    st.subheader("📋 Report Strategico Giornaliero")
    st.markdown(st.session_state["analysis_result"])
    
