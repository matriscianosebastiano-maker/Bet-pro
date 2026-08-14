import os
import requests
import json
from datetime import datetime

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')
GLOBAL_SPORTS = [
    "soccer_italy_coppa_italia",
    "soccer_italy_serie_a", 
    "soccer_epl", 
    "soccer_spain_la_liga", 
    "soccer_germany_bundesliga",
    "basketball_nba"
]

def run_engine():
    recommendations = []
    
    for sport in GLOBAL_SPORTS:
        # Richiediamo sia il mercato 1X2 (h2h) che i totali gol (totals) per i valori laterali
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            'apiKey': ODDS_KEY, 
            'regions': 'eu', 
            'markets': 'h2h,totals', 
            'oddsFormat': 'decimal'
        }
        
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
                        market_key = m.get('key')
                        outcomes = m.get('outcomes', [])
                        if not outcomes:
                            continue
                        
                        # --- ANALISI MERCATO 1X2 (H2H) ---
                        if market_key == 'h2h':
                            implied_probs = []
                            valid_outcomes = []
                            
                            for out in outcomes:
                                price = float(out.get('price', 0))
                                if price > 1.05:
                                    implied_probs.append(1.0 / price)
                                    valid_outcomes.append((out.get('name'), price))
                            
                            if not implied_probs or len(implied_probs) < 2:
                                continue
                            
                            total_margin = sum(implied_probs)
                            if total_margin <= 0:
                                continue
                            
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
                                    
                                if ev > 5.0:
                                    risk = "Ottimo Valore (EV+)"
                                elif ev > 0:
                                    risk = "Valore Moderato (EV+)"
                                else:
                                    risk = "Standard / Sotto Margine"

                                recommendations.append({
                                    "id": f"{e.get('id')}_{label}".replace(" ", "_"),
                                    "sport": sport.split('_')[0].upper(),
                                    "match": f"{home} vs {away}",
                                    "market": "1X2 (Esito Finale)",
                                    "pick": label,
                                    "odds": price,
                                    "prob": true_prob,
                                    "ev": ev,
                                    "risk": risk,
                                    "is_positive": 1 if ev > 0 else 0,
                                    "score": ev
                                })

                        # --- ANALISI MERCATO TOTALS (Valori Laterali Over/Under 2.5) ---
                        elif market_key == 'totals':
                            # Filtriamo solitamente la linea standard 2.5 gol
                            total_outcomes = [o for o in outcomes if float(o.get('point', 2.5)) == 2.5]
                            if len(total_outcomes) == 2:
                                implied_probs = []
                                valid_totals = []
                                
                                for out in total_outcomes:
                                    price = float(out.get('price', 0))
                                    if price > 1.05:
                                        implied_probs.append(1.0 / price)
                                        valid_totals.append((out.get('name'), price))
                                
                                if len(implied_probs) == 2:
                                    total_margin = sum(implied_probs)
                                    if total_margin > 0:
                                        for name, price in valid_totals:
                                            raw_imp = 1.0 / price
                                            true_prob = round((raw_imp / total_margin) * 100, 1)
                                            ev = round(((price * (true_prob / 100)) - 1) * 100, 2)
                                            
                                            label = f"Over 2.5" if name.lower() == 'over' else f"Under 2.5"
                                            
                                            if ev > 5.0:
                                                risk = "Ottimo Valore (EV+)"
                                            elif ev > 0:
                                                risk = "Valore Moderato (EV+)"
                                            else:
                                                risk = "Standard / Sotto Margine"

                                            recommendations.append({
                                                "id": f"{e.get('id')}_{label}".replace(" ", "_"),
                                                "sport": sport.split('_')[0].upper(),
                                                "match": f"{home} vs {away}",
                                                "market": "Under/Over 2.5 (Valore Laterale)",
                                                "pick": label,
                                                "odds": price,
                                                "prob": true_prob,
                                                "ev": ev,
                                                "risk": risk,
                                                "is_positive": 1 if ev > 0 else 0,
                                                "score": ev
                                            })
        except Exception as ex:
            print(f"Errore {sport}: {ex}")
            continue
    
    # Ordinamento strategico: prima le giocate con EV positivo, ordinate per valore decrescente
    recommendations.sort(key=lambda x: (x['is_positive'], x['score']), reverse=True)
    
    top_pick = recommendations[0] if recommendations else None
    
    output = {
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "top_pick": top_pick,
        "recommendations": recommendations[:25]
    }
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
    print("Analisi multi-mercato (1X2 + Totals) completata con successo.")

if __name__ == "__main__":
    run_engine()
