import streamlit as st
import requests
from datetime import datetime
from groq import Groq

st.set_page_config(page_title="Bet-Pro | Live Quant Analysis", page_icon="📊", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = ""


def fetch_live_fixtures():
    """Recupera le partite del giorno tramite API sportive pubbliche, 
    verificando lo stato e scartando i match già iniziati o conclusi."""
    try:
        # Utilizzo di un endpoint pubblico affidabile per il palinsesto calcistico giornaliero
        today_str = datetime.now().strftime("%Y-%m-%d")
        url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={today_str}&s=Soccer"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"Errore di connessione API (HTTP {response.status_code})"
        
        data = response.json()
        events = data.get("events", [])
        
        if not events:
            return None, "Nessuna partita trovata per la data odierna."
            
        valid_matches = []
        current_time = datetime.now()
        
        for ev in events:
            home = ev.get("strHomeTeam", "")
            away = ev.get("strAwayTeam", "")
            league = ev.get("strLeague", "")
            time_str = ev.get("strTime", "") # Formato es: 20:00:00
            status = ev.get("strStatus", "") # Stato del match (es. Match Finished, Not Started, ecc.)
            
            # Filtro temporale rigoroso: se la partita è già conclusa o in corso, la scartiamo
            lower_status = status.lower()
            if any(term in lower_status for term in ['ft', 'finished', 'closed', 'postponed', 'cancelled', '1h', '2h', 'ht', 'live']):
                continue
                
            # Controllo orario se disponibile
            if time_str:
                try:
                    match_time_obj = datetime.strptime(time_str[:5], "%H:%M")
                    # Confronto orario odierno (opzionale ma utile)
                except ValueError:
                    pass

            if home and away:
                valid_matches.append(f"{home} vs {away} ({league}) - Inizio previsto ore {time_str[:5] if time_str else 'Da definire'}")

        if not valid_matches:
            return None, "Tutte le partite odierne sono già iniziate o concluse."

        return "\n".join(valid_matches), None

    except Exception as e:
        return None, str(e)


def run_ai_analysis(match_data: str, api_key: str) -> str:
    """Elabora l'analisi quantitativa avanzata tramite Llama 3.3."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = Groq(api_key=api_key.strip())
        
        system_prompt = (
            "Sei un analista quantitativo e bookmaker professionista, specializzato in scommesse sportive. "
            "REGINA ASSOLUTA DEI PRONOSTICI: non devi MAI usare etichette o categorie vuote (come 'Esito 1X2' o 'Under/Over'). "
            "Devi indicare SEMPRE il pronostico concreto e specifico (es. Segno 1, Segno X, Segno 2, Gol, NoGol, Under 2.5, Over 2.5, ecc.). "
            "REGOLA TEMPORALE: Considera esclusivamente match futuri non ancora iniziati."
        )
        
        user_prompt = f"""Ecco il palinsesto ufficiale validato per oggi:
-----------------
{match_data}
-----------------

Istruzioni tassative:
1. Per OGNI partita valida presente nell'elenco, genera una scheda tecnica strutturata rigorosamente in Markdown con questo formato esatto:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione])
* **Contesto Tattico & Formula:** (Analisi di forma e specificando se è campionato o coppa)
* **Classi di Esito (Pronostici concreti):**
  * **Conservativa (Basso Rischio):** [Es. 1X / X2 / DNB Casa / Under 3.5]
  * **Principale (Medio Rischio):** [Es. Segno 1 / Segno 2 / Gol / Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo Segno 1 + Over 1.5 / Multigol 2-4]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono rigoroso, professionale e privo di etichette vuote."""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Errore durante l'elaborazione con l'IA: {e}"


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Live Quant Analysis")
st.caption("Sincronizzazione via API sportive con filtro orario e verifica stato match.")

st.markdown("---")

st.subheader("🎯 Gestione Palinsesto Live")
st.write("Premi il pulsante per interrogare i server sportivi in tempo reale, verificare gli orari ed eseguire l'analisi quantitativa.")

if st.button("🚀 Sincronizza Palinsesto e Avvia Analisi", type="primary", use_container_width=True):
    with st.spinner("Interrogazione feed sportivi in corso..."):
        raw_data, err = fetch_live_fixtures()
        
        if err or not raw_data:
            st.error(f"Impossibile completare la sincronizzazione: {err}")
        else:
            with st.spinner("L'IA sta elaborando l'analisi quantitativa dei match validi..."):
                result = run_ai_analysis(raw_data, GROQ_API_KEY)
                st.session_state["analysis_result"] = result

if st.session_state["analysis_result"]:
    st.markdown("---")
    st.subheader("📋 Risultati dell'Analisi Quantitativa")
    st.markdown(st.session_state["analysis_result"])
    
