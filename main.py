import os
import requests
import json
from datetime import datetime

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')
GLOBAL_SPORTS = ["soccer_italy_serie_a", "soccer_epl", "soccer_spain_la_liga"]

def run_engine():
    best_bets = {} 

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
                                    price = float(out.get('price', 0))
                                    if price < 1.10: continue
                                    
                                    # Calcolo probabilistico
                                    implied_prob = (1 / price) * 100
                                    # Calcolo EV (stima di valore)
                                    ev = round((implied_prob * 1.05) - 100, 2)
                                    
                                    # Definizione insight matematico
                                    insight = "NEUTRAL"
                                    if implied_prob > 65: insight = "SICURA"
                                    elif ev > 5: insight = "VALUE"
                                    elif price > 3.0: insight = "BIG"
                                    
                                    key = f"{e['id']}_{out['name']}"
                                    if key not in best_bets or price > best_bets[key]['odds']:
                                        best_bets[key] = {
                                            "id": key,
                                            "match": f"{e['home_team']} vs {e['away_team']}",
                                            "pick": out['name'],
                                            "odds": price,
                                            "prob": round(implied_prob, 1),
                                            "ev": ev,
                                            "insight": insight
                                        }
        except: continue
    
    # Ordiniamo per score di confidenza (Priorità: Probabilità Alta + Valore)
    final_list = sorted(list(best_bets.values()), key=lambda x: x['prob'], reverse=True)
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": datetime.now().strftime("%d/%m %H:%M"), "recommendations": final_list}, f, ensure_ascii=False)

if __name__ == "__main__":
    run_engine()
    
