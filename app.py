import streamlit as st
import requests
from bs4 import BeautifulSoup
from groq import Groq

st.set_page_config(page_title="Bet-Pro | Analista Scommesse IA", page_icon="📊", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = ""

if "raw_palinsesto" not in st.session_state:
    st.session_state["raw_palinsesto"] = ""


def scrape_onefootball():
    """Tenta il recupero live dei match."""
    url = "https://onefootball.com/it/partite"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        valid_matches = []
        
        for line in soup.get_text(separator="\n", strip=True).split("\n"):
            if " - " in line or " vs " in line:
                if 5 < len(line.strip()) < 80:
                    valid_matches.append(line.strip())

        unique_matches = list(dict.fromkeys(valid_matches))
        if unique_matches:
            return "\n".join(unique_matches[:60])
        
        return None
    except Exception:
        return None


def run_ai_analysis(match_data: str, api_key: str) -> str:
    """Elabora l'analisi quantitativa escludendo rigorosamente i match conclusi."""
    if not api_key:
        return "❌ Errore: GROQ_API_KEY non presente nei Secrets di Streamlit."

    try:
        client = Groq(api_key=api_key.strip())
        
        system_prompt = (
            "Sei un analista quantitativo e bookmaker professionista, specializzato in scommesse sportive. "
            "REGOLA TEMPORALE TASSATIVA: Scarta assolutamente qualsiasi partita già terminata o conclusa. "
            "Analizza ESCLUSIVAMENTE le partite ancora da disputare o in corso."
        )
        
        user_prompt = f"""Palinsesto di riferimento:
-----------------
{match_data}
-----------------

Istruzioni tassative:
1. Estrai solo le partite reali ancora da giocare, scartando scorie e risultati finali.
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

st.title("📊 Bet-Pro | Analista Scommesse IA")
st.caption("Sistema di sincronizzazione e analisi quantitativa avanzata.")

st.markdown("---")
st.subheader("🎯 Gestione Palinsesto Live")

# Tentativo di sincronizzazione automatica al click
if st.button("🚀 Sincronizza OneFootball e Avvia Analisi", type="primary", use_container_width=True):
    with st.spinner("Connessione ai feed in corso..."):
        scraped_data = scrape_onefootball()
        
        if scraped_data:
            st.session_state["raw_palinsesto"] = scraped_data
            with st.spinner("Analisi quantitativa dei match in corso..."):
                st.session_state["analysis_result"] = run_ai_analysis(scraped_data, GROQ_API_KEY)
        else:
            st.warning("⚠️ Il sito ha applicato restrizioni anti-bot alla lettura diretta. Inserisci o conferma il palinsesto qui sotto per procedere all'istante:")

# Box di sicurezza sempre disponibile per inserire/confermare i match in caso di protezione del sito
user_input_palinsesto = st.text_area(
    "Partite del giorno (puoi incollare o modificare il palinsesto):",
    value=st.session_state["raw_palinsesto"],
    placeholder="Es: Frosinone vs Juve Stabia, Genoa vs Ascoli...",
    height=100
)

if st.button("📊 Elabora Analisi da Testo/Palinsesto", use_container_width=True):
    if not user_input_palinsesto.strip():
        st.warning("Inserisci le partite da analizzare.")
    elif not GROQ_API_KEY:
        st.error("Configura GROQ_API_KEY nei Secrets di Streamlit.")
    else:
        with st.spinner("L'IA sta elaborando l'analisi quantitativa..."):
            st.session_state["analysis_result"] = run_ai_analysis(user_input_palinsesto, GROQ_API_KEY)

if st.session_state["analysis_result"]:
    st.markdown("---")
    st.subheader("📋 Risultati dell'Analisi Quantitativa")
    st.markdown(st.session_state["analysis_result"])
    
