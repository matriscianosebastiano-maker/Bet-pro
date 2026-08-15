import streamlit as st
import pandas as pd
import numpy as np
import google.generativeai as genai
import random # Usato qui solo per simulare i dati se l'API non è collegata

# --- 1. CONFIGURAZIONE PAGINA E VARIABILI ---
st.set_page_config(
    page_title="Bet-Pro | Intelligence", 
    page_icon="📈", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Nascondere il menu di default di Streamlit per un look più pulito
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# API Key di Gemini (sostituisci con la tua se diversa o usa i secrets di Streamlit)
GEMINI_API_KEY = "AQ.Ab8RN6JgwZVuzMONM_Zmn_IlwL-PqY9-Sdu3Bxw8jxDNeAfBwg"

# --- 2. FUNZIONI DI CALCOLO E DATI ---

def calcola_probabilita_implicita(quota):
    """Calcola la probabilità implicita data una quota decimale."""
    if quota > 0:
        return (1 / quota) * 100
    return 0

def calcola_kelly(quota, probabilita_stimata, bankroll=1000):
    """
    Calcola la percentuale del bankroll da puntare secondo il Criterio di Kelly.
    formula: f* = (bp - q) / b
    b = quota decimale - 1
    p = probabilità di vincita stimata (decimale, es. 0.55)
    q = probabilità di perdita (1 - p)
    """
    if quota <= 1 or probabilita_stimata <= 0:
        return 0.0
    
    b = quota - 1
    p = probabilita_stimata / 100
    q = 1 - p
    
    f_star = (b * p - q) / b
    
    # Se f_star è negativo, il vantaggio è del bookmaker, non si punta.
    # Applichiamo un "Fractional Kelly" (es. 0.5 o mezzo Kelly) per mitigare il rischio
    fractional_multiplier = 0.5 
    
    if f_star > 0:
        puntata_perc = (f_star * fractional_multiplier) * 100
        return round(puntata_perc, 2)
    return 0.0

def mock_fetch_odds_data():
    """
    Funzione simulata per recuperare i dati.
    Qui andrà inserita la tua logica reale (es. chiamate a The Odds API).
    """
    squadre = [("Napoli", "Inter"), ("Juventus", "Milan"), ("Roma", "Lazio"), ("Atalanta", "Fiorentina")]
    dati = []
    
    for casa, trasferta in squadre:
        q1 = round(random.uniform(1.3, 3.5), 2)
        qx = round(random.uniform(2.8, 4.0), 2)
        q2 = round(random.uniform(1.8, 4.5), 2)
        
        # Simulazione di una confidenza algoritmica
        confidenza = random.randint(45, 75) 
        
        kelly_1 = calcola_kelly(q1, confidenza)
        
        dati.append({
            "Lega": "Serie A",
            "Match": f"{casa} vs {trasferta}",
            "Quota_1": q1,
            "Quota_X": qx,
            "Quota_2": q2,
            "Pronostico": "1 (Casa)" if q1 < q2 else "2 (Trasferta)",
            "Confidenza (%)": confidenza,
            "Kelly_Puntata_Max (%)": kelly_1
        })
    
    return pd.DataFrame(dati)

# --- 3. INTEGRAZIONE GEMINI AI ---
def get_gemini_market_intelligence(api_key, dataframe):
    """Invia i dati elaborati a Gemini per un'analisi strategica testuale."""
    try:
        genai.configure(api_key=api_key)
        
        # IMPORTANTE: Utilizzo del modello stabile richiesto
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Prepariamo un riassunto dei dati in formato stringa per il prompt
        market_summary = dataframe.to_string(index=False)
        
        prompt = f"""
        Agisci come un Quantitative Trader e analista sportivo professionista.
        Ho un algoritmo che ha processato le seguenti quote di mercato e calcolato 
        la size della puntata tramite il Criterio di Kelly (frazione).
        
        Ecco i dati dei match di oggi:
        {market_summary}
        
        Compiti:
        1. Identifica le 2 o 3 migliori "Value Bet" (puntate di valore) basandoti sulla confidenza e sul Kelly.
        2. Spiega brevemente perché queste partite presentano un'opportunità matematica.
        3. Fornisci un avvertimento sul money management per queste specifiche puntate.
        
        Scrivi il report in italiano, usa il formato Markdown e mantieni un tono tecnico, analitico e distaccato.
        """
        
        # Richiamiamo il modello
        response = model.generate_content(prompt)
        return response.text, "successo"
        
    except Exception as e:
        return None, f"Errore di comunicazione con Gemini: {str(e)}"

# --- 4. INTERFACCIA UTENTE (UI) ---

# Sidebar
with st.sidebar:
    st.title("⚙️ Bet-Pro Settings")
    st.markdown("---")
    st.success("🔑 API Gemini Configurata")
    st.info("🧠 Motore: Gemini 1.5 Flash")
    
    st.markdown("---")
    st.subheader("Filtri Analisi")
    min_confidence = st.slider("Confidenza Algoritmica Minima (%)", min_value=30, max_value=90, value=50)
    min_kelly = st.slider("Puntata Kelly Minima (%)", min_value=0.0, max_value=10.0, value=0.5, step=0.1)

# Main Body
st.title("📊 Bet-Pro | Market Intelligence Dashboard")
st.markdown("Analisi delle quote, probabilità algoritmiche e gestione del Bankroll.")

# Recupero dati
df_odds = mock_fetch_odds_data()

# Applicazione filtri
df_filtered = df_odds[
    (df_odds["Confidenza (%)"] >= min_confidence) & 
    (df_odds["Kelly_Puntata_Max (%)"] >= min_kelly)
]

# Metriche principali in alto
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Match Analizzati", value=len(df_odds))
with col2:
    st.metric(label="Value Bets Trovate", value=len(df_filtered))
with col3:
    max_k = df_filtered['Kelly_Puntata_Max (%)'].max() if not df_filtered.empty else 0
    st.metric(label="Max Kelly %", value=f"{max_k}%")

st.markdown("---")

# Visualizzazione della Tabella Dati Filtrata
st.subheader("📋 Opportunità di Mercato Identificate")
if not df_filtered.empty:
    # Mostriamo un dataframe interattivo
    st.dataframe(
        df_filtered.style.highlight_max(subset=['Kelly_Puntata_Max (%)'], color='#1f77b4')
                         .highlight_max(subset=['Confidenza (%)'], color='#2ca02c'),
        use_container_width=True
    )
    
    st.markdown("---")
    
    # Sezione Analisi AI
    st.subheader("🧠 Analisi Strategica Avanzata (Gemini AI)")
    
    # Pulsante per avviare l'analisi (come nel tuo screenshot)
    if st.button("🚀 Interpella Gemini per Analisi Strategica", use_container_width=True, type="primary"):
        with st.spinner("Gemini sta analizzando le value bet..."):
            ai_report, status = get_gemini_market_intelligence(GEMINI_API_KEY, df_filtered)
            
            if status == "successo":
                st.success("Analisi completata con successo!")
                
                # Card per il report AI
                with st.container():
                    st.markdown("""
                        <style>
                        .report-box {
                            background-color: #1e1e2e;
                            padding: 20px;
                            border-radius: 10px;
                            border-left: 5px solid #00f0ff;
                            color: white;
                        }
                        </style>
                        """, unsafe_allow_html=True)
                    st.markdown(f'<div class="report-box">{ai_report}</div>', unsafe_allow_html=True)
            else:
                st.error(status)
else:
    st.warning("Nessuna partita soddisfa i criteri di confidenza e Kelly impostati nei filtri laterali. Abbassa le soglie per vedere più match.")
                  
