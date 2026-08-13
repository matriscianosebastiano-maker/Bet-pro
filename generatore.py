from datetime import datetime

oggi = datetime.now().strftime("%d/%m/%Y")
ora = datetime.now().strftime("%H:%M")

html_content = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>BetBot Master Pro</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --accent: #22c55e;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
            --tag-bg: #0f172a;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 15px;
            padding-bottom: 90px;
        }}
        header {{
            background: #1e293b;
            padding: 15px;
            border-radius: 12px;
            border: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}
        header h1 {{ font-size: 16px; margin: 0; color: var(--accent); }}
        .bankroll-badge {{ background: var(--tag-bg); padding: 5px 10px; border-radius: 20px; font-size: 12px; border: 1px solid var(--border); }}
        .card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 15px;
            border: 1px solid var(--border);
        }}
        .card-header {{ display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: bold; margin-bottom: 8px; }}
        .match-title {{ font-size: 15px; font-weight: bold; margin-bottom: 10px; }}
        .match-details {{
            background: var(--tag-bg);
            padding: 10px;
            border-radius: 8px;
            font-size: 13px;
            margin-bottom: 12px;
            border-left: 4px solid var(--accent);
            line-height: 1.4;
        }}
        .market-tag {{
            display: inline-block;
            background: #0284c7;
            color: white;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .btn {{
            background: var(--accent);
            color: #000;
            border: none;
            width: 100%;
            padding: 12px;
            border-radius: 8px;
            font-weight: bold;
            font-size: 14px;
            cursor: pointer;
        }}
    </style>
</head>
<body>

    <header>
        <h1>⚡ BetBot ({oggi})</h1>
        <div class="bankroll-badge">Budget: <b>35.00€</b></div>
    </header>

    <div class="container">
        <div class="card">
            <div class="card-header"><span>Stato Cloud</span><span>Live Sync</span></div>
            <div class="match-title">Sincronizzazione Automatica Attiva</div>
            <div class="match-details">
                <span class="market-tag">Aggiornato alle {ora}</span><br>
                🎯 Il sistema in cloud è operativo e pronto per scaricare i palinsesti giornalieri.
            </div>
            <button class="btn" onclick="alert('Sistema operativo e sincronizzato!')">Verifica Stato</button>
        </div>
    </div>

</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print("index.html generato correttamente.")
