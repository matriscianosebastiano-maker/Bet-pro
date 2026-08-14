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
                    
                    # Prendiamo il primo bookmaker disponibile per pulire il palinsesto
                    bookie = bookmakers[0]
                    match_outcomes = []
                    
                    for m in bookie.get('markets', []):
                        if m.get('key') == 'h2h':
                            for out in m.get('outcomes', []):
                                name = out.get('name')
                                price = float(out.get('price', 0))
                                if price <= 1.05:
                                    continue
                                
                                # Nomenclatura standard bookmaker (1, X, 2)
                                if name == home:
                                    label = f"1 ({home})"
                                elif name == away:
                                    label = f"2 ({away})"
                                else:
                                    label = "X (Pareggio)"
                                    
                                prob = round((1 / price) * 100, 1)
                                ev = round((prob * 1.05) - 100, 2)
                                
                                match_outcomes.append({
                                    "pick": label,
                                    "odds": price,
                                    "prob": prob,
                                    "ev": ev
                                })
                    
                    if match_outcomes:
                        # Seleziona la quota con il valore statistico migliore per questo match
                        best_option = max(match_outcomes, key=lambda x: x['ev'])
                        
                        # Calcolo livello di rischio basato su probabilità e quota
                        if best_option['prob'] > 55:
                            risk = "Basso (Consigliato)"
                        elif best_option['prob'] > 35:
                            risk = "Medio (Buon Valore)"
                        else:
                            risk = "Alto (Speculativo)"

                        recommendations.append({
                            "id": f"{e.get('id')}_{best_option['pick']}",
                            "sport": sport.split('_')[0].upper(),
                            "match": f"{home} vs {away}",
                            "pick": best_option['pick'],
                            "odds": best_option['odds'],
                            "prob": best_option['prob'],
                            "ev": best_option['ev'],
                            "risk": risk
                        })
        except Exception as ex:
            print(f"Errore {sport}: {ex}")
            continue
    
    # Ordina per valore atteso (EV)
    recommendations.sort(key=lambda x: x['ev'], reverse=True)
    top_pick = recommendations[0] if recommendations else None
    
    output = {
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "top_pick": top_pick,
        "recommendations": recommendations[:12] # Mostra le migliori 12 opportunità uniche
    }
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
    print("Analisi completata con successo.")

if __name__ == "__main__":
    run_engine()
                                    
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
