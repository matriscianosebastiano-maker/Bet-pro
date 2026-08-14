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
    best_bets = {} 

    for sport in GLOBAL_SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': 'h2h', 'oddsFormat': 'decimal'}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                events = response.json()
                if isinstance(events, list):
                    for e in events:
                        for bookie in e.get('bookmakers', []):
                            for m in bookie.get('markets', []):
                                if m.get('key') == 'h2h':
                                    for out in m.get('outcomes', []):
                                        try:
                                            price = float(out.get('price', 0))
                                            if price <= 1.05: continue
                                            
                                            name = out.get('name')
                                            implied_prob = (1 / price) * 100
                                            ev = round((implied_prob * 1.05) - 100, 2)
                                            
                                            insight = "NEUTRAL"
                                            if implied_prob > 65: insight = "SICURA"
                                            elif ev > 5: insight = "VALUE"
                                            elif price > 2.5: insight = "BIG"
                                                
                                            key = f"{e.get('id')}_h2h_{name}"
                                            if key not in best_bets or price > best_bets[key]['odds']:
                                                best_bets[key] = {
                                                    "id": key,
                                                    "sport": sport.split('_')[0].upper(),
                                                    "match": f"{e.get('home_team')} vs {e.get('away_team')}",
                                                    "pick": name,
                                                    "odds": price,
                                                    "prob": round(implied_prob, 1),
                                                    "ev": ev,
                                                    "insight": insight
                                                }
                                        except:
                                            continue
        except Exception as ex:
            print(f"Errore {sport}: {ex}")
            continue
    
    final_list = sorted(list(best_bets.values()), key=lambda x: x['ev'], reverse=True)
    
    output = {
        "last_update": datetime.now().strftime("%d/%m %H:%M"),
        "recommendations": final_list
    }
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
    print(f"File salvato con successo: {len(final_list)} eventi.")

if __name__ == "__main__":
    run_engine()
    
