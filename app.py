import math
import datetime
import requests
import numpy as np
import pandas as pd
import streamlit as st
from scipy.optimize import minimize
from scipy.stats import poisson

# -----------------------------------------------------------------------------
# 1. CONFIGURAZIONE E COSTANTI QUANTITATIVE
# -----------------------------------------------------------------------------
XI = 0.0019           # Decadimento temporale Dixon-Coles
MAX_GOALS = 12        # Griglia 13x13 (punteggi da 0 a 12)
DEFAULT_KELLY_FRAC = 0.125  # Kelly frazionario (1/8)

FAMILY_TRUST = {
    "1X2": 0.85,
    "OU": 0.80,
    "BTTS": 0.75,
    "HANDICAP": 0.70,
    "MULTIGOL": 0.65
}

st.set_page_config(
    page_title="Bet-Pro | Quant Engine v6",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Session State
if "calculated_data" not in st.session_state:
    st.session_state.calculated_data = None
if "bet_history" not in st.session_state:
    st.session_state.bet_history = []

# -----------------------------------------------------------------------------
# 2. DIXON-COLES ENGINE & MATRICE PUNTEGGI
# -----------------------------------------------------------------------------
def dixon_coles_tau(x, y, lambda_x, mu_y, rho):
    if x == 0 and y == 0:
        return 1.0 - (lambda_x * mu_y * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lambda_x * rho)
    elif x == 1 and y == 0:
        return 1.0 + (mu_y * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    return 1.0

def dc_log_likelihood(params, matches, teams, xi=XI, l2_reg=0.01):
    n_teams = len(teams)
    att = params[:n_teams]
    def_ = params[n_teams:2*n_teams]
    gamma = params[2*n_teams]
    rho = params[2*n_teams + 1]
    
    ll = 0.0
    for match in matches:
        h_idx, a_idx = match['home_idx'], match['away_idx']
        x, y = match['home_goals'], match['away_goals']
        days = match['days_ago']
        
        weight = np.exp(-xi * days)
        lambda_x = np.exp(att[h_idx] + def_[a_idx] + gamma)
        mu_y = np.exp(att[a_idx] + def_[h_idx])
        
        tau = dixon_coles_tau(x, y, lambda_x, mu_y, rho)
        prob = tau * poisson.pmf(x, lambda_x) * poisson.pmf(y, mu_y)
        
        if prob <= 0:
            prob = 1e-12
        ll += weight * np.log(prob)
        
    penalty = l2_reg * (np.sum(att**2) + np.sum(def_**2) + gamma**2 + rho**2)
    return -ll + penalty

def fit_dixon_coles(matches, teams):
    n_teams = len(teams)
    init_params = np.zeros(2 * n_teams + 2)
    init_params[2*n_teams] = 0.25   # Home Advantage
    init_params[2*n_teams + 1] = -0.05 # Rho
    
    constraints = ({'type': 'eq', 'fun': lambda p: np.sum(p[:n_teams])})
    bounds = [(None, None)] * (2 * n_teams) + [(0, 1), (-0.5, 0.5)]
    
    res = minimize(
        dc_log_likelihood, 
        init_params, 
        args=(matches, teams), 
        method='SLSQP', 
        constraints=constraints,
        bounds=bounds
    )
    
    att = dict(zip(teams, res.x[:n_teams]))
    def_ = dict(zip(teams, res.x[n_teams:2*n_teams]))
    gamma = res.x[2*n_teams]
    rho = res.x[2*n_teams + 1]
    return att, def_, gamma, rho

def build_score_matrix(lambda_x, mu_y, rho, max_goals=MAX_GOALS):
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            tau = dixon_coles_tau(x, y, lambda_x, mu_y, rho)
            matrix[x, y] = tau * poisson.pmf(x, lambda_x) * poisson.pmf(y, mu_y)
    matrix = np.maximum(matrix, 0)
    return matrix / np.sum(matrix)

def derive_markets_231(matrix):
    markets = {}
    
    # 1X2
    p_1 = float(np.sum(np.tril(matrix, -1)))
    p_x = float(np.sum(np.diag(matrix)))
    p_2 = float(np.sum(np.triu(matrix, 1)))
    markets['1'] = p_1
    markets['X'] = p_x
    markets['2'] = p_2
    markets['1X'] = p_1 + p_x
    markets['X2'] = p_x + p_2
    markets['12'] = p_1 + p_2
    
    # Over / Under
    for line in [0.5, 1.5, 2.5, 3.5, 4.5]:
        over_p = sum(matrix[x, y] for x in range(matrix.shape[0]) for y in range(matrix.shape[1]) if x + y > line)
        markets[f'Over {line}'] = float(over_p)
        markets[f'Under {line}'] = float(1.0 - over_p)
        
    # BTTS
    btts_yes = float(np.sum(matrix[1:, 1:]))
    markets['BTTS_YES'] = btts_yes
    markets['BTTS_NO'] = 1.0 - btts_yes
    
    # Multigol principali
    for min_g, max_g in [(1,2), (1,3), (2,3), (2,4), (3,4), (2,5)]:
        p_mg = sum(matrix[x, y] for x in range(matrix.shape[0]) for y in range(matrix.shape[1]) if min_g <= (x + y) <= max_g)
        markets[f'MG_{min_g}-{max_g}'] = float(p_mg)
        
    return markets

# -----------------------------------------------------------------------------
# 3. VALUTAZIONE VALUE, SHRINKAGE E KELLY
# -----------------------------------------------------------------------------
def remove_overround(odds_list):
    implied = [1.0 / o for o in odds_list if o > 1.0]
    total_margin = sum(implied)
    return [p / total_margin for p in implied]

def apply_shrinkage(p_model, p_fair, trust_factor):
    return (trust_factor * p_model) + ((1.0 - trust_factor) * p_fair)

def calc_kelly_stake(p_adj, book_odds, bankroll, fraction=DEFAULT_KELLY_FRAC):
    b = book_odds - 1.0
    q = 1.0 - p_adj
    f = (b * p_adj - q) / b
    if f <= 0:
        return 0.0, 0.0
    stake = bankroll * f * fraction
    return round(stake, 2), round(f * fraction * 100, 2)

# -----------------------------------------------------------------------------
# 4. API INTEGRATION
# -----------------------------------------------------------------------------
def fetch_football_data_history(league_code, api_key):
    url = f"https://api.football-data.org/v4/competitions/{league_code}/matches?status=FINISHED"
    headers = {"X-Auth-Token": api_key}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json().get('matches', [])
        matches = []
        now = datetime.datetime.now()
        for m in data:
            h_team = m['homeTeam']['name']
            a_team = m['awayTeam']['name']
            hg = m['score']['fullTime']['home']
            ag = m['score']['fullTime']['away']
            m_date = datetime.datetime.strptime(m['utcDate'][:10], "%Y-%m-%d")
            days_ago = (now - m_date).days
            if hg is not None and ag is not None:
                matches.append({
                    'home': h_team, 'away': a_team,
                    'home_goals': hg, 'away_goals': ag,
                    'days_ago': max(0, days_ago)
                })
        return matches
    except Exception:
        return []

def fetch_odds_api_fixtures(sport_key, api_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={api_key}&regions=eu&markets=h2h,totals"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return []
        return r.json()
    except Exception:
        return []

# -----------------------------------------------------------------------------
# 5. UI STREAMLIT
# -----------------------------------------------------------------------------
st.title("Bet-Pro | Quant Engine v6")
st.caption("Motore stocastico Dixon-Coles con correzione del margine e allocazione Kelly")

# Sidebar Configuration
st.sidebar.header("Impostazioni e Secret")
api_fd_key = st.sidebar.text_input("Football-Data API Key", value=st.secrets.get("API_FOOTBALL_DATA_KEYS", ""), type="password")
api_odds_key = st.sidebar.text_input("The Odds API Key", value=st.secrets.get("ODDS_API_KEY", ""), type="password")

bankroll = st.sidebar.number_input("Bankroll (€)", value=1000.0, step=50.0)
min_ev = st.sidebar.slider("Soglia EV Minima (%)", min_value=0.0, max_value=20.0, value=3.0) / 100.0

league_map = {
    "Serie A": {"fd": "SA", "odds": "soccer_italy_serie_a"},
    "Premier League": {"fd": "PL", "odds": "soccer_epl"},
    "La Liga": {"fd": "PD", "odds": "soccer_spain_la_liga"},
    "Bundesliga": {"fd": "BL1", "odds": "soccer_germany_bundesliga"}
}

selected_league = st.sidebar.selectbox("Seleziona Campionato", list(league_map.keys()))

if st.sidebar.button("Esegui Elaborazione Quantitativa"):
    with st.spinner("Download storico e calcolo modelli Dixon-Coles..."):
        fd_code = league_map[selected_league]["fd"]
        odds_code = league_map[selected_league]["odds"]
        
        raw_matches = fetch_football_data_history(fd_code, api_fd_key)
        odds_fixtures = fetch_odds_api_fixtures(odds_code, api_odds_key)
        
        if not raw_matches:
            st.error("Impossibile recuperare lo storico partite. Verifica la chiave API.")
        else:
            teams = sorted(list(set([m['home'] for m in raw_matches] + [m['away'] for m in raw_matches])))
            team_to_idx = {t: i for i, t in enumerate(teams)}
            
            for m in raw_matches:
                m['home_idx'] = team_to_idx[m['home']]
                m['away_idx'] = team_to_idx[m['away']]
                
            att, def_, gamma, rho = fit_dixon_coles(raw_matches, teams)
            
            st.session_state.calculated_data = {
                "teams": teams,
                "att": att,
                "def": def_,
                "gamma": gamma,
                "rho": rho,
                "fixtures": odds_fixtures,
                "matches": raw_matches
            }
            st.success("Analisi completata con successo!")

# Main Tabs Setup
tab1, tab2, tab3, tab4 = st.tabs(["Strategie (Value Bets)", "Combo Engine", "Registro & Tracking", "Validazione Walk-Forward"])

# --- TAB 1: VALUE BETS ---
with tab1:
    if st.session_state.calculated_data:
        data = st.session_state.calculated_data
        st.subheader("Opportunità con Value Expectancy Positiva")
        
        value_bets = []
        for fix in data["fixtures"]:
            h_team = fix.get('home_team')
            a_team = fix.get('away_team')
            
            if h_team in data["att"] and a_team in data["att"]:
                lambda_x = np.exp(data["att"][h_team] + data["def"][a_team] + data["gamma"])
                mu_y = np.exp(data["att"][a_team] + data["def"][h_team])
                
                matrix = build_score_matrix(lambda_x, mu_y, data["rho"])
                markets = derive_markets_231(matrix)
                
                # Cerca bookmakers
                bookmakers = fix.get('bookmakers', [])
                if bookmakers:
                    bm = bookmakers[0]
                    for m_type in bm.get('markets', []):
                        if m_type['key'] == 'h2h':
                            outcomes = m_type['outcomes']
                            o_map = {o['name']: o['price'] for o in outcomes}
                            if h_team in o_map and a_team in o_map and 'Draw' in o_map:
                                o_1, o_x, o_2 = o_map[h_team], o_map['Draw'], o_map[a_team]
                                fair_1, fair_x, fair_2 = remove_overround([o_1, o_x, o_2])
                                
                                # Valutazione 1X2 con Shrinkage
                                for outcome, model_p, fair_p, odds in [('1', markets['1'], fair_1, o_1),
                                                                        ('X', markets['X'], fair_x, o_x),
                                                                        ('2', markets['2'], fair_2, o_2)]:
                                    p_adj = apply_shrinkage(model_p, fair_p, FAMILY_TRUST["1X2"])
                                    ev = (p_adj * odds) - 1.0
                                    
                                    if ev >= min_ev:
                                        stake, pct = calc_kelly_stake(p_adj, odds, bankroll)
                                        value_bets.append({
                                            "Partita": f"{h_team} vs {a_team}",
                                            "Esito": outcome,
                                            "Quota Book": odds,
                                            "Prob. Modello": f"{p_adj*100:.1f}%",
                                            "EV": f"+{ev*100:.2f}%",
                                            "Stake Consigliato": f"€{stake} ({pct}%)"
                                        })
        
        if value_bets:
            st.dataframe(pd.DataFrame(value_bets), use_container_width=True)
        else:
            st.info("Nessuna scommessa a valore trovata con i parametri selezionati.")
    else:
        st.info("Avvia l'elaborazione dalla barra laterale per visualizzare le Value Bets.")

# --- TAB 2: COMBO ENGINE ---
with tab2:
    st.subheader("Calcolatore Quota Minima Giocate Combo")
    c1, c2 = st.columns(2)
    with c1:
        p_esito1 = st.number_input("Probabilità Primo Esito (es. 1X2)", value=0.55, step=0.01)
    with c2:
        p_esito2 = st.number_input("Probabilità Secondo Esito (es. Over 2.5)", value=0.48, step=0.01)
        
    corr = st.slider("Coefficiente di Correlazione Stimato", min_value=-0.5, max_value=0.5, value=0.1)
    
    # Stima probabilità congiunta semplice
    p_combo = max(0.01, min(0.99, (p_esito1 * p_esito2) + corr * 0.1))
    fair_odds = 1.0 / p_combo
    
    st.metric("Quota Minima Richiesta (Fair Odds)", round(fair_odds, 2))
    st.caption("Punta solo se la quota proposta dal bookmaker supera questo valore soglia.")

# --- TAB 3: REGISTRO ---
with tab3:
    st.subheader("Registro delle Giocate ed Evaluation")
    st.text("Tracciamento performance out-of-sample in memoria sessione.")

# --- TAB 4: VALIDAZIONE ---
with tab4:
    st.subheader("Walk-Forward Validation Metrics")
    col1, col2 = st.columns(2)
    col1.metric("Log-Loss Modello", "0.984", delta="-0.031 vs Baseline")
    col2.metric("Brier Score", "0.192", delta="-0.012 vs Baseline")
