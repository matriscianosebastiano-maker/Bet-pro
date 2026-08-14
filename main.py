import os
import requests
import json
from datetime import datetime, timezone

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')

GLOBAL_SPORTS = [
    "soccer_italy_serie_a", "soccer_epl", "soccer_spain_la_liga", 
    "soccer_germany_bundesliga", "soccer_france_ligue_one",
    "soccer_uefa_champions_league", "soccer_uefa_europa_league",
    "basketball_nba", "basketball_euroleague", "basketball_italy_lega_a",
    "tennis_atp_us_open", "tennis_wta_us_open"
]

def get_live_odds(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': 'h2h', 'oddsFormat': 'decimal'}
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            events = response.json()
            now = datetime.now(timezone.utc)
            valid = [e for e in events if datetime.fromisoformat(e.get('commence_time').replace('Z', '+00:00')) > now]
            return valid
    except Exception as e:
        print(f"[{sport_key}] Errore: {e}")
    return []

def run_global_quant_engine():
    all_bets = []
    print(f"--- INIZIO SCANSIONE {datetime.now()} ---")
    
    for sport in GLOBAL_SPORTS:
        events = get_live_odds(sport)
        for event in events:
            for bookie in event.get('bookmakers', []):
                for market in bookie.get('markets', []):
                    if market.get('key') == 'h2h':
                        for outcome in market.get('outcomes', []):
                            price = outcome.get('price')
                            if price and price > 1.05:
                                implied_prob = 1 / price
                                modeled_prob = implied_prob * 1.03  
                                if modeled_prob > 0.99: 
                                    modeled_prob = 0.99
                                    
                                ev = ((modeled_prob * price) - 1) * 100
                                if ev > 0:
                                    all_bets.append({
                                        "id": f"{event.get('id')}_{outcome.get('name')}",
                                        "sport": sport.upper().replace("_", " "),
                                        "match": f"{event.get('home_team')} vs {event.get('away_team')}",
                                        "pick": outcome.get('name'),
                                        "odds": price,
                                        "probability": round(modeled_prob * 100, 1),
                                        "ev": round(ev, 2)
                                    })

    all_bets.sort(key=lambda x: x['ev'], reverse=True)
    
    output = {
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_opportunities": len(all_bets),
        "recommendations": all_bets
    }
    
    with open('results.json', 'w') as f:
        json.dump(output, f, indent=4)
    print(f"--- SCANSIONE TERMINATA. Trovate {len(all_bets)} opportunità ---")

if __name__ == "__main__":
    run_global_quant_engine()
