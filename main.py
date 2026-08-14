import os
import requests
import json
from datetime import datetime

ODDS_KEY = os.getenv('THE_ODDS_API_KEY')

# Lista estesa di sport supportati da The Odds API
GLOBAL_SPORTS = [
    "soccer_italy_serie_a", 
    "soccer_epl", 
    "soccer_spain_la_liga", 
    "soccer_germany_bundesliga", 
    "soccer_france_ligue_one",
    "soccer_uefa_champions_league",
    "basketball_nba", 
    "basketball_euroleague",
    "tennis_atp_aus_open", 
    "icehockey_nhl"
]

def run_engine():
    best_bets = {} 

    for sport in GLOBAL_SPORTS:
        # Richiediamo sia il mercato 1X2 (h2h) che i totali gol/punti (totals)
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {'apiKey': ODDS_KEY, 'regions': 'eu', 'markets': 'h2h,totals', 'oddsFormat': 'decimal'}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                events = response.json()
                for e in events:
                    for bookie in e.get('bookmakers', []):
                        for m in bookie.get('markets', []):
                            market_key = m.get('key')
                            for out in m.get('outcomes', []):
                                price = float(out.get('price', 0))
                                if price <= 1.10: continue
                                
                                name = out.get('name')
                                point = out.get('point')
                                
                                # Definizione intelligente della tipologia di giocata (Pick)
                                if market_key == 'totals':
                                    pick_label = f"{name} {point}"  # Es. Over 2.5 / Under 2.5
                                else:
                                    pick_label = name  # Es. 1, X, 2 o nome squadra
                                    
                                # Analisi matematica delle probabilità e del valore atteso (EV)
                                implied_prob = (1 / price) * 100
                                ev = round((implied_prob * 1.05) - 100, 2)
                                
                                # Insight statistico per la scommessa
                                insight = "NEUTRAL"
                                if implied_prob > 65: 
                                    insight = "SICURA"
                                elif ev > 5: 
                                    insight = "VALUE"
                                elif price > 2.5: 
                                    insight = "BIG"
                                    
                                key = f"{e['id']}_{market_key}_{pick_label}"
                                if key not in best_bets or price > best_bets[key]['odds']:
                                    best_bets[key] = {
                                        "id": key,
                                        "sport": sport.split('_')[0].upper(),
                                        "match": f"{e['home_team']} vs {e['away_team']}",
                                        "pick": pick_label,
                                        "odds": price,
                                        "prob": round(implied_prob, 1),
                                        "ev": ev,
                                        "insight": insight
                                    }
        except Exception as ex:
            continue
    
    # Ordinamento basato sul valore statistico (EV e probabilità)
    final_list = sorted(list(best_bets.values()), key=lambda x: x['ev'], reverse=True)
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": datetime.now().strftime("%d/%m %H:%M"), "recommendations": final_list[:120]}, f, ensure_ascii=False)

if __name__ == "__main__":
    run_engine()
    
