import streamlit as st
import requests
import time
from datetime import datetime, timezone, timedelta
import re

# --- LIBRERIE AI ---
try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from groq import Groq
except ImportError:
    Groq = None

st.set_page_config(page_title="Bet-Pro | Quant Engine Alpha", page_icon="⚙️", layout="wide")

# --- CONFIGURAZIONE CHIAVI (Da Streamlit Secrets) ---
API_FOOTBALL_KEYS = [k.strip() for k in st.secrets.get("API_FOOTBALL_KEYS", "").split(",") if k.strip()]
API_DATA_KEYS = [k.strip() for k in st.secrets.get("API_FOOTBALL_DATA_KEYS", "").split(",") if k.strip()]
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

# --- PALINSESTO LOCALE (ESTREMA RATIO IN CASO DI BLACKOUT GLOBALE) ---
def get_fallback_fixtures(oggi_str):
    return f"""--- PALINSESTO ELITE ---
[{oggi_str} 20:45] Atalanta vs Lecce | L: Serie A | Quote: 1: 1.45 | X: 4.30 | 2: 7.50
[{oggi_str} 21:00] Villarreal vs Atl. Madrid | L: La Liga | Quote: 1: 2.65 | X: 3.20 | 2: 2.70
--- PALINSESTO GLOBALE ---
[{oggi_str} 19:00] AIK vs Djurgården | L: Allsvenskan | Quote: 1: 2.50 | X: 3.30 | 2: 2.80"""

# --- MOTORE DI ESTRAZIONE DATI A CASCATA (9 SLOT) ---
def fetch_real_matches_and_odds():
    italy_tz = timezone(timedelta(hours=2))
    oggi_dt = datetime.now(italy_tz)
    oggi_str = oggi_dt.strftime("%Y-%m-%d")
    
    status_msg = st.empty()
    elite_keywords = ["serie a", "serie b", "coppa italia", "champions league", "europa league", "conference league", "premier league", "la liga", "bundesliga", "ligue 1"]
    
    # 1. TENTATIVO CON LE 3 CHIAVI API-FOOTBALL (Include estrazione Quote)
    for i, key in enumerate(API_FOOTBALL_KEYS):
        status_msg.info(f"🔄 Ricerca match odierni... Test API-Sports (Chiave {i+1}/3)")
        try:
            headers = {"x-rapidapi-host": "v3.football.api-sports.io", "x-rapidapi-key": key}
            # Estrae SOLO partite di oggi
            r_fixtures = requests.get(f"https://v3.football.api-sports.io/fixtures?date={oggi_str}", headers=headers, timeout=6)
            
            if r_fixtures.status_code == 200 and r_fixtures.json().get("response"):
                all_matches = r_fixtures.json()["response"]
                filtered_matches = [m for m in all_matches if m.get('fixture', {}).get('status', {}).get('short') in ['NS', 'TBD']]
                
                if not filtered_matches: continue
                
                elite_list, global_list = [], []
                
                for m in filtered_matches:
                    f = m['fixture']
                    f_id = f.get('id')
                    match_time = datetime.fromtimestamp(f.get('timestamp', 0), tz=timezone.utc).astimezone(italy_tz).strftime('%H:%M')
                    home = m.get('teams', {}).get('home', {}).get('name', 'Casa')
                    away = m.get('teams', {}).get('away', {}).get('name', 'Ospite')
                    league_name = m.get('league', {}).get('name', 'League')
                    
                    # Estrazione Quote (Solo per API-Football)
                    odds_str = "Quote standard/da calcolare"
                    if f_id:
                        try:
                            r_odds = requests.get(f"https://v3.football.api-sports.io/odds?fixture={f_id}&bookmaker=8", headers=headers, timeout=2)
                            if r_odds.status_code == 200 and r_odds.json().get("response"):
                                bets = r_odds.json()["response"][0].get("bookmakers", [{}])[0].get("bets", [])
                                winner = next((b for b in bets if b.get("id") == 1), None)
                                if winner and len(winner.get("values", [])) >= 3:
                                    v = winner["values"]
                                    odds_str = f"1: {v[0]['odd']} | X: {v[1]['odd']} | 2: {v[2]['odd']}"
                        except: pass

                    match_line = f"[{oggi_dt.strftime('%d/%m')} {match_time}] {home} vs {away} | L: {league_name} | Quote Reali: {odds_str}"
                    if any(kw in league_name.lower() for kw in elite_keywords): elite_list.append(match_line)
                    else: global_list.append(match_line)
                
                status_msg.success(f"✅ Dati estratti con successo da API-Sports (Chiave {i+1}).")
                time.sleep(1)
                status_msg.empty()
                
                final_data = "--- PALINSESTO ELITE ---\n" + ("\n".join(elite_list) if elite_list else "Nessun match elite oggi.")
                final_data += "\n\n--- PALINSESTO GLOBALE ---\n" + "\n".join(global_list[:25])
                return final_data

        except Exception: continue

    # 2. TENTATIVO CON LE 6 CHIAVI FOOTBALL-DATA (Fallback se le prime 3 falliscono)
    for i, key in enumerate(API_DATA_KEYS):
        status_msg.info(f"⚠️ API-Sports esaurite. Test Football-Data (Chiave {i+1}/6)")
        try:
            headers = {"X-Auth-Token": key}
            r = requests.get(f"https://api.football-data.org/v4/matches?date={oggi_str}", headers=headers, timeout=6)
            if r.status_code == 200 and r.json().get("matches"):
                matches = r.json()["matches"]
                data_lines = []
                for m in matches:
                    if m.get('status') == 'SCHEDULED':
                        home = m.get('homeTeam', {}).get('name', 'Casa')
                        away = m.get('awayTeam', {}).get('name', 'Ospite')
                        comp = m.get('competition', {}).get('name', 'League')
                        data_lines.append(f"[{oggi_dt.strftime('%d/%m')} Orario ND] {home} vs {away} | L: {comp} | Quote Reali: Valutazione AI richiesta")
                
                status_msg.success(f"✅ Dati estratti con successo da Football-Data (Chiave {i+1}).")
                time.sleep(1)
                status_msg.empty()
                return "--- PALINSESTO MISTO (Football-Data) ---\n" + "\n".join(data_lines[:30])
        except Exception: continue

    status_msg.error("❌ Tutte le 9 chiavi API sono down. Attivazione emergenza locale.")
    return get_fallback_fixtures(oggi_dt.strftime('%d/%m'))

