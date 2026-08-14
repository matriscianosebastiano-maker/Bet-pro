import os
import requests
import json
from datetime import datetime

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')

def get_active_competitions():
    # Recupera sport attivi, filtra per massimizzare efficienza API
    url = "https://api.the-odds-api.com/v4/sports/"
    try:
        response = requests.get(url, params={'apiKey': ODDS_KEY}, timeout=10)
        return [s['key'] for s in response.json() if s.get('active')] if response.status_code == 200 else []
    except: return []

def calculate_ev(price, prob_real):
    # EV = (Quota * Probabilità_Reale) - 1
    return round(((price * prob_real) - 1) * 100, 2)

def run_engine():
    all_recommendations = []
    sports = get_active_competitions()
    
    # Limita a 10 sport per evitare timeout su GitHub Actions (i più popolari)
    for sport in sports[:10]: 
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': 'h2h,totals', 'oddsFormat': 'decimal'}
        
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code != 200: continue
            
            for event in res.json():
                home, away = event.get('home_team'), event.get('away_team')
                bookmakers = event.get('bookmakers', [])
                if not bookmakers: continue
                
                # Prendiamo il primo bookmaker disponibile
                markets = bookmakers[0].get('markets', [])
                for m in markets:
                    outcomes = m.get('outcomes', [])
                    if not outcomes: continue
                    
                    # Logica di De-vigging (Rimozione margine banco)
                    prices = [float(o.get('price', 0)) for o in outcomes if float(o.get('price', 0)) > 1.05]
                    if len(prices) < 2: continue
                    
                    implied_probs = [1.0/p for p in prices]
                    margin = sum(implied_probs)
                    
                    for i, o in enumerate(outcomes):
                        p = float(o.get('price', 0))
                        if p <= 1.05: continue
                        
                        prob_real = (1.0/p) / margin
                        ev = calculate_ev(p, prob_real)
                        
                        all_recommendations.append({
                            "match": f"{home} vs {away}",
                            "sport": sport,
                            "market": m['key'],
                            "pick": o.get('name') if 'name' in o else o.get('point'),
                            "odds": p,
                            "ev": ev,
                            "is_positive": ev > 0
                        })
        except: continue

    # Ordina per EV decrescente
    all_recommendations.sort(key=lambda x: x['ev'], reverse=True)
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump({"data": all_recommendations[:40], "updated": datetime.now().strftime("%H:%M")}, f)

if __name__ == "__main__":
    run_engine()
