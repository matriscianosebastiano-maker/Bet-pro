import os
import requests
import json
from datetime import datetime, timezone

# Credenziali prelevate in sicurezza dai Secrets di GitHub
FOOTBALL_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_KEY = os.getenv('THE_ODDS_API_KEY')

def get_standings(league_code="SA"):
    """Estrae le statistiche reali (gol fatti/subiti) da football-data.org (Es. SA = Serie A)"""
    url = f"https://api.football-data.org/v4/competitions/{league_code}/standings"
    headers = {'X-Auth-Token': FOOTBALL_KEY}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if 'standings' in data and len(data['standings']) > 0:
                return data['standings'][0].get('table', [])
    except Exception as e:
        print(f"Errore recupero dati statistici: {e}")
    return []

def get_odds(sport="soccer_italy_serie_a"):
    """Estrae le quote live e filtra rigorosamente solo i match non ancora iniziati."""
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
                    # Converte la stringa in datetime UTC
                    commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    
                    # Filtro temporale: scarta tutto ciò che è già iniziato o passato
                    if commence_time > now:
                        upcoming_events.append(event)
                        
            return upcoming_events
    except Exception as e:
        print(f"Errore recupero/filtraggio quote: {e}")
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
    print("Avvio analisi quantitativa multisorgente con filtro temporale...")
    
    # 1. Recupero dati statistici e quote future
    standings = get_standings("SA")
    odds_data = get_odds("soccer_italy_serie_a")
    
    valid_matches_count = len(odds_data)
    print(رحمن = f"Trovati {valid_matches_count} match futuri validi.")

    # Struttura dei risultati per la dashboard HTML
    analysis_results = {
        "status": "Success",
        "matches_analyzed": valid_matches_count,
        "top_bets": [
            {
                "sport": "Calcio (Serie A)",
                "match": f"Analisi eseguita su {valid_matches_count} eventi futuri",
                "pick": "In elaborazione algoritmi di Poisson & Kelly",
                "odds": 0.0,
                "ev": 0.0,
                "kelly": 0.0,
                "risk": "Controllato"
            }
        ]
    }
    
    # Salvataggio dei risultati in un file JSON per la visualizzazione
    with open('results.json', 'w') as f:
        json.dump(analysis_results, f, indent=4)
        
    print("Analisi completata e salvata con successo in results.json.")

if __name__ == "__main__":
    run_quant_analysis()