# --- MOTORE AI INTEGRATO CON REALITY CHECK ASSOLUTO ---
def run_integrated_ai_engine(match_data):
    oggi_str = datetime.now().strftime("%d/%m/%Y")
    
    # PROMPT BLINDATO: OBBLIGO DI REALITY CHECK
    system_instruction = (
        f"Sei il 'Quant Engine Alpha', la più avanzata AI di analisi sportiva. Oggi è il {oggi_str}.\n"
        "REGOLE INVALICABILI:\n"
        "1. Analizza SOLO ed ESCLUSIVAMENTE le partite fornite nel palinsesto. Non inventare match.\n"
        "2. REALITY CHECK OBBLIGATORIO: Non limitarti a leggere i numeri delle quote. Incrocia le quote con le probabili formazioni, gli infortuni attuali e il contesto reale. Se una squadra è favorita ma ha i giocatori migliori infortunati (es. analogia assenza stelle), NON dare la vittoria fissa ma cerca coperture (es. Gol, Multigol, X2).\n"
        "3. Se le quote non sono presenti nel prompt, deduce i favoriti in base al divario tecnico reale odierno e motiva.\n\n"
        "FORMATO DI OUTPUT (RISPETTALO ALLA LETTERA):\n\n"
        "**STRATEGIA 1: Schedina Global Daily 50€**\n\n"
        "Match e Orario: [Data e Ora]\n"
        "[Casa] vs [Ospite]\n"
        "Esito e Reality Check: [Pronostico]\n"
        "Quota: [Quota reale o stimata]\n"
        "Analisi Logica: [Spiega come l'assenza di giocatori o il contesto ha influenzato questo pronostico rispetto alla sola quota]\n\n"
        "(Ripeti per i migliori 5 eventi globali/misti)\n\n"
        "*Quota Totale: [Totale]*\n"
        "*Protocollo: Toro (Puntata 5€)*\n\n"
        "**STRATEGIA 2: Specchietto Dedicato Elite (Top League)**\n\n"
        "Match e Orario: [Data e Ora]\n"
        "[Casa] vs [Ospite]\n"
        "Esito e Reality Check: [Pronostico]\n"
        "Quota: [Quota]\n"
        "Analisi Logica: [Analisi rigorosa integrata con infortuni/formazioni]\n\n"
        "(Ripeti per i migliori 5 eventi Elite)\n\n"
        "*Quota Totale: [Totale]*\n"
        "*Protocollo: Orso (Puntata 3€)*"
    )
    
    user_prompt = f"Palinsesto filtrato di OGGI ({oggi_str}):\n{match_data}\nEsegui l'incrocio quote-realtà e genera l'output."

    # TENTATIVO 1: GEMINI (Il Re del Reality Check per via delle basi dati aggiornate)
    if GEMINI_API_KEY and genai:
        try:
            genai.configure(api_key=GEMINI_API_KEY.strip())
            model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_instruction)
            response = model.generate_content(user_prompt)
            if response and response.text:
                return f"🧠 **[AI ENGINE: GEMINI (Reality Check Primario)]**\n\n{response.text}"
        except Exception as e:
            pass # Scivola a Groq

    # TENTATIVO 2: GROQ / LLAMA 3 (Backup iper-veloce se Gemini cade)
    if GROQ_API_KEY and Groq:
        try:
            client = Groq(api_key=GROQ_API_KEY.strip())
            res = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            return f"⚡ **[AI ENGINE: GROQ (Fallback Quantitativo)]**\n\n{res.choices[0].message.content}"
        except Exception as e:
            pass

    return "❌ Errore critico in entrambi i cervelli AI. Verifica le tue API Keys di Gemini e Groq."

# --- UI STREAMLIT ---
st.title("⚙️ Bet-Pro | Quant Engine Alpha")
st.markdown("*Motore a 9 API con Reality Check e Dual-AI Integration*")

if st.button("🚀 Inizializza Motore (Analizza Solo Oggi)", type="primary"):
    with st.spinner("Sincronizzazione dati live e incrocio algoritmi..."):
        # 1. Recupera i dati incrociando le 9 API
        raw_data = fetch_real_matches_and_odds()
        
        # 2. Invia i dati all'intelligenza artificiale per il Reality Check
        final_analysis = run_integrated_ai_engine(raw_data)
        
        # 3. Salva in sessione per visualizzarlo
        st.session_state["analysis"] = final_analysis

if "analysis" in st.session_state:
    st.markdown("---")
    st.markdown(st.session_state["analysis"])
    
