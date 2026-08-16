import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
from groq import Groq

st.set_page_config(page_title="Bet-Pro | OneFootball AI Sync", page_icon="📊", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = ""


def scrape_onefootball():
    """Esegue il fetch live e filtra escludendo le partite già terminate."""
    url = "https://onefootball.com/it/partite"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"Errore HTTP {response.status_code}"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        script_tag = soup.find('script', id='__NEXT_DATA__')
        extracted_text = []
        
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                def extract_matches(obj):
                    if isinstance(obj, dict):
                        if 'homeTeam' in obj and 'awayTeam' in obj:
                            # Controlla lo stato della partita per scartare quelle finite
                            status = str(obj.get('matchStatus', obj.get('status', obj.get('matchState', '')))).lower()
                            if any(term in status for term in ['finished', 'ft', 'ended', 'conclusa', 'terminata', 'full-time', 'closed']):
                                return # Salta la partita se è già finita
                            
                            home = obj['homeTeam'].get('name', '') if isinstance(obj['homeTeam'], dict) else str(obj['homeTeam'])
                            away = obj['awayTeam'].get('name', '') if isinstance(obj['awayTeam'], dict) else str(obj['awayTeam'])
                            comp = obj.get('competition', {}).get('name', '') if isinstance(obj.get('competition'), dict) else ''
                            
                            if home and away:
                                extracted_text.append(f"{home} vs {away} ({comp})")
                        for k, v in obj.items():
                            extract_matches(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            extract_matches(item)
                
                extract_matches(data)
            except Exception:
                pass
        
        if extracted_text:
            # Rimuove eventuali duplicati mantenendo l'ordine
            seen = set()
            unique_matches = [m for m in extracted_text if not (m in seen or seen.add(m))]
            return "\n".join(unique_matches[:100]), None
        
        return soup.get_text(separator="\n", strip=True)[:4000], None

    except Exception as e:
        return None, str(e)


def run_ai_analysis(match_data: str, api_key: str) -> str:
    """Elabora l'analisi quantitativa filtrando rigorosamente solo i match da giocare o live."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = Groq(api_key=api_key.strip())
        
        system_prompt = (
            "Sei un analista quantitativo e bookmaker professionista, specializzato in scommesse sportive. "
            "REGOLA CRITICA SUL TEMPO: Ignora e scarta assolutamente qualsiasi partita che risulta già conclusa o terminata. "
            "Analizza ESCLUSIVAMENTE le partite ancora da disputare o in corso di svolgimento."
        )
        
        user_prompt = f"""Ecco i dati grezzi estratti in tempo reale da OneFootball:
-----------------
{match_data}
-----------------

Istruzioni tassative:
1. Filtra ed escludi qualsiasi match già terminato nel corso della giornata. Considera solo quelli futuri o live.
2. Per OGNI partita valida identificata, genera una scheda tecnica strutturata rigorosamente in Markdown con questo formato esatto:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione esatta])
* **Contesto Tattico & Formula:** (Analisi di forma e specificando se è campionato o coppa a eliminazione diretta).
* **Classi di Esito (Pronostici concreti):**
  * **Conservativa (Basso Rischio):** [Es. 1X / X2 / DNB Casa / Under 3.5]
  * **Principale (Medio Rischio):** [Es. Segno 1 / Segno 2 / Gol / Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo Segno 1 + Over 1.5 / Multigol 2-4]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono rigoroso, professionale e privo di match passati."""

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

st.title("📊 Bet-Pro | OneFootball AI Sync")
st.caption("Sincronizzazione live da OneFootball con filtro anti-match terminati.")

st.markdown("---")

st.subheader("🎯 Gestione Palinsesto Live")
st.write("Premi il pulsante sottostante per sincronizzare i match odierni escludendo quelli già conclusi.")

if st.button("🚀 Sincronizza OneFootball e Avvia Analisi", type="primary", use_container_width=True):
    with st.spinner("Connessione e filtraggio palinsesto in corso..."):
        raw_data, err = scrape_onefootball()
        
        if err or not raw_data:
            st.error(f"Impossibile completare la lettura del sito: {err}")
        else:
            with st.spinner("L'IA sta elaborando l'analisi quantitativa dei match validi..."):
                result = run_ai_analysis(raw_data, GROQ_API_KEY)
                st.session_state["analysis_result"] = result

if st.session_state["analysis_result"]:
    st.markdown("---")
    st.subheader("📋 Risultati dell'Analisi Quantitativa")
    st.markdown(st.session_state["analysis_result"])
    
