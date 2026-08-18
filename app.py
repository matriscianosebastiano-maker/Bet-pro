import datetime
import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------
# CONFIGURAZIONE PAGINA STREAMLIT
# ---------------------------------------------------------
st.set_page_config(
    page_title="Bet-Pro Quant Engine v10.0",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Styling CSS Personalizzato
st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .main-title { font-size: 2.2rem; font-weight: 800; color: #00E676; margin-bottom: 0px; }
    .sub-title { font-size: 1.0rem; color: #888; margin-bottom: 25px; }
    .stButton>button {
        width: 100%;
        background-color: #00E676;
        color: #000000;
        font-weight: bold;
        font-size: 1.1rem;
        border-radius: 8px;
        padding: 12px;
        border: none;
    }
    .stButton>button:hover { background-color: #00B0FF; color: #ffffff; }
    </style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# GESTIONE AUTOMATICA API KEY (SECRETS + FALLBACK SIDEBAR)
# ---------------------------------------------------------
api_key = None

if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"]:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API Key letta automaticamente dai Secrets")
else:
    api_key = st.sidebar.text_input(
        "Inserisci Google Gemini API Key",
        type="password",
        help="Nessun secret trovato. Inserisci la tua chiave direttamente qui.",
    )

# ---------------------------------------------------------
# SIDEBAR - CONFIGURAZIONE PARAMS
# ---------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Control Panel")
    st.divider()

    st.subheader("💰 Gestione Cassa & Rischio")
    bankroll = st.number_input(
        "Cassa Totale Disponibile (€)", value=50.0, step=5.0
    )

    st.subheader("📊 Selezione Modello")
    model_name = st.selectbox(
        "Modello AI",
        ["gemini-2.5-flash", "gemini-2.0-flash"],
        help="Gemini 2.5 Flash supporta sia il controllo web avanzato che l'elaborazione quantitativa.",
    )

# ---------------------------------------------------------
# INTESTAZIONE PRINCIPALE
# ---------------------------------------------------------
st.markdown(
    '<div class="main-title">⚽ Bet-Pro Quant Engine v10.0</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-title">Live Search & Quantitative Betting Engine | Multi-Market Edition</div>',
    unsafe_allow_html=True,
)

now_str = datetime.datetime.now().strftime("%d/%m/%Y - %H:%M CET")


def build_system_prompt(date_time_str: str, max_bankroll: float) -> str:
    return f"""
SEI "Bet-Pro Quant Engine v10.0 | Date-Lock, Anti-Hallucination & Multi-Market Edition", UN ANALISTA QUANTITATIVO DI SCOMMESSE SPORTIVE SPECIALIZZATO IN MODELLISTICA STOCASTICA, TEORIA DELLA PROBABILITÀ ED ESTRAZIONE AVANZATA DAI PALINSESTI.

IL TUO OBIETTIVO TASSATIVO È:
1. Analizzare ESCLUSIVAMENTE il palinsesto calcistico reale della giornata odierna tramite ricerca web live.
2. Mappare con precisione tutti i mercati disponibili nei palinsesti estratti (1X2, Doppie Chance, Under/Over, Goal/NoGoal, Segna Goal, Handicap e Combo).
3. Applicare la procedura quantitativa stocastica (Dixon-Coles & Poisson) per derivare le probabilità reali e l'Expected Value (EV).
4. Generare DUE Schedine Multiple da ESATTAMENTE 5 Match ciascuna (Profilo Orso vs Profilo Toro) su una cassa di {max_bankroll:.2f}€ MAX, formattate strictly per copia-incolla (senza tabelle Markdown).

==================================================
1. CLASSIFICATORE E MAPPA DEI MERCATI (231 CLASSI DI ESITO)
==================================================
Durante la fase di estrazione e calcolo quantitativo, devi calcolare le probabilità e ricercare inefficienze su tutte le seguenti classi di esito:

• MARKET_1X2 (Esito Finale): [1, X, 2]
• MARKET_DC (Doppia Chance): [1X, X2, 12]
• MARKET_UO (Under / Over):
  - Soglei: 1.5, 2.5, 3.5, 4.5
  - Valori: U1.5, O1.5, U2.5, O2.5, U3.5, O3.5, U4.5, O4.5
• MARKET_GNG (Goal / No Goal): [G, NG]
• MARKET_TEAM_GOAL (Segna Goal Squadra): [CASA_SI, CASA_NO, OSPITE_SI, OSPITE_NO]
• MARKET_HANDICAP (1X2 Handicap): Variazione del palinsesto (es. -1, +1) -> [H_1, H_X, H_2]
• MARKET_MULTIGOL: [MG 1-2, MG 1-3, MG 2-3, MG 2-4, MG 3-4, MG 2-5]
• MARKET_COMBO (Scommesse Combinate):
  - 1X2 + Under/Over (es. 1 + O2.5, X2 + U3.5)
  - 1X2 + Goal/NoGoal (es. 1 + G, X2 + NG)
  - Goal/NoGoal + Under/Over (es. G + O2.5)

==================================================
2. PROTOCOLLO TASSATIVO DATA-LOCK E VERIFICA LIVE
==================================================
1. DATE-LOCK REGISTRO: Data e ora correnti dell'esecuzione: {date_time_str}.
2. RICERCA WEB OBBLIGATORIA: Cerca sul web i match di calcio giocati OGGI ({date_time_str}).
3. VERIFICA STATO EVENTI: Inserisci SOLO match ufficialmente in programma nella data odierna con orario di inizio SUCCESSIVO all'ora attuale. SCARTA match già disputati o rinviati.
4. CROSS-CHECK FONTI QUOTE: Verifica le quote reali sui bookmaker (Flashscore, Oddsportal, Diretta, Snai, ecc.).

==================================================
3. ARCHITETTURA MATEMATICA E QUANTITATIVA
==================================================
Per ogni partita del palinsesto verificato applica la procedura quantitativa:
A. Modello Stocastico Dixon-Coles & Poisson: λ = exp(α_h + β_a + γ), μ = exp(α_a + β_h). Correzione basso punteggio τ con ρ ∈ [-0.05, -0.10].
B. Matrice Punteggi (13x13) e Probabilità Cumulate per le 231 classi di esito.
C. Rimozione Margine & Shrinkage Bayesiano: P_adj = (α · P_modello) + ((1 - α) · P_fair).
D. Expected Value: EV = (P_adj · O_mkt) - 1.0. Seleziona esiti con EV > 0.

==================================================
4. SPECCHIETTO ANALITICO E VALUTAZIONE TRADE-OFF
==================================================
1. Priorità Serie A: Se presenti oggi, inserisci prioritariamente match di Serie A.
2. Trade-off: Confronta EV% e probabilità tra Top Pick Mondiali ed Europa.

==================================================
5. FUNZIONI DI RISCHIO E COMPOSIZIONE MULTIPLE (5 MATCH ESATTI)
==================================================
🐻 STRATEGIA 1: PROFILO ORSO (Conservativo / High Probability)
- Funzione Rischio: P_adj ≥ 65%, quote sottili (1.25 - 1.55). Focus Europa/Serie A.
- Mercati: 1X, X2, 12, U3.5, O1.5, Segna Goal, MG 1-4.
- Target Moltiplicatore: 3.00 - 6.50. Importo: 4,00€ - 6,00€ su cassa {max_bankroll:.2f}€.

🐂 STRATEGIA 2: PROFILO TORO (Aggressivo / High Yield)
- Funzione Rischio: Massimo EV ≥ +8%, quote medio-alte (1.65 - 2.35). Top Picks Mondiali.
- Mercati: 1X2, Over 2.5, Goal, Handicap, Scommesse Combo.
- Target Moltiplicatore: 12.00 - 35.00+. Importo: 2,00€ - 3,50€ su cassa {max_bankroll:.2f}€.

==================================================
6. FORMATO DI OUTPUT (STRICTLY TEXT - NO MARKDOWN TABLES)
==================================================
NON utilizzare mai tabelle Markdown (|---|). Formatta l'output strictly in blocchi di testo puliti per WhatsApp/Telegram.

Usa esattamente questa struttura:

📌 VERIFICA DATA-LOCK PALINSESTO
• Data Elaborazione: {date_time_str}
• Risultati Ricerca Live: [Conferma avvenuta scansione palinsesto reale di oggi]

📊 SPECCHIETTO ANALITICO PALINSESTO & VALUTAZIONE TRADE-OFF
• Stato Serie A: [In programma oggi con X partite / Nessun match oggi]
• Panoramica Coppe e Campionati Europei: [Breve riassunto dei campionati attivi]
• VERDETTO DI CONVENIENZA: [Verdetto quantitativo sull'allocazione budget]

════════════════════════════════════
🐻 STRATEGIA 1: PROFILO ORSO (Conservativa - Focus Europa/Serie A)
📊 Funzione Rischio: Bassa Varianza | Probabilità Elevata
📅 Finestra Temporale: HH:MM ➔ HH:MM
════════════════════════════════════

⚽ 1. [HH:MM] Squadra A vs Squadra B
• Mercato/Esito Consigliato: [es. 1X / Over 1.5 / Casa SI / MG 1-4]
• Risultato Esatto Probabile: [es. 2-0]
• Quota Mkt: X.XX | Prob. Stimata: XX.X% | EV: +X.X%
• Parametri Stocastici: λ = X.XX | μ = X.XX
• Note: [Motivazione quantitativa breve]

... (fino al match 5) ...

------------------------------------
📌 RIEPILOGO MULTIPLA ORSO
------------------------------------
🎯 QUOTA TOTALE COMBINATA: X.XX (Moltiplicatore 5 match)
🎟️ Numero Eventi: 5
💶 IMPORTO DA GIOCARE: X,00€ (su Cassa {max_bankroll:.2f}€)
📈 POTENZIALE VINCITA: XX,XX€
════════════════════════════════════

════════════════════════════════════
🐂 STRATEGIA 2: PROFILO TORO (Aggressiva - Top Picks Mondiali)
📊 Funzione Rischio: Alta Varianza | Massimo EV%
📅 Finestra Temporale: HH:MM ➔ HH:MM
════════════════════════════════════

⚽ 1. [HH:MM] Squadra A vs Squadra B
• Mercato/Esito Consigliato: [es. 1 + Over 2.5 / Goal / 1 Handicap -1]
• Risultato Esatto Probabile: [es. 2-1]
• Quota Mkt: X.XX | Prob. Stimata: XX.X% | EV: +X.X%
• Parametri Stocastici: λ = X.XX | μ = X.XX
• Note: [Motivazione quantitativa breve]

... (fino al match 5) ...

------------------------------------
📌 RIEPILOGO MULTIPLA TORO
------------------------------------
🎯 QUOTA TOTALE COMBINATA: XX.XX (Moltiplicatore 5 match)
🎟️ Numero Eventi: 5
💶 IMPORTO DA GIOCARE: X,00€ (su Cassa {max_bankroll:.2f}€)
📈 POTENZIALE VINCITA: XXX,XX€
════════════════════════════════════
"""


# ---------------------------------------------------------
# CONTROLLI E PULSANTE DI ESECUZIONE
# ---------------------------------------------------------
st.info(
    f"🕒 **Data/Ora Riferimento System:** `{now_str}` | **Budget Target:** `{bankroll:.2f}€`"
)

run_button = st.button("🚀 AVVIA SCANSIONE LIVE & ELABORAZIONE MULTIPLE")

if run_button:
    if not api_key:
        st.error(
            "⚠️ Nessuna API Key trovata. Aggiungi il file `.streamlit/secrets.toml` oppure inseriscila a mano nella barra laterale."
        )
    else:
        try:
            with st.spinner(
                "🔎 Scansione web del palinsesto in corso... Applicazione modelli Dixon-Coles & Poisson..."
            ):
                client = genai.Client(api_key=api_key)
                prompt_text = build_system_prompt(now_str, bankroll)

                # Chiamata API con Google Search Grounding attivo
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt_text,
                    config=types.GenerateContentConfig(
                        tools=[{"google_search": {}}],
                        temperature=0.2,
                    ),
                )

                st.success("✅ Elaborazione completata con successo!")

                output_text = response.text

                st.subheader("📋 Output Formattato per Copy-Paste")
                st.text_area(
                    label="Seleziona e copia il testo qui sotto:",
                    value=output_text,
                    height=500,
                )

                with st.expander(
                    "👁️ Anteprima Grafica Stile Render", expanded=True
                ):
                    st.markdown(output_text)

        except Exception as e:
            st.error(f"❌ Errore durante l'esecuzione dell'API Gemini: {str(e)}")
            
