import streamlit as st
import requests
from bs4 import BeautifulSoup
from groq import Groq

st.set_page_config(page_title="Bet-Pro | OneFootball AI Sync", page_icon="📊", layout="centered")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = ""


def scrape_onefootball():
    """Esegue il fetch live e isola solo le partite future o con orario valido."""
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
        
        valid_matches = []
        
        # Cerca i contenitori dei match o le celle degli eventi nel DOM di OneFootball
        # Di solito le partite sono all'interno di elementi specifici o link con nomi squadre
        match_elements = soup.find_all(['div', 'a'], class_=lambda x: x and any(c in x.lower() for c in ['match', 'event', 'cell', 'score']))
        
        for el in match_elements:
            text = el.get_text(separator=" | ", strip=True)
            # Filtra per elementi che contengono una struttura "Squadra vs Squadra" o indicatori di orario (es. cifre con i due punti come 20:45)
            if " vs " in text or " - " in text:
                # Esclude righe palesemente concluse o testi di servizio
                lower_text = text.lower()
                if any(term in lower_text for term in ['fin', 'ft', 'terminata', 'conclusa', '1-', '2-', '3-']):
                    # Se contiene uno score numerico tipico di fine partita, lo scartiamo a meno che non ci sia un orario futuro
                    if not any(hour in text for hour in [":00", ":15", ":30", ":45"]):
                        continue
                
                if len(text) < 150 and text not in valid_matches:
                    valid_matches.append(text)
        
        # Fallback di sicurezza se i selettori mirati non restituiscono abbastanza righe
        if not valid_matches:
            for line in soup.get_text(separator="\n", strip=True).split("\n"):
                if " - " in line or " vs " in line:
                    if len(line.strip()) > 5 and len(line.strip()) < 80:
                        valid_matches.append(line.strip())

        unique_matches = list(dict.fromkeys(valid_matches))
        
        if unique_matches:
            return "\n".join(unique_matches[:80]), None
        
        return None, "Nessuna partita valida trovata nella pagina."

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
            "REGOLA TEMPORALE TASSATIVA: Devi scartare assolutamente qualsiasi match già terminato, concluso o che mostra un risultato finale. "
            "Seleziona ed elabora ESCLUSIVAMENTE le partite che devono ancora iniziare o che hanno un orario futuro nella giornata odierna."
        )
        
        user_prompt = f"""Ecco i dati grezzi estratti da OneFootball:
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
st.caption("Sincronizzazione live da OneFootball con controllo orario e filtro partite concluse.")

st.markdown("---")

st.subheader("🎯 Gestione Palinsesto Live")
st.write("Premi il pulsante per sincronizzare i match odierni escludendo quelli già archiviati.")

if st.button("🚀 Sincronizza OneFootball e Avvia Analisi", type="primary", use_container_width=True):
    with st.spinner("Connessione e filtraggio orari in corso..."):
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
    
