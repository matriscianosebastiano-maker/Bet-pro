import os
import requests
import json
from datetime import datetime

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')
GLOBAL_SPORTS = [
    "soccer_italy_serie_a", "soccer_epl", "soccer_spain_la_liga", 
    "soccer_germany_bundesliga", "soccer_france_ligue_one",
    "soccer_uefa_champions_league", "soccer_uefa_europa_league",
    "basketball_nba", "basketball_euroleague"
]

def run_engine():
    all_bets = []
    for sport in GLOBAL_SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': 'h2h', 'oddsFormat': 'decimal'}
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                events = response.json()
                for e in events:
                    for bookie in e.get('bookmakers', []):
                        for m in bookie.get('markets', []):
                            if m.get('key') == 'h2h':
                                for out in m.get('outcomes', []):
                                    price = out.get('price', 0)
                                    if price > 1.05:
                                        prob = (1 / price) * 1.03
                                        all_bets.append({
                                            "id": f"{e['id']}_{out['name']}",
                                            "sport": sport.replace("_", " ").upper(),
                                            "match": f"{e['home_team']} vs {e['away_team']}",
                                            "pick": out['name'],
                                            "odds": price,
                                            "probability": round(min(prob * 100, 99), 1),
                                            "ev": round(((prob * price) - 1) * 100, 2)
                                        })
        except Exception as err:
            print(f"Errore {sport}: {err}")
            continue
    
    all_bets.sort(key=lambda x: x['ev'], reverse=True)
    
    output = {
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "recommendations": all_bets
    }
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
    print(f"File salvato con {len(all_bets)} opportunità.")

if __name__ == "__main__":
    run_engine()
    
