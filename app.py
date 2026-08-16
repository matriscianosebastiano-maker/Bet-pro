import streamlit as st
import requests
import pandas as pd
from google import genai

st.set_page_config(page_title="Bet-Pro | Analisi Quote e Classi di Esito", page_icon="📊", layout="centered")

ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

RISK_LEVELS = {
    "Prudente":   {"kelly_mult": 0.10, "cap": 0.02},
    "Standard":   {"kelly_mult": 0.25, "cap": 0.03},
    "Aggressivo": {"kelly_mult": 0.50, "cap": 0.05},
}


@st.cache_data(ttl=7200)
def fetch_real_market_odds(api_key: str):
    """Recupera il palinsesto e le quote reali salvandole in cache per 2 ore."""
    if not api_key:
        return pd.DataFrame(), "Chiave ODDS_API_KEY non presente nei Secrets di Streamlit."

    try:
        url = (
            "https://api.the-odds-api.com/v4/sports/upcoming/odds/"
            f"?regions=eu&markets=h2h,totals&apiKey={api_key.strip()}"
        )
        res = requests.get(url, timeout=8)

        if res.status_code == 401:
            return pd.DataFrame(), "Chiave API non valida o non autorizzata."
        if res.status_code == 429:
            return pd.DataFrame(), "Quota mensile di chiamate esaurita."

        res.raise_for_status()
        events = res.json()

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

            if odds_h2h.get(home) and odds_h2h.get(away):
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
            return pd.DataFrame(), "Nessun match con quote valide disponibile."

        df = pd.DataFrame(matches).sort_values("Data_Ora").reset_index(drop=True)
        return df, None

    except requests.RequestException as e:
        return pd.DataFrame(), f"Errore di rete: {e}"


def compute_market_probabilities(df: pd.DataFrame) -> pd.DataFrame:
    """Calcola le probabilità implicite scorporando l'aggio del bookmaker."""
    rows = []
    for _, row in df.iterrows():
        q1, qx, q2 = row["Quota_1"], row["Quota_X"], row["Quota_2"]
        if not (q1 and q2) or q1 <= 0 or q2 <= 0:
            continue

        if pd.notna(qx) and qx > 0:
            p1, px, p2 = 1 / q1, 1 / qx, 1 / q2
            overround = p1 + px + p2
            outcomes = [("1", p1 / overround), ("X", px / overround), ("2", p2 / overround)]
        else:
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
            "Favorito": f"{fav_label} ({fav_prob * 100:.0f}%)",
        })
    return pd.DataFrame(rows)


def analyze_with_ai(df_summary: pd.DataFrame, api_key: str):
    """Analizza il palinsesto associando classi di esito e risultati esatti probabilistici."""
    client = genai.Client(api_key=api_key)
    
    prompt = f"""Sei un analista quantitativo di scommesse sportive. Analizza il seguente palinsesto di partite e quote:

{df_summary.to_string(index=False)}

Per OGNI partita nel palinsesto, applica questa logica di clustering e rispondi esattamente con questa struttura in Markdown:

### ⚽ [Nome Match]
* **Lettura del Mercato:** (Analisi rapida delle quote 1X2 e Under/Over)
* **Classi di Esito Associate:**
  * **Conservativa (Basso Rischio):** [Es. Doppia chance / DNB / Multigol conservativo]
  * **Principale (Medio Rischio):** [Es. Esito 1X2 / Segno + Under/Over / Gol-NoGol]
  * **Speculativa (Alto Rischio):** [Es. Combo mirata / Risultato a gruppi]
* **Cluster Risultati Esatti Coerenti:** [Indica i 3 risultati esatti (es. 1-0, 2-0, 1-1) statisticamente più coerenti con la distribuzione delle quote del bookmaker].

Usa un tono analitico, diretto, ed evita frasi generiche o promesse di vincita."""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return response.text if response else "Nessuna risposta generata dall'IA."
    except Exception as e:
        return f"Errore durante la generazione dell'analisi IA: {e}"


# ---------------- INTERFACCIA STREAMLIT ----------------

st.title("📊 Bet-Pro | Palinsesto & Classi di Esito")
st.caption("Estrae il palinsesto reale e calcola cluster di esiti e risultati probabilistici tramite IA.")

if "df_raw" not in st.session_state:
    st.session_state["df_raw"] = None

col_btn1, col_btn2 = st.columns([3, 1])
with col_btn1:
    if st.button("🔍 Estrai Palinsesto e Quote", type="primary", use_container_width=True):
        with st.spinner("Recupero dati dal mercato in corso..."):
            df_fetched, error = fetch_real_market_odds(ODDS_API_KEY)
            if error:
                st.error(error)
            else:
                st.session_state["df_raw"] = df_fetched
                st.success("Palinsesto aggiornato!")

with col_btn2:
    if st.button("🔄 Svuota Cache", use_container_width=True):
        st.cache_data.clear()
        st.session_state["df_raw"] = None
        st.rerun()

if st.session_state["df_raw"] is not None and not st.session_state["df_raw"].empty:
    df_analyzed = compute_market_probabilities(st.session_state["df_raw"])
    
    st.subheader("📋 Palinsesto e Probabilità Implicite")
    st.dataframe(df_analyzed, use_container_width=True)

    st.divider()
    st.subheader("🤖 Analisi IA: Classi di Esito & Risultati Coerenti")
    
    if not GEMINI_API_KEY:
        st.warning("Aggiungi `GEMINI_API_KEY` nei Secrets di Streamlit per abilitare il motore di analisi IA.")
    else:
        if st.button("🧠 Elabora Classi di Esito per il Palinsesto", type="primary", use_container_width=True):
            with st.spinner("Analisi quantitativa in corso sui singoli match..."):
                ai_result = analyze_with_ai(df_analyzed, GEMINI_API_KEY)
                st.markdown(ai_result)
        
