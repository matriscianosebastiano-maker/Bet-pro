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
                    # Filtro temporale: solo eventi futuri
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
    print("Avvio analisi quantitativa completa e filtro temporale...")
    
    # Lista di sport/campionati da scansionare (puoi aggiungere altri sport di The-Odds-API)
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
                        # Analizziamo le quote dei vari esiti (1X2 o Testa a Testa)
                        for outcome in outcomes:
                            name = outcome.get('name')
                            price = outcome.get('price') # Quota decimale
                            
                            # Stima euristica/statistica provvisoria della probabilità basata sulla quota implicita
                            # (Nel modulo avanzato qui subentrerà il modello di Poisson o Elo)
                            implied_prob = 1 / price if price > 1 else 0
                            
                            # Esempio di logica Value Bet: cerchiamo inefficienze
                            # Assegniamo una probabilità corretta dal modello (ipotetica di test o statistica)
                            modeled_prob = implied_prob * 1.02 # Esempio di edge calcolato
                            
                            ev = calculate_ev(modeled_prob, price)
                            kelly = calculate_kelly(modeled_prob, price)
                            
                            if ev > 0: # Filtro di valore positivo
                                all_opportunities.append({
                                    "sport": sport.upper(),
                                    "match": f"{home_team} vs {away_team}",
                                    "pick": f"Puntata su: {name}",
                                    "odds": price,
                                    "ev": round(ev * 100, 2),
                                    "kelly": kelly,
                                    "commence": event.get('commence_time')
                                })

    # Ordina le opportunità per Valore Atteso decrescente (il "Meglio del Meglio")
    all_opportunities.sort(key=lambda x: x['ev'], reverse=True)
    top_3_bets = all_opportunities[:3] # Prende le prime 3 in assoluto

    # Se non ci sono match con EV positivo al momento, inseriamo un placeholder descrittivo
    if not top_3_bets:
        top_3_bets = [{
            "sport": "Sistema in ascolto",
            "match": "Nessuna inefficienza attiva trovata al momento",
            "pick": "Attesa prossimi palinsesti",
            "odds": 0.0,
            "ev": 0.0,
            "kelly": 0.0
        }]

    analysis_results = {
        "status": "Success",
        "top_bets": top_3_bets
    }
    
    with open('results.json', 'w') as f:
        json.dump(analysis_results, f, indent=4)
        
    print(f"Analisi completata. Trovate {len(top_3_bets)} giocate di valore salvate in results.json.")

if __name__ == "__main__":
    run_quant_analysis()
