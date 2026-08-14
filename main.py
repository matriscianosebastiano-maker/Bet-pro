import os
import requests
import json
from datetime import datetime

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')
GLOBAL_SPORTS = ["soccer_italy_serie_a", "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga"]

def calculate_risk(prob, ev):
    if prob > 65 and ev > 2: return "Basso (Stabile)"
    if prob > 50 and ev > 5: return "Medio (Valore)"
    return "Alto (Speculativo)"

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
                                    price = float(out.get('price', 0))
                                    if price < 1.30 or price > 4.00: continue # Filtro range quote utili
                                    
                                    prob = (1 / price) * 100
                                    ev = round(((prob * 1.05) - 100), 2) # Calcolo base EV
                                    risk = calculate_risk(prob, ev)
                                    score = (prob * 0.6) + (ev * 0.4)
                                    
                                    all_bets.append({
                                        "id": f"{e['id']}_{out['name']}",
                                        "sport": sport.split('_')[1].upper(),
                                        "match": f"{e['home_team']} vs {e['away_team']}",
                                        "pick": out['name'],
                                        "odds": price,
                                        "prob": round(prob, 1),
                                        "ev": ev,
                                        "risk": risk,
                                        "score": score
                                    })
        except: continue
    
    # Ordina per score e prendi la Top
    all_bets.sort(key=lambda x: x['score'], reverse=True)
    top_pick = all_bets[0] if all_bets else None
    
    output = {
        "last_update": datetime.now().strftime("%d/%m %H:%M"),
        "top_pick": top_pick,
        "recommendations": all_bets[:10] # Solo le migliori 10
    }
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    run_engine()
