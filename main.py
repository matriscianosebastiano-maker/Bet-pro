import os
import requests
import json
from datetime import datetime

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')
GLOBAL_SPORTS = [
    "soccer_italy_serie_a", 
    "soccer_epl", 
    "soccer_spain_la_liga", 
    "soccer_germany_bundesliga",
    "basketball_nba"
]

def run_engine():
    recommendations = []
    
    for sport in GLOBAL_SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            'apiKey': ODDS_KEY, 
            'regions': 'eu', 
            'markets': 'h2h', 
            'oddsFormat': 'decimal'
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                events = response.json()
                for e in events:
                    home = e.get('home_team')
                    away = e.get('away_team')
                    commence_time = e.get('commence_time')
                    bookmakers = e.get('bookmakers', [])
                    
                    if not bookmakers:
                        continue
                    
                    # Prendiamo il primo bookmaker disponibile per pulire il palinsesto
                    bookie = bookmakers[0]
                    markets = bookie.get('markets', [])
                    
                    match_data = {
                        'sport': sport,
                        'home_team': home,
                        'away_team': away,
                        'commence_time': commence_time,
                        'bookmaker': bookie.get('title'),
                        'odds': {}
                    }
                    
                    # Estrazione delle quote dal mercato h2h
                    for market in markets:
                        if market.get('key') == 'h2h':
                            for outcome in market.get('outcomes', []):
                                name = outcome.get('name')
                                price = outcome.get('price')
                                match_data['odds'][name] = price
                    
                    if match_data['odds']:
                        recommendations.append(match_data)
                        
            else:
                print(f"Errore {response.status_code} per lo sport {sport}: {response.text}")
                
        except requests.exceptions.RequestException as req_err:
            print(f"Errore di connessione o timeout per {sport}: {req_err}")
            
    return recommendations

if __name__ == "__main__":
    results = run_engine()
    print(json.dumps(results, indent=4, ensure_ascii=False))
