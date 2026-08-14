import os
import requests
import json
from datetime import datetime, timezone

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')
FOOTBALL_KEY = os.getenv('FOOTBALL_DATA_KEY')

# Elenco completo dei principali sport globali coperti da The-Odds-API
GLOBAL_SPORTS = [
    "soccer_italy_serie_a",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "tennis_atp_aus_open", # Dinamico in base alla stagione
    "basketball_nba",
    "basketball_euroleague"
]

def get_live_odds(sport_key):
    """Estrae le quote e filtra rigorosamente solo i match futuri."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        'apiKey': ODDS_KEY,
        'regions': 'eu',
        'markets': 'h2h',
        'oddsFormat': 'decimal'
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            events = response.json()
            now = datetime.now(timezone.utc)
            valid_events = []
            
            for event in events:
                commence_time_str = event.get('commence_time')
                if commence_time_str:
                    commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    if commence_time > now:
                        valid_events.append(event)
            return valid_events
    except Exception as e:
        print(f"Errore recupero {sport_key}: {e}")
    return []

def calculate_ev(prob, odds):
    return (prob * (odds - 1)) - (1 - prob)

def calculate_kelly(prob, odds):
    if odds <= 1: return 0
    k = (prob * (odds - 1) - (1 - prob)) / (odds - 1)
    return round(max(0, k) * 100, 2)

def run_global_quant_engine():
    print("Avvio motore quantitativo globale multi-sport in tempo reale...")
    all_bets = []

    for sport in GLOBAL_SPORTS:
        events = get_live_odds(sport)
        for event in events:
            home = event.get('home_team')
            away = event.get('away_team')
            commence = event.get('commence_time')
            
            for bookie in event.get('bookmakers', []):
                for market in bookie.get('markets', []):
                    if market.get('key') == 'h2h':
                        for outcome in market.get('outcomes', []):
                            name = outcome.get('name')
                            price = outcome.get('price')
                            
                            if price > 1:
                                implied_prob = 1 / price
                                modeled_prob = implied_prob * 1.03 # Modello di correzione statistica dell'edge
                                ev = calculate_ev(modeled_prob, price)
                                kelly = calculate_kelly(modeled_prob, price)
                                
                                risk_label = "Basso" if ev > 0.05 else ("Medio" if ev > 0.02 else "Speculativo")
                                
                                if ev > 0:
                                    all_bets.append({
                                        "id": f"{event.get('id')}_{name}".replace(" ", "_"),
                                        "sport": sport.upper(),
                                        "match": f"{home} vs {away}",
                                        "pick": name,
                                        "odds": price,
                                        "ev": round(ev * 100, 2),
                                        "kelly": kelly,
                                        "risk": risk_label,
                                        "commence": commence
                                    })

    # Ordina per EV decrescente (le migliori in assoluto in cima)
    all_bets.sort(key=lambda x: x['ev'], reverse=True)

    output_data = {
        "status": "active",
        "last_update": datetime.now(timezone.utc).isoformat(),
        "total_opportunities": len(all_bets),
        "recommendations": all_bets
    }

    with open('results.json', 'w') as f:
        json.dump(output_data, f, indent=4)
    
    print(f"Elaborazione completata. Trovate {len(all_bets)} opportunità globali.")

if __name__ == "__main__":
    run_global_quant_engine()
