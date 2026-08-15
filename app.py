import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro AI | Miglior Risultato", page_icon="🎯", layout="wide")
st.title("🎯 Bet-Pro AI Engine | Selezione Miglior Giocata")
st.markdown("Analisi automatica del palinsesto multisport ed estrazione del **miglior risultato da giocare** elaborato dall'algoritmo IA.")

# --- GESTIONE CHIAVI API (Sidebar) ---
st.sidebar.header("⚙️ Configurazione Chiavi")
st.sidebar.markdown("Se riscontri errori di autenticazione, inserisci una chiave Gemini valida generata da [Google AI Studio](https://aistudio.google.com/).")
gemini_input_key = st.sidebar.text_input("Inserisci Gemini API Key", type="password")

api_key = None
if gemini_input_key:
    api_key = gemini_input_key
else:
    try:
        api_key = st.secrets["GEMINI_KEY"]
    except Exception:
        pass

# --- MOTORE DI RECUPERO DATI MULTISPORT DA ESPN ---
@st.cache_data(ttl=300)
def fetch_all_sports_schedules():
    endpoints = [
        {"sport": "soccer", "league": "ita.1", "name": "Serie A (Calcio)"},
        {"sport": "soccer", "league": "eng.1", "name": "Premier League (Calcio)"},
        {"sport": "soccer", "league": "esp.1", "name": "La Liga (Calcio)"},
        {"sport": "soccer", "league": "ger.1", "name": "Bundesliga (Calcio)"},
        {"sport": "soccer", "league": "uefa.champions", "name": "Champions League (Calcio)"},
        {"sport": "basketball", "league": "nba", "name": "NBA (Basket)"},
        {"sport": "tennis", "league": "atp", "name": "Tennis ATP"},
        {"sport": "football", "league": "nfl", "name": "NFL (Football Americano)"}
    ]
    
    all_matches = []
    
    for ep in endpoints:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{ep['sport']}/{ep['league']}/scoreboard"
        try:
            response = requests.get(url, timeout=4)
            if response.status_code == 200:
                data = response.json()
                events = data.get("events", [])
                for event in events:
                    match_name = event.get("name")
                    match_date = event.get("date")
                    status = event.get("status", {}).get("type", {}).get("description", "Programmato")
                    
                    competitions = event.get("competitions", [{}])[0]
                    competitors = competitions.get("competitors", [])
                    
                    home_team, away_team = "Home", "Away"
                    for c in competitors:
                        if c.get("homeAway") == "home":
                            home_team = c.get("team", {}).get("displayName", "Home")
                        elif c.get("homeAway") == "away":
                            away_team = c.get("team", {}).get("displayName", "Away")
                            
                    all_matches.append({
                        "Sport / Lega": ep["name"],
                        "Match": f"{home_team} vs {away_team}" if home_team != "Home" else match_name,
                        "Data": match_date[:10] if match_date else "N/A",
                        "Stato": status
                    })
        except Exception:
            continue
            
    return pd.DataFrame(all_matches)

# --- INTERFACCIA PRINCIPALE ---
if st.button("🚀 Sincronizza & Calcola il Miglior Pronostico da Giocare", use_container_width=True, type="primary"):
    if not api_key:
        st.error("⚠️ Inserisci una chiave API di Gemini valida nella barra laterale (Sidebar a sinistra) per procedere con l'analisi.")
    else:
        with st.spinner("Sincronizzazione feed sportivi globali in corso..."):
            df_events = fetch_all_sports_schedules()
            
        if df_events.empty:
            st.warning("Nessun evento disponibile al momento sui server.")
        else:
            st.success(f"✅ Sincronizzazione completata: trovati {len(df_events)} eventi attivi.")
            
            # Elaborazione IA per estrarre la giocata ottimale
            with st.spinner("L'intelligenza artificiale sta analizzando le probabilità per selezionare il miglior risultato da giocare..."):
                try:
                    genai.configure(api_key=api_key)
                    ai_model = genai.GenerativeModel('gemini-1.5-flash')
                    
                    sample_data = df_events.head(30).to_string()
                    prompt = f"""
                    Agisci come un Quantitative Sports Trader professionista.
                    Analizza il seguente palinsesto di eventi sportivi attivi:
                    
                    {sample_data}
                    
                    Il tuo compito è elaborare e restituire ESCLUSIVAMENTE la selezione con il valore statistico più alto.
                    Struttura la risposta in questo modo esatto:
                    
                    ### 🏆 TOP BET CONSIGLIATA (Miglior Risultato da Giocare)
                    - **Match Selezionato:** [Inserisci il match]
                    - **Sport / Lega:** [Inserisci la lega]
                    - **Esito Matematico Consigliato:** [Es. 1, X2, Over 2.5, ecc.]
                    - **Indice di Confidenza:** [Es. Alta / 90%]
                    - **Analisi e Motivazione Algoritmica:** [Spiegazione tecnica sintetica del perché questo è il miglior evento su cui puntare]
                    
                    ### 📋 Altre Occasioni di Valore
                    (Crea una breve tabella con altri 3 match di spicco e i relativi esiti consigliati).
                    """
                    
                    response = ai_model.generate_content(prompt)
                    if response and hasattr(response, 'text'):
                        st.markdown(response.text)
                except Exception as e:
                    st.error(f"⚠️ Errore di autenticazione o generazione IA: {e}")
                    st.info("💡 Suggerimento: Verifica che la chiave API inserita nella barra laterale sia corretta e attiva.")
            
            st.divider()
            st.subheader("📋 Dataset Completo Eventi Sincronizzati")
            st.dataframe(df_events, use_container_width=True, hide_index=True)
            
