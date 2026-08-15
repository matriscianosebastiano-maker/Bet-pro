import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bet-Pro AI | Palinsesto Multisport Globale", page_icon="🏅", layout="wide")
st.title("🏅 Bet-Pro AI Engine | Feed Multisport & Analisi Algoritmica")
st.markdown("Sistema integrato di acquisizione dati da tutti gli sport e campionati globali (ESPN Public Feed) con elaborazione pronostici IA.")

# --- GESTIONE CHIAVI API (Con fallback in Sidebar) ---
st.sidebar.header("⚙️ Configurazione Chiavi")
gemini_input_key = st.sidebar.text_input("Inserisci Gemini API Key", type="password")

api_key = None
if gemini_input_key:
    api_key = gemini_input_key
else:
    try:
        api_key = st.secrets["GEMINI_KEY"]
    except Exception:
        pass

if not api_key:
    st.sidebar.warning("⚠️ Inserisci la tua Gemini API Key per attivare l'analisi IA.")

# --- MOTORE DI RECUPERO DATI MULTISPORT DA ESPN ---
@st.cache_data(ttl=300)
def fetch_all_sports_schedules():
    # Elenco completo ed esteso di tutti gli sport e campionati disponibili su ESPN
    endpoints = [
        # Calcio Europeo e Internazionale
        {"sport": "soccer", "league": "ita.1", "name": "Serie A (Calcio)"},
        {"sport": "soccer", "league": "eng.1", "name": "Premier League (Calcio)"},
        {"sport": "soccer", "league": "esp.1", "name": "La Liga (Calcio)"},
        {"sport": "soccer", "league": "ger.1", "name": "Bundesliga (Calcio)"},
        {"sport": "soccer", "league": "fra.1", "name": "Ligue 1 (Calcio)"},
        {"sport": "soccer", "league": "uefa.champions", "name": "Champions League (Calcio)"},
        {"sport": "soccer", "league": "uefa.europa", "name": "Europa League (Calcio)"},
        
        # Basket
        {"sport": "basketball", "league": "nba", "name": "NBA (Basket)"},
        {"sport": "basketball", "league": "mens-college-basketball", "name": "NCAA Basket (USA)"},
        
        # Tennis
        {"sport": "tennis", "league": "atp", "name": "Tennis ATP"},
        {"sport": "tennis", "league": "wta", "name": "Tennis WTA"},
        
        # Altri Sport USA / Globali
        {"sport": "baseball", "league": "mlb", "name": "MLB (Baseball)"},
        {"sport": "hockey", "league": "nhl", "name": "NHL (Hockey su ghiaccio)"},
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
if st.button("🚀 Sincronizza Tutti gli Sport & Analisi IA", use_container_width=True, type="primary"):
    with st.spinner("Scansione in corso di tutti i feed sportivi globali (Calcio, Basket, Tennis, MLB, NHL, NFL)..."):
        df_events = fetch_all_sports_schedules()
        
    if df_events.empty:
        st.warning("Nessun evento disponibile al momento sui server.")
    else:
        st.success(f"✅ Sincronizzazione completata: trovati {len(df_events)} eventi attivi in tutti gli sport.")
        
        st.subheader("📋 Dataset Globale Eventi Multisport")
        st.dataframe(df_events, use_container_width=True, hide_index=True)
        
        # Sezione IA per l'analisi e pronostici
        if not api_key:
            st.error("⚠️ Impossibile generare i pronostici IA: inserisci la chiave API nella barra laterale (Sidebar).")
        else:
            try:
                genai.configure(api_key=api_key)
                ai_model = genai.GenerativeModel('gemini-1.5-flash')
                
                with st.spinner("L'intelligenza artificiale sta elaborando i pronostici statistici per tutte le discipline..."):
                    # Prendiamo un campione rappresentativo se il dataset è molto ampio per evitare limiti di token
                    sample_data = df_events.head(25).to_string()
                    prompt = f"""
                    Agisci come un Quantitative Sports Analyst esperto di tutti i mercati sportivi (Calcio, Basket, Tennis, US Sports). 
                    Analizza la seguente lista di eventi sportivi multisport:
                    
                    {sample_data}
                    
                    Per ogni riga, genera un pronostico strutturato in tabella Markdown comprendente:
                    1. Sport / Lega
                    2. Match
                    3. Esito Matematico Consigliato (es. 1X2, Over/Under, Moneyline, Spread)
                    4. Indice di Confidenza (Alta, Media, Rischio Calcolato)
                    5. Motivazione sintetica basata su algoritmi stocastici.
                    """
                    
                    response = ai_model.generate_content(prompt)
                    if response and hasattr(response, 'text'):
                        st.markdown("### 🤖 Pronostici & Esiti Algoritmici Multisport dell'IA")
                        st.markdown(response.text)
            except Exception as e:
                st.error(f"⚠️ Errore di autenticazione o generazione IA: {e}")
                
