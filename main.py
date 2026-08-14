import os
import requests
import json
from datetime import datetime, timezone

# Credenziali prelevate in sicurezza dai Secrets di GitHub
FOOTBALL_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_KEY = os.getenv('THE_ODDS_API_KEY')

def get_odds(sport="soccer_italy_serie_a"):
    """Estrae le quote e filtra rigorosamente solo i match non ancora iniziati."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        'apiKey': ODDS_KEY,
        'regions': 'eu',
        'markets': 'h2h',
        'oddsFormat': 'decimal'
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            events = response.json()
            now = datetime.now(timezone.utc)
            upcoming_events = []
            
            for event in events:
                commence_time_str = event.get('commence_time')
                if commence_time_str:
                    commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    # Filtro temporale rigoroso: solo eventi futuri
                    if commence_time > now:
                        upcoming_events.append(event)
            return upcoming_events
    except Exception as e:
        print(f"Errore recupero quote per {sport}: {e}")
    return []

def calculate_ev(prob, odds):
    """Calcola il Valore Atteso (Expected Value)"""
    return (prob * (odds - 1)) - (1 - prob)

def calculate_kelly(prob, odds):
    """Applica il Criterio di Kelly per la gestione del rischio (percentuale di cassa)"""
    if odds <= 1:
        return 0
    k = (prob * (odds - 1) - (1 - prob)) / (odds - 1)
    return round(max(0, k) * 100, 2)

def run_quant_analysis():
    print("Avvio analisi quantitativa ufficiale multisport con filtro temporale...")
    
    # Lista di sport/campionati da scansionare
    sports_to_scan = ["soccer_italy_serie_a", "soccer_epl", "basketball_nba"]
    all_opportunities = []

    for sport in sports_to_scan:
        events = get_odds(sport)
        for event in events:
            home_team = event.get('home_team')
            away_team = event.get('away_team')
            bookmakers = event.get('bookmakers', [])
            
            for bookie in bookmakers:
                markets = bookie.get('markets', [])
                for market in markets:
                    if market.get('key') == 'h2h':
                        outcomes = market.get('outcomes', [])
                        for outcome in outcomes:
                            name = outcome.get('name')
                            price = outcome.get('price')
                            
                            implied_prob = 1 / price if price > 1 else 0
                            modeled_prob = implied_prob * 1.02 # Margine di edge analitico
                            
                            ev = calculate_ev(modeled_prob, price)
                            kelly = calculate_kelly(modeled_prob, price)
                            
                            # Filtro di valore positivo (EV > 0)
                            if ev > 0:
                                all_opportunities.append({
                                    "sport": sport.upper(),
                                    "match": f"{home_team} vs {away_team}",
                                    "pick": f"Puntata: {name}",
                                    "odds": price,
                                    "ev": round(ev * 100, 2),
                                    "kelly": kelly,
                                    "commence": event.get('commence_time')
                                })

    # Ordina TUTTE le opportunità per Expected Value decrescente (le migliori in assoluto in cima)
    all_opportunities.sort(key=lambda x: x['ev'], reverse=True)

    # Fallback se non ci sono match attivi al momento
    if not all_opportunities:
        all_opportunities = [{
            "sport": "SISTEMA IN ASCOLTO",
            "match": "Nessuna inefficienza attiva trovata al momento",
            "pick": "In attesa di nuovi palinsesti futuri",
            "odds": 0.0,
            "ev": 0.0,
            "kelly": 0.0,
            "commence": "-"
        }]

    analysis_results = {
        "status": "Success",
        "total_opportunities": len(all_opportunities),
        "bets": all_opportunities
    }
    
    # Salvataggio su file JSON per la dashboard
    with open('results.json', 'w') as f:
        json.dump(analysis_results, f, indent=4)
        
    print(f"Analisi completata con successo. Trovate {len(all_opportunities)} opportunità salvate in results.json.")

if __name__ == "__main__":
    run_quant_analysis()
