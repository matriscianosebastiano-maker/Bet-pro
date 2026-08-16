import streamlit as st
import requests
import pandas as pd
from google import genai

st.set_page_config(page_title="Analisi quote sportive", page_icon="📊", layout="centered")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

RISK_LEVELS = {
    "Prudente":   {"kelly_mult": 0.10, "cap": 0.02},
    "Standard":   {"kelly_mult": 0.25, "cap": 0.03},
    "Aggressivo": {"kelly_mult": 0.50, "cap": 0.05},
}


@st.cache_data(ttl=300)
def fetch_real_market_odds(api_key: str):
    """Recupera quote reali dal mercato. Ritorna (dataframe, errore_o_None).
    Non genera MAI dati finti come fallback: se l'API fallisce, lo dice chiaramente."""
    if not api_key:
        return pd.DataFrame(), "Chiave ODDS_API_KEY non impostata nei secrets."
    try:
        url = (
            "https://api.the-odds-api.com/v4/sports/upcoming/odds/"
            f"?regions=eu&markets=h2h,totals&apiKey={api_key}"
        )
        res = requests.get(url, timeout=8)
        res.raise_for_status()
        events = res.json()
    except requests.RequestException as e:
        return pd.DataFrame(), f"Errore di connessione all'API quote: {e}"

    matches = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        bookmakers = event.get("bookmakers", [])
        if not (home and away and bookmakers):
            continue

        odds_h2h, totals_odds = {}, {}
        for m in bookmakers[0].get("markets", []):
            if m.get("key") == "h2h":
                odds_h2h = {o["name"]: o["price"] for o in m.get("outcomes", [])}
            elif m.get("key") == "totals":
                for o in m.get("outcomes", []):
                    if o.get("point") == 2.5:
                        totals_odds[o["name"]] = o["price"]

        if not (odds_h2h.get(home) and odds_h2h.get(away)):
            continue  # niente quota reale per questo match: lo saltiamo, non lo inventiamo

        matches.append({
            "Competizione": event.get("sport_title", "—"),
            "Data_Ora": (event.get("commence_time", "") or "").replace("T", " ")[:16],
            "Match": f"{home} vs {away}",
            "Quota_1": odds_h2h.get(home),
            "Quota_X": odds_h2h.get("Draw"),
            "Quota_2": odds_h2h.get(away),
            "Quota_Under_2.5": totals_odds.get("Under"),
            "Quota_Over_2.5": totals_odds.get("Over"),
        })

    if not matches:
        return pd.DataFrame(), "Nessun match con quote complete disponibile in questo momento."
    df = pd.DataFrame(matches).sort_values("Data_Ora").reset_index(drop=True)
    return df, None


def compute_market_probabilities(df: pd.DataFrame) -> pd.DataFrame:
    """Rilegge le quote come probabilità implicite, scorporando il margine del bookmaker.
    NON è un modello predittivo e non pretende di battere il mercato: mostra solo,
    in modo trasparente, cosa il mercato sta già prezzando."""
    rows = []
    for _, row in df.iterrows():
        q1, qx, q2 = row["Quota_1"], row["Quota_X"], row["Quota_2"]
        if not (q1 and q2):
            continue
        if qx:
            p1, px, p2 = 1 / q1, 1 / qx, 1 / q2
            overround = p1 + px + p2
            outcomes = [("1", p1 / overround), ("X", px / overround), ("2", p2 / overround)]
        else:  # mercato a 2 esiti (es. tennis): niente pareggio
            p1, p2 = 1 / q1, 1 / q2
            overround = p1 + p2
            outcomes = [("1", p1 / overround), ("2", p2 / overround)]

        fav_label, fav_prob = max(outcomes, key=lambda x: x[1])
        rows.append({
            "Competizione": row["Competizione"],
            "Data_Ora": row["Data_Ora"],
            "Match": row["Match"],
            "Quota_1": q1, "Quota_X": qx, "Quota_2": q2,
            "U_2.5": row.get("Quota_Under_2.5"), "O_2.5": row.get("Quota_Over_2.5"),
            "Margine_book_%": round((overround - 1) * 100, 1),
            "Favorito_di_mercato": f"{fav_label} ({fav_prob * 100:.0f}%)",
        })
    return pd.DataFrame(rows)


def suggested_stake(bankroll: float, odds: float, own_prob_pct: float, risk_key: str):
    """Calcola uno stake prudente SOLO a partire da una probabilità che l'utente
    inserisce di sua iniziativa — il sistema non la genera mai da solo."""
    if not odds or odds <= 1 or not own_prob_pct:
        return None, None
    b = odds - 1
    p = own_prob_pct / 100
    kelly = max(0.0, (b * p - (1 - p)) / b)
    risk = RISK_LEVELS[risk_key]
    fraction = min(kelly * risk["kelly_mult"], risk["cap"])
    ev = p * odds - 1
    return bankroll * fraction, ev


# ---------------- INTERFACCIA ----------------

