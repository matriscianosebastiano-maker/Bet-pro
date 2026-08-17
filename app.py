import streamlit as st
import requests
from datetime import datetime
from groq import Groq

st.set_page_config(page_title="Bet-Pro | Analisi Quantitativa Avanzata", page_icon="📈", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
API_FOOTBALL_KEY = st.secrets.get("API_FOOTBALL_KEY", "") # Aggiungi questa chiave nei secrets

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = ""

def fetch_global_fixtures(api_key: str):
    """Recupera TUTTE le partite mondiali del giorno tramite API-Football e applica un filtro temporale assoluto."""
    if not api_key:
        return None, "❌ Errore: API_FOOTBALL_KEY non configurata nei secrets."

    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        url = "https://v3.football.api-sports.io/fixtures"
        querystring = {"date": today_str}
        
        headers = {
            "x-rapidapi-host": "v3.football.api-sports.io",
            "x-rapidapi-key": api_key
        }
        
        response = requests.get(url, headers=headers, params=querystring, timeout=15)
        
        if response.status_code != 200:
            return None, f"Errore API-Football (HTTP {response.status_code})"
            
        data = response.json()
        matches = data.get("response", [])
        
        if not matches:
            return None, "Nessuna partita in programma per oggi nel database mondiale."
            
        valid_matches = []
        current_timestamp = int(datetime.now().timestamp())
        
        for match in matches:
            fixture = match.get("fixture", {})
            teams = match.get("teams", {})
            league = match.get("league", {})
            
            match_timestamp = fixture.get("timestamp", 0)
            status_short = fixture.get("status", {}).get("short", "")
            
            # FILTRO LOGICO TEMPORALE: 
            # Scarta matematicamente qualsiasi match il cui orario d'inizio è nel passato,
            # oppure che ha uno stato diverso da "Not Started" (NS) o "Time to be Defined" (TBD).
            if match_timestamp <= current_timestamp or status_short not in ["NS", "TBD"]:
                continue
                
            home = teams.get("home", {}).get("name", "Sconosciuta")
            away = teams.get("away", {}).get("name", "Sconosciuta")
            league_name = league.get("name", "Competizione Sconosciuta")
            country = league.get("country", "Mondo")
            
            # Formatta l'orario per il prompt
            match_time = datetime.fromtimestamp(match_timestamp).strftime('%H:%M')
            
            valid_matches.append(f"[{match_time}] {home} vs {away} - {league_name} ({country})")
            
        if not valid_matches:
            return None, "Tutte le partite del palinsesto odierno sono già iniziate o concluse."
            
        # Per evitare limiti di token sull'IA, limitiamo ai 100 match più imminenti
        return "\n".join(valid_matches[:100]), None

    except Exception as e:
        return None, f"Errore di sistema: {str(e)}"

def run_advanced_ai_analysis(match_data: str, api_key: str) -> str:
    """Elabora i pronostici applicando logica matematica e asimmetria motivazionale."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente."

    try:
        client = Groq(api_key=api_key.strip())
        
        system_prompt = (
            "Sei un analista quantitativo di livello senior e un algoritmo di betting predittivo. "
            "Il tuo compito non è indovinare chi vince, ma calcolare le probabilità matematiche e identificare il valore atteso (EV). "
            "REGOLE DI PENSIERO LOGICO COMPLESSO:\n"
            "1. ASIMMETRIA MOTIVAZIONALE: Valuta criticamente la competizione. Se è una coppa nazionale, considera il rischio turnover. Le squadre minori o in lotta per la salvezza tendono a sacrificare le coppe a favore del campionato.\n"
            "2. CONTESTO PSICOLOGICO E CALENDARIO: Ragiona sulle fatiche accumulate, sugli scontri diretti imminenti e sulla differenza di motivazioni tra le due squadre.\n"
            "3. NIENTE BANALITÀ: Evita le etichette vuote. Devi fornire ESCLUSIVAMENTE pronostici concreti basati su una ratio rischio/rendimento.\n"
            "4. SCARTA I MATCH FINITI: Analizza solo match futuri. Se per errore ricevi un match già in corso, ignoralo."
        )
        
        user_prompt = f"""Ecco il palinsesto mondiale completo dei match ANCORA DA GIOCARE oggi:
-----------------
{match_data}
-----------------

Istruzioni Operative:
Per OGNI partita, esegui il tuo ragionamento logico-matematico e genera la seguente scheda in Markdown:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione, Nazione]) - Ore [Orario]
* **Analisi Dinamica e Motivazionale:** (Spiega il tuo ragionamento logico: c'è rischio turnover? È una coppa minore? Chi ha più 'fame' di punti?)
* **Classi di Esito (Pronostici Matematici):**
  * **Copertura (Basso Rischio):** [Es. 1X e Under 3.5]
  * **Value Bet (Medio Rischio):** [Il pronostico con il miglior rapporto probabilità/quota, es. Goal o Segno 2]
  * **Speculativa (Alto Rischio):** [Es. Segno 1 + Over 2.5]
* **Cluster Risultati Esatti:** [I 3 risultati più allineati al tuo ragionamento logico]"""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2 # Leggermente alzato per permettere un ragionamento logico più flessibile
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Errore IA: {e}"

# ---------------- INTERFACCIA ----------------

st.title("📈 Bet-Pro | Motore Logico Avanzato")
st.caption("Palinsesto globale filtrato al secondo + Analisi su Asimmetria Motivazionale.")
st.markdown("---")

if st.button("🚀 Estrai Palinsesto Globale e Avvia Calcolo Logico", type="primary", use_container_width=True):
    with st.spinner("Sincronizzazione col database mondiale in corso (filtro orario attivo)..."):
        raw_data, err = fetch_global_fixtures(API_FOOTBALL_KEY)
        
        if err or not raw_data:
            st.error(err)
        else:
            with st.spinner("Il motore quantitativo sta elaborando le asimmetrie motivazionali..."):
                result = run_advanced_ai_analysis(raw_data, GROQ_API_KEY)
                st.session_state["analysis_result"] = result

if st.session_state["analysis_result"]:
    st.markdown("---")
    st.subheader("📋 Output Analitico Quantitativo")
    st.markdown(st.session_state["analysis_result"])
    
