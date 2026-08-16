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
    """Esegue il fetch live della pagina delle partite di OneFootball ed estrae i match."""
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
        
        # Tentativo di estrazione dal JSON interno di Next.js (__NEXT_DATA__)
        script_tag = soup.find('script', id='__NEXT_DATA__')
        extracted_text = []
        
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                def extract_matches(obj):
                    if isinstance(obj, dict):
                        if 'homeTeam' in obj and 'awayTeam' in obj:
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
        
        # Fallback sui tag HTML visibili se il JSON non è accessibile direttamente
        if not extracted_text:
            for tag in soup.find_all(['span', 'div', 'a'], class_=lambda x: x and ('match' in x.lower() or 'team' in x.lower() or 'title' in x.lower())):
                txt = tag.get_text(strip=True)
                if txt and len(txt) < 50 and txt not in extracted_text:
                    extracted_text.append(txt)
        
        if extracted_text:
            return "\n".join(extracted_text[:120]), None
        
        return soup.get_text(separator="\n", strip=True)[:4000], None

    except Exception as e:
        return None, str(e)


def run_ai_analysis(match_data: str, api_key: str) -> str:
    """Elabora l'analisi quantitativa tramite l'IA di Groq."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = Groq(api_key=api_key.strip())
        
        system_prompt = (
            "Sei un analista quantitativo e bookmaker professionista, specializzato in scommesse sportive. "
            "Hai una conoscenza enciclopedica del calcio mondiale, dei regolamenti dei tornei "
            "(distinguendo rigorosamente tra Coppe a eliminazione diretta e campionati) e delle dinamiche di palinsesto."
        )
        
        user_prompt = f"""Ecco i dati grezzi estratti in tempo reale da OneFootball (https://onefootball.com/it/partite):
-----------------
{match_data}
-----------------

Istruzioni tassative:
1. Analizza i dati sopra per identificare le partite di calcio reali in programma oggi, dividendole correttamente per competizione (coppe o campionati).
2. Per OGNI partita identificata, genera una scheda tecnica strutturata rigorosamente in Markdown con questo formato esatto:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione])
* **Contesto Tattico & Formula:** (Analisi di forma e specificando se è gara secca, andata/ritorno o campionato)
* **Classi di Esito:**
  * **Conservativa (Basso Rischio):** [Es. Passaggio Turno / 1X / Doppia Chance]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Gol-NoGol / Under-Over 2.5]
  * **Speculativa (Alto Rischio):** [Es. Combo / Multigol preciso]
* **Cluster Risultati Esatti Coerenti:** [3 risultati esatti maggiormente probabilistici]

Mantieni un tono rigoroso, professionale e privo di invenzioni."""

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
st.caption("Sincronizzazione live da OneFootball e analisi quantitativa avanzata con Llama 3.3.")

st.markdown("---")

st.subheader("🎯 Gestione Palinsesto Live")
st.write("Premi il pulsante sottostante per leggere in automatico le partite odierne da OneFootball ed eseguire l'analisi quantitativa completa.")

if st.button("🚀 Sincronizza OneFootball e Avvia Analisi", type="primary", use_container_width=True):
    with st.spinner("Connessione a OneFootball in corso..."):
        raw_data, err = scrape_onefootball()
        
        if err or not raw_data:
            st.error(f"Impossibile completare la lettura del sito: {err}")
        else:
            with st.spinner("L'IA sta elaborando l'analisi incrociata e i pronostici dei match..."):
                result = run_ai_analysis(raw_data, GROQ_API_KEY)
                st.session_state["analysis_result"] = result

if st.session_state["analysis_result"]:
    st.markdown("---")
    st.subheader("📋 Risultati dell'Analisi Quantitativa")
    st.markdown(st.session_state["analysis_result"])
    
