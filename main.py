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
        params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': 'h2h', 'oddsFormat': 'decimal'}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                events = response.json()
                for e in events:
                    home = e.get('home_team')
                    away = e.get('away_team')
                    bookmakers = e.get('bookmakers', [])
                    if not bookmakers:
                        continue
                    
                    bookie = bookmakers[0]
                    
                    for m in bookie.get('markets', []):
                        if m.get('key') == 'h2h':
                            outcomes = m.get('outcomes', [])
                            if not outcomes:
                                continue
                            
                            implied_probs = []
                            valid_outcomes = []
                            
                            for out in outcomes:
                                price = float(out.get('price', 0))
                                if price > 1.05:
                                    implied_probs.append(1.0 / price)
                                    valid_outcomes.append((out.get('name'), price))
                            
                            if not implied_probs:
                                continue
                            
                            total_margin = sum(implied_probs)
                            if total_margin <= 0:
                                continue
                            
                            match_outcomes = []
                            for name, price in valid_outcomes:
                                raw_imp = 1.0 / price
                                true_prob = round((raw_imp / total_margin) * 100, 1)
                                ev = round(((price * (true_prob / 100)) - 1) * 100, 2)
                                
                                if name == home:
                                    label = f"1 - Vittoria Casa ({home})"
                                elif name == away:
                                    label = f"2 - Vittoria Trasferta ({away})"
                                else:
                                    label = "X - Pareggio"
                                    
                                match_outcomes.append({
                                    "pick": label,
                                    "odds": price,
                                    "prob": true_prob,
                                    "ev": ev
                                })
                            
                            if match_outcomes:
                                best_option = max(match_outcomes, key=lambda x: x['ev'])
                                
                                if best_option['ev'] > 5.0:
                                    risk = "Ottimo Valore (EV+)"
                                elif best_option['ev'] > 0:
                                    risk = "Valore Moderato (EV+)"
                                else:
                                    risk = "Standard / Sotto Margine"

                                recommendations.append({
                                    "id": f"{e.get('id')}_{best_option['pick']}".replace(" ", "_"),
                                    "sport": sport.split('_')[0].upper(),
                                    "match": f"{home} vs {away}",
                                    "pick": best_option['pick'],
                                    "odds": best_option['odds'],
                                    "prob": best_option['prob'],
                                    "ev": best_option['ev'],
                                    "risk": risk,
                                    # Flag per ordinamento: 1 se EV positivo (vantaggiosa), 0 altrimenti
                                    "is_positive": 1 if best_option['ev'] > 0 else 0,
                                    "score": best_option['ev']
                                })
        except Exception as ex:
            print(f"Errore {sport}: {ex}")
            continue
    
    # Ordinamento strategico: 
    # 1. Prima le giocate con EV positivo (vantaggiose)
    # 2. A parità di categoria, ordinate per Expected Value più alto
    recommendations.sort(key=lambda x: (x['is_positive'], x['score']), reverse=True)
    
    top_pick = recommendations[0] if recommendations else None
    
    output = {
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "top_pick": top_pick,
        "recommendations": recommendations[:20]
    }
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
    print("Analisi statistica ordinata completata.")

if __name__ == "__main__":
    run_engine()
    