st.title("📊 Analisi quote sportive")
st.caption(
    "Legge il mercato in modo trasparente. Non genera schedine automatiche né pronostici "
    "'garantiti' — ogni puntata resta una tua scelta manuale, fatta sul sito del tuo bookmaker."
)

with st.sidebar:
    st.subheader("Il tuo profilo di rischio")
    bankroll = st.number_input("Bankroll (€)", min_value=1.0, value=100.0, step=10.0)
    risk_key = st.selectbox("Livello di rischio", list(RISK_LEVELS.keys()), index=0)
    st.caption(f"Stake massimo per giocata: {RISK_LEVELS[risk_key]['cap'] * 100:.0f}% del bankroll")

if st.button("🔍 Recupera quote di mercato", type="primary", use_container_width=True):
    df_raw, error = fetch_real_market_odds(ODDS_API_KEY)

    if error:
        st.error(f"{error} Non mostro dati inventati o obsoleti spacciati per reali — riprova più tardi.")
    else:
        df_analyzed = compute_market_probabilities(df_raw)
        st.subheader("Quote e probabilità di mercato")
        st.caption(
            "'Favorito di mercato' è la quota riletta in percentuale, già scorporata dal margine "
            "del bookmaker ('Margine_book_%'). È il modo in cui il mercato prezza l'evento ora — "
            "non una previsione di ciò che accadrà."
        )
        st.dataframe(df_analyzed, use_container_width=True)
        st.session_state["df_analyzed"] = df_analyzed

if "df_analyzed" in st.session_state and not st.session_state["df_analyzed"].empty:
    df_analyzed = st.session_state["df_analyzed"]

    st.divider()
    st.subheader("Calcolo stake per una tua giocata")
    st.caption(
        "Inserisci la tua stima di probabilità per un esito specifico: nessun modello basato "
        "solo sulle quote può stimarla al posto tuo in modo affidabile."
    )
    selected_match = st.selectbox("Match", df_analyzed["Match"].tolist())
    row = df_analyzed[df_analyzed["Match"] == selected_match].iloc[0]

    outcome_options = ["1", "2"] if pd.isna(row["Quota_X"]) or not row["Quota_X"] else ["1", "X", "2"]
    col1, col2 = st.columns(2)
    with col1:
        selected_outcome = st.selectbox("Esito", outcome_options)
    with col2:
        own_prob = st.number_input("Tua stima probabilità (%)", min_value=1, max_value=99, value=50)

    odds_map = {"1": row["Quota_1"], "X": row["Quota_X"], "2": row["Quota_2"]}
    chosen_odds = odds_map[selected_outcome]

    stake, ev = suggested_stake(bankroll, chosen_odds, own_prob, risk_key)
    if stake is not None:
        st.markdown(f"Quota selezionata: **{chosen_odds}**")
        ev_color = "green" if ev >= 0 else "red"
        st.markdown(f"Valore atteso secondo la tua stima: :{ev_color}[{ev * 100:+.1f}%]")
        st.markdown(
            f"Stake consigliato ({risk_key.lower()}, tetto {RISK_LEVELS[risk_key]['cap'] * 100:.0f}%): "
            f"**€{stake:.2f}**"
        )
        if ev < 0:
            st.info(
                "Secondo la tua stima questa quota non ha valore. Il calcolo è mostrato comunque "
                "per trasparenza — valuta di non giocarla o di ridurre l'importo."
            )

    if GEMINI_API_KEY:
        st.divider()
        if st.button("📝 Genera lettura di contesto (facoltativo)"):
            with st.spinner("Analisi in corso…"):
                summary = df_analyzed.to_string(index=False)
                prompt = f"""Sei un analista che aiuta a leggere il mercato delle scommesse sportive con onestà statistica.
Ecco i match con quote e probabilità implicite di mercato (già scorporate dal margine):

{summary}

Per ciascun match scrivi 2-3 righe di contesto (forma, importanza della gara, assenze note) SENZA:
- proporre schedine multiple o combo forzate
- usare espressioni come "consigliato", "sicuro", "vincente certo"
- inventare percentuali diverse da quelle di mercato indicate sopra

Chiudi con una riga che ricordi che sono probabilità di mercato, non previsioni garantite."""
                try:
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    # Verifica il nome modello aggiornato nella documentazione ufficiale Google AI:
                    # "gemini-3.5-flash" nell'app originale non risulta tra i modelli documentati.
                    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                    if response and response.text:
                        st.markdown(response.text)
                    else:
                        st.warning("Nessuna risposta generata, riprova.")
                except Exception as e:
                    st.warning(f"Generazione non riuscita: {e}")
    else:
        st.caption("Imposta GEMINI_API_KEY nei secrets per abilitare la lettura di contesto testuale (facoltativa).")

st.divider()
st.caption(
    "Le probabilità mostrate derivano dalle quote di mercato, non da un modello predittivo proprietario. "
    "Punta solo ciò che puoi permetterti di perdere."
)
