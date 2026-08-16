import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
from groq import Groq

st.set_page_config(page_title="Bet-Pro | OneFootball AI Sync", page_icon="📊", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = ""


def scrape_onefootball():
    """Esegue il fetch live aggirando le protezioni anti-bot con cloudscraper."""
    url = "https://onefootball.com/it/partite"
    try:
        # Configura uno scraper che simula un browser reale e supera Cloudflare
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'firefox',
                'platform': 'windows',
                'desktop': True
            }
        )
        response = scraper.get(url, timeout=15)
        if response.status_code != 200:
            return None, f"Errore HTTP {response.status_code}"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        valid_matches = []
        
        # Estrae i blocchi di testo relativi alle partite dal DOM del sito
        for tag in soup.find_all(['span', 'div', 'a', 'p'], class_=lambda x: x and any(c in x.lower() for c in ['match', 'team', 'title', 'score', 'event'])):
            txt = tag.get_text(strip=True)
            if (" vs " in txt or " - " in txt) and 5 < len(txt) < 100:
                if txt not in valid_matches:
                    valid_matches.append(txt)
        
        # Fallback di lettura testuale generale se i selettori mirati non restituiscono abbastanza righe
        if not valid_matches:
            for line in soup.get_text(separator="\n", strip=True).split("\n"):
                if " - " in line or " vs " in line:
                    if 5 < len(line.strip()) < 80:
                        valid_matches.append(line.strip())

        unique_matches = list(dict.fromkeys(valid_matches))
        
        if unique_matches:
            return "\n".join(unique_matches[:80]), None
        
        return None, "Nessuna partita estratta dalla pagina."

    except Exception as e:
        return None, str(e)


def run_ai_analysis(match_data: str, api_key: str) -> str:
    """Elabora l'analisi quantitativa filtrando rigorosamente solo i match da disputare."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = Groq(api_key=api_key.strip())
        
        system_prompt = (
            "Sei un analista quantitativo e bookmaker professionista, specializzato in scommesse sportive. "
            "REGOLA TEMPORALE TASSATIVA: Scarta assolutamente qualsiasi partita già terminata o conclusa. "
            "Analizza ESCLUSIVAMENTE le partite ancora da disputare o in corso nella giornata odierna."
        )
        
        user_prompt = f"""Ecco i dati grezzi estratti in tempo reale da OneFootball:
-----------------
{match_data}
-----------------

Istruzioni tassative:
1. Estrai solo le partite reali ancora da giocare oggi, scartando scorie, risultati finali e testo non pertinente.
2. Per OGNI partita valida trovata, genera una scheda tecnica rigorosamente in Markdown con questo formato esatto:

### [Squadra Casa] vs [Squadra Ospite] ([Competizione])
* **Contesto Tattico & Formula:** (Analisi di forma e specificando se è campionato o coppa)
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
st.caption("Sincronizzazione live automatica e bypass anti-bot integrato.")

st.markdown("---")

st.subheader("🎯 Sincronizzazione Automatica Live")
st.write("Premi il pulsante per far leggere al bot il sito in autonomia, superare le protezioni ed eseguire l'analisi.")

if st.button("🚀 Sincronizza OneFootball e Avvia Analisi", type="primary", use_container_width=True):
    with st.spinner("Connessione e superamento protezione anti-bot in corso..."):
        raw_data, err = scrape_onefootball()
        
        if err or not raw_data:
            st.error(f"Impossibile leggere il sito in autonomia: {err}")
        else:
            with st.spinner("L'IA sta elaborando l'analisi quantitativa dei match validi..."):
                result = run_ai_analysis(raw_data, GROQ_API_KEY)
                st.session_state["analysis_result"] = result

if st.session_state["analysis_result"]:
    st.markdown("---")
    st.subheader("📋 Risultati dell'Analisi Quantitativa")
    st.markdown(st.session_state["analysis_result"])
