"""
Bet-Pro | Quant Engine v6 — MONOFILE, PERCORSO GRATUITO
========================================================

Unico file da incollare come `app.py` su GitHub e deployare su
Streamlit Community Cloud. Nel repo serve solo requirements.txt:

    streamlit>=1.36
    requests>=2.31
    numpy>=1.26
    scipy>=1.11

SECRET (Streamlit Cloud -> Manage app -> Settings -> Secrets, MAI nel repo).
Configurazione gratuita e regolare, un account per servizio:

    ODDS_API_KEY = "chiave_the_odds_api"
    API_FOOTBALL_DATA_KEYS = "fd1,fd2,fd3"

  the-odds-api.com    500 richieste/mese. Una richiesta = quote di un intero
                      campionato -> ~8 al giorno. Ci sta con margine.
  football-data.org   storico dei risultati, per stimare il modello.

Alternativa, se hai un piano API-Sports valido: API_FOOTBALL_KEYS = "chiave".
Il percorso The Odds API ha la precedenza quando ODDS_API_KEY e' presente.


COME FUNZIONA, IN BREVE

  1. Dixon-Coles stima attacco e difesa di ogni squadra dai risultati storici,
     con decadimento temporale e shrinkage verso la media di lega.
  2. Dalla matrice dei punteggi derivano 231 classi di esito, esattamente.
  3. Le quote reali vengono ripulite dal margine del bookmaker.
  4. La probabilita' del modello viene ridotta verso quella di mercato in
     proporzione a quanto il modello e' realmente informato (shrinkage).
     E' il passaggio che impedisce di scambiare errore di stima per valore.
  5. EV e Kelly sulla quota migliore trovata; due strategie; motivazioni
     costruite da numeri, mai generate liberamente.


LE QUATTRO TAB CHE CONTANO

  Strategie   selezioni con motivazione, puntata consigliata, registrazione
  Combo       i mercati combinati non hanno quota sui provider gratuiti:
              il modello produce la QUOTA MINIMA e la confronti con il tuo
              bookmaker
  Registro    confronto tra promesso e accaduto. E' la tab che dice se tutto
              il resto funziona. Senza, non si impara nulla.
  Validazione backtest walk-forward: se il modello non batte il baseline su
              una lega, i suoi edge su quella lega sono rumore


INSTALLAZIONE COME APP SU ANDROID
Non serve un APK. Apri l'URL Streamlit in Chrome, menu tre puntini,
"Aggiungi a schermata Home": icona e avvio a schermo intero. Un APK sarebbe
comunque solo un browser attorno a questa pagina, perche' il modello gira su
scipy e ha bisogno di un server.


LIMITI DICHIARATI
  - il modello vede solo gol segnati e subiti: non conosce formazioni,
    squalifiche, motivazioni di classifica, calendario, meteo
  - niente mercati di primo tempo, corner, cartellini, marcatori: servirebbero
    modelli separati, quindi non vengono prodotti numeri su quei mercati
  - EV positivo significa discrepanza rispetto al mercato, non profitto:
    si realizza solo su volume ed e' compatibile con lunghe serie negative

Struttura interna (cerca i banner ===== per navigare):
   1. Modello Dixon-Coles          7. Parser mercati API-Sports
   2. I 231 mercati                8. Motore di valore
   3. Backtest walk-forward        9. Combo
   4. Quote The Odds API          10. Registro e staking
   5. Quote API-Sports            11. Motivazioni
   6. Storico football-data       12. Interfaccia Streamlit
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import numpy as np
import os
import re
import requests
import streamlit as st
import sys
import time
import traceback
from dataclasses import dataclass
from dataclasses import dataclass, asdict
from datetime import datetime
from datetime import datetime, timedelta, timezone
from datetime import datetime, timezone
from pathlib import Path
from requests.adapters import HTTPAdapter
from scipy.optimize import minimize
from scipy.stats import poisson
from zoneinfo import ZoneInfo


# ============================================================================
# MODELLO — Dixon-Coles
# ============================================================================
# Dixon-Coles (1997) con time-decay e regolarizzazione ridge.
#
# Modello:
#     lambda_home = exp(att[home] - dif[away] + gamma)
#     lambda_away = exp(att[away] - dif[home])
#     P(x,y)      = tau(x,y) * Pois(x|lambda_home) * Pois(y|lambda_away)
#
# tau corregge la dipendenza sui punteggi bassi, dove il Poisson indipendente
# sbaglia sistematicamente (troppi pochi 0-0 e 1-1).
#
# Identificabilita': mean(att) = 0 e mean(dif) = 0, imposte per centratura
# dentro la funzione obiettivo (non come vincolo esterno).
#
# Regolarizzazione: penalita' L2 su att/dif = shrinkage verso la media di lega.
# Serve per le squadre con poche partite, dove la MLE pura esplode.

MAX_GOALS = 12  # dimensione griglia punteggi (0..12 per lato)


# ---------------------------------------------------------------- tau

def _tau(x, y, lam, mu, rho):
    """Correzione Dixon-Coles sui 4 punteggi bassi. Vettorializzata."""
    t = np.ones_like(lam, dtype=float)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    t = np.where(m00, 1.0 - lam * mu * rho, t)
    t = np.where(m01, 1.0 + lam * rho, t)
    t = np.where(m10, 1.0 + mu * rho, t)
    t = np.where(m11, 1.0 - rho, t)
    return np.clip(t, 1e-9, None)


# ---------------------------------------------------------------- fit

@dataclass
class DCFit:
    teams: list[str]
    attack: dict[str, float]
    defence: dict[str, float]
    home_adv: float
    rho: float
    n_matches: int
    matches_per_team: dict[str, int]
    converged: bool
    loglik: float
    league: str = ""

    def lambdas(self, home: str, away: str) -> tuple[float, float] | None:
        if home not in self.attack or away not in self.attack:
            return None
        lam = np.exp(self.attack[home] - self.defence[away] + self.home_adv)
        mu = np.exp(self.attack[away] - self.defence[home])
        return float(lam), float(mu)

    def reliability(self, home: str, away: str) -> float:
        """0..1. Quanta fiducia riporre nella stima per questo match."""
        n_h = self.matches_per_team.get(home, 0)
        n_a = self.matches_per_team.get(away, 0)
        if n_h == 0 or n_a == 0:
            return 0.0
        base = min(n_h, n_a) / 25.0          # 25 partite = piena affidabilita'
        return float(np.clip(base, 0.0, 1.0) * (1.0 if self.converged else 0.6))


def fit_dixon_coles(
    home_teams: list[str],
    away_teams: list[str],
    home_goals: list[int],
    away_goals: list[int],
    days_ago: list[float],
    xi: float = 0.0019,          # half-life ~ 365 giorni
    ridge: float = 0.02,
    league: str = "",
) -> DCFit | None:
    """Stima i parametri via MLE pesata. Ritorna None se i dati sono insufficienti."""
    n = len(home_teams)
    if n < 40:
        return None

    teams = sorted(set(home_teams) | set(away_teams))
    idx = {t: i for i, t in enumerate(teams)}
    nt = len(teams)
    if nt < 6:
        return None

    hi = np.array([idx[t] for t in home_teams])
    ai = np.array([idx[t] for t in away_teams])
    hg = np.asarray(home_goals, dtype=int)
    ag = np.asarray(away_goals, dtype=int)
    w = np.exp(-xi * np.asarray(days_ago, dtype=float))
    w = w / w.mean()

    counts: dict[str, int] = {t: 0 for t in teams}
    for t in home_teams:
        counts[t] += 1
    for t in away_teams:
        counts[t] += 1

    def unpack(p):
        att = p[:nt]
        dif = p[nt:2 * nt]
        att = att - att.mean()      # centratura -> identificabilita'
        dif = dif - dif.mean()
        return att, dif, p[-2], np.clip(p[-1], -0.25, 0.25)

    def nll(p):
        att, dif, gamma, rho = unpack(p)
        lam = np.exp(att[hi] - dif[ai] + gamma)
        mu = np.exp(att[ai] - dif[hi])
        lam = np.clip(lam, 1e-6, 12.0)
        mu = np.clip(mu, 1e-6, 12.0)
        # tau non conserva la massa totale: senza normalizzare, la MLE
        # gonfia rho per guadagnare verosimiglianza. Z e' la costante esatta.
        p00 = np.exp(-lam - mu)
        p01 = p00 * mu
        p10 = p00 * lam
        p11 = p00 * lam * mu
        z = 1.0 + p00 * (-lam * mu * rho) + p01 * (lam * rho) \
            + p10 * (mu * rho) + p11 * (-rho)
        z = np.clip(z, 1e-9, None)

        ll = (poisson.logpmf(hg, lam)
              + poisson.logpmf(ag, mu)
              + np.log(_tau(hg, ag, lam, mu, rho))
              - np.log(z))
        pen = ridge * (np.sum(att ** 2) + np.sum(dif ** 2))
        return -float(np.sum(w * ll)) + pen

    x0 = np.concatenate([np.zeros(nt), np.zeros(nt), [0.25], [-0.05]])
    bounds = [(-3, 3)] * nt + [(-3, 3)] * nt + [(-1.0, 1.5), (-0.25, 0.25)]

    res = minimize(nll, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 2000, "maxfun": 200000,
                            "ftol": 1e-12, "gtol": 1e-9, "eps": 1e-7})

    att, dif, gamma, rho = unpack(res.x)
    return DCFit(
        teams=teams,
        attack={t: float(att[idx[t]]) for t in teams},
        defence={t: float(dif[idx[t]]) for t in teams},
        home_adv=float(gamma),
        rho=float(rho),
        n_matches=n,
        matches_per_team=counts,
        converged=bool(res.success),
        loglik=float(-res.fun),
        league=league,
    )


# ---------------------------------------------------------------- score matrix

def score_matrix(lam: float, mu: float, rho: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    """Matrice (max_goals+1)^2 delle probabilita' di ogni punteggio esatto."""
    x = np.arange(max_goals + 1)
    ph = poisson.pmf(x, lam)
    pa = poisson.pmf(x, mu)
    m = np.outer(ph, pa)

    m[0, 0] *= 1.0 - lam * mu * rho
    m[0, 1] *= 1.0 + lam * rho
    m[1, 0] *= 1.0 + mu * rho
    m[1, 1] *= 1.0 - rho

    m = np.clip(m, 0.0, None)
    total = m.sum()
    return m / total if total > 0 else m


# ============================================================================
# MERCATI — 231 classi di esito dalla matrice punteggi
# ============================================================================
# Da una matrice dei punteggi P(x,y) deriva OGNI classe di esito.
#
# Ogni mercato e' restituito come chiave canonica -> (p_win, p_push).
# p_push serve per handicap e linee intere (rimborso): senza, l'EV di
# "Under 3.0" o "AH -1.0" e' calcolato male.
#
# Coperti: 1X2, doppia chance, DNB, Over/Under (0.5-6.5 con quarti), BTTS,
# combo esito+goal, combo BTTS+goal, multigol, gol squadra, clean sheet,
# win to nil, pari/dispari, risultato esatto, gol totali esatti,
# handicap asiatico ed europeo, margine di vittoria.
#
# NON coperti: mercati di primo/secondo tempo, cartellini, corner, marcatori.
# Richiederebbero modelli separati; qualunque numero prodotto qui su quei
# mercati sarebbe inventato, quindi non vengono prodotti affatto.

Prob = tuple[float, float]  # (p_win, p_push)


def _grid(m: np.ndarray):
    n = m.shape[0]
    x = np.arange(n)[:, None] * np.ones((1, n))
    y = np.ones((n, 1)) * np.arange(n)[None, :]
    return x, y


def all_markets(m: np.ndarray) -> dict[str, Prob]:
    """m: matrice (N+1)x(N+1), m[x, y] = P(casa segna x, ospite segna y)."""
    x, y = _grid(m)
    tot = x + y
    diff = x - y
    out: dict[str, Prob] = {}

    def put(key: str, mask, push_mask=None):
        pw = float(m[mask].sum())
        pp = float(m[push_mask].sum()) if push_mask is not None else 0.0
        out[key] = (pw, pp)

    # ---- 1X2
    put("1X2:1", diff > 0)
    put("1X2:X", diff == 0)
    put("1X2:2", diff < 0)

    # ---- doppia chance
    put("DC:1X", diff >= 0)
    put("DC:X2", diff <= 0)
    put("DC:12", diff != 0)

    # ---- draw no bet (pareggio = rimborso)
    put("DNB:1", diff > 0, diff == 0)
    put("DNB:2", diff < 0, diff == 0)

    # ---- over/under totali, incluse linee intere e quarti
    for line in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.5, 6.5):
        lbl = f"{line:g}"
        if float(line).is_integer():
            put(f"OU:O{lbl}", tot > line, tot == line)
            put(f"OU:U{lbl}", tot < line, tot == line)
        else:
            put(f"OU:O{lbl}", tot > line)
            put(f"OU:U{lbl}", tot < line)

    # ---- both teams to score
    btts = (x > 0) & (y > 0)
    put("BTTS:Y", btts)
    put("BTTS:N", ~btts)

    # ---- combo esito + over/under 2.5 (e 1.5, 3.5)
    for line in (1.5, 2.5, 3.5):
        for res, rmask in (("1", diff > 0), ("X", diff == 0), ("2", diff < 0)):
            put(f"RES_OU:{res}&O{line:g}", rmask & (tot > line))
            put(f"RES_OU:{res}&U{line:g}", rmask & (tot < line))
    # combo doppia chance + goal
    for res, rmask in (("1X", diff >= 0), ("X2", diff <= 0), ("12", diff != 0)):
        put(f"DC_OU:{res}&O2.5", rmask & (tot > 2.5))
        put(f"DC_OU:{res}&U2.5", rmask & (tot < 2.5))

    # ---- combo BTTS + over/under
    for line in (2.5, 3.5):
        put(f"BTTS_OU:Y&O{line:g}", btts & (tot > line))
        put(f"BTTS_OU:Y&U{line:g}", btts & (tot < line))
        put(f"BTTS_OU:N&O{line:g}", (~btts) & (tot > line))
        put(f"BTTS_OU:N&U{line:g}", (~btts) & (tot < line))
    # combo esito + BTTS
    for res, rmask in (("1", diff > 0), ("X", diff == 0), ("2", diff < 0)):
        put(f"RES_BTTS:{res}&Y", rmask & btts)
        put(f"RES_BTTS:{res}&N", rmask & ~btts)

    # ---- multigol
    for lo, hi in [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6),
                   (2, 3), (2, 4), (2, 5), (2, 6), (3, 4), (3, 5), (3, 6), (4, 6)]:
        put(f"MULTIGOL:{lo}-{hi}", (tot >= lo) & (tot <= hi))

    # ---- gol squadra
    for side, g in (("H", x), ("A", y)):
        for line in (0.5, 1.5, 2.5, 3.5):
            put(f"TEAM_OU:{side}:O{line:g}", g > line)
            put(f"TEAM_OU:{side}:U{line:g}", g < line)
        for lo, hi in [(1, 2), (1, 3), (2, 3), (2, 4)]:
            put(f"TEAM_MULTIGOL:{side}:{lo}-{hi}", (g >= lo) & (g <= hi))

    # ---- clean sheet / win to nil
    put("CLEANSHEET:H", y == 0)
    put("CLEANSHEET:A", x == 0)
    put("WINTONIL:H", (diff > 0) & (y == 0))
    put("WINTONIL:A", (diff < 0) & (x == 0))

    # ---- pari / dispari
    put("ODDEVEN:ODD", (tot % 2) == 1)
    put("ODDEVEN:EVEN", (tot % 2) == 0)

    # ---- gol totali esatti
    for g in range(0, 6):
        put(f"EXACT_GOALS:{g}", tot == g)
    put("EXACT_GOALS:6+", tot >= 6)

    # ---- risultato esatto (fino a 5-5)
    n = m.shape[0]
    for i in range(min(6, n)):
        for j in range(min(6, n)):
            out[f"CS:{i}-{j}"] = (float(m[i, j]), 0.0)

    # ---- handicap europeo a 3 vie (linee intere, niente rimborso)
    for h in (-3, -2, -1, 1, 2, 3):
        d = diff + h
        put(f"EH:{h:+d}:1", d > 0)
        put(f"EH:{h:+d}:X", d == 0)
        put(f"EH:{h:+d}:2", d < 0)

    # ---- handicap asiatico (con push e quarti di linea)
    quarter_lines = [-2.75, -2.5, -2.25, -2.0, -1.75, -1.5, -1.25, -1.0,
                     -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0,
                     1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75]
    for h in quarter_lines:
        for side, d in (("H", diff + h), ("A", -diff + (-h))):
            if abs(h * 4) % 2 == 1:  # quarto di linea: meta' stake su due linee
                lo, hi = (h - 0.25, h + 0.25)
                dl = (diff + lo) if side == "H" else (-diff - lo)
                dh = (diff + hi) if side == "H" else (-diff - hi)
                pw = 0.5 * float(m[dl > 0].sum()) + 0.5 * float(m[dh > 0].sum())
                pp = 0.5 * float(m[dl == 0].sum()) + 0.5 * float(m[dh == 0].sum())
                out[f"AH:{side}:{h:+g}"] = (pw, pp)
            else:
                out[f"AH:{side}:{h:+g}"] = (float(m[d > 0].sum()), float(m[d == 0].sum()))

    # ---- margine di vittoria
    for k in (1, 2, 3):
        put(f"MARGIN:H:{k}", diff == k)
        put(f"MARGIN:A:{k}", diff == -k)
    put("MARGIN:H:4+", diff >= 4)
    put("MARGIN:A:4+", diff <= -4)

    return out


HUMAN = {
    "1X2": "Esito finale", "DC": "Doppia chance", "DNB": "Draw No Bet",
    "OU": "Over/Under", "BTTS": "Entrambe segnano", "RES_OU": "Esito + Goal",
    "DC_OU": "Doppia chance + Goal", "BTTS_OU": "Goal/NoGoal + Over/Under",
    "RES_BTTS": "Esito + Goal/NoGoal", "MULTIGOL": "Multigol",
    "TEAM_OU": "Gol squadra", "TEAM_MULTIGOL": "Multigol squadra",
    "CLEANSHEET": "Porta inviolata", "WINTONIL": "Vince senza subire",
    "ODDEVEN": "Pari/Dispari", "EXACT_GOALS": "Numero gol esatto",
    "CS": "Risultato esatto", "EH": "Handicap europeo",
    "AH": "Handicap asiatico", "MARGIN": "Scarto di vittoria",
}


def describe(key: str) -> str:
    fam = key.split(":")[0]
    return f"{HUMAN.get(fam, fam)} — {key.split(':', 1)[1]}"


# ============================================================================
# VALIDAZIONE — backtest walk-forward
# ============================================================================
# Validazione walk-forward.
#
# Senza questo passaggio non sai se il modello e' informativo o se sta solo
# producendo numeri. Il test e' semplice e severo: si stima il modello sulle
# partite fino al giorno T e si predice la giornata T+1, ripetendo in avanti.
#
# Metriche su 1X2:
#   - log-loss  (piu' basso = meglio; il riferimento e' il baseline di lega)
#   - Brier     (idem)
#   - calibrazione per bucket di probabilita': se il modello dice 60%,
#     l'esito deve verificarsi circa il 60% delle volte. Se non succede,
#     ogni "edge" calcolato a valle e' rumore.

def _outcome(hg: int, ag: int) -> int:
    return 0 if hg > ag else (1 if hg == ag else 2)


def walk_forward(rows: list[dict], min_train: int = 150, step: int = 20,
                 xi: float = 0.0019, ridge: float = 0.02) -> dict:
    """rows ordinate per data crescente, con chiavi home/away/hg/ag/days_ago."""
    rows = sorted(rows, key=lambda r: -r["days_ago"])
    if len(rows) < min_train + step:
        return {"ok": False, "reason": "storico insufficiente per il backtest"}

    preds, actuals = [], []
    i = min_train
    while i < len(rows):
        train = rows[:i]
        test = rows[i:i + step]
        base_day = train[-1]["days_ago"]
        fit = fit_dixon_coles(
            [r["home"] for r in train], [r["away"] for r in train],
            [r["hg"] for r in train], [r["ag"] for r in train],
            [r["days_ago"] - base_day for r in train],
            xi=xi, ridge=ridge)
        if fit is None:
            break
        for r in test:
            lm = fit.lambdas(r["home"], r["away"])
            if lm is None:
                continue
            m = score_matrix(lm[0], lm[1], fit.rho)
            p = [float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())]
            s = sum(p)
            preds.append([q / s for q in p])
            actuals.append(_outcome(r["hg"], r["ag"]))
        i += step

    if len(preds) < 30:
        return {"ok": False, "reason": "troppe poche predizioni out-of-sample"}

    P = np.clip(np.array(preds), 1e-6, 1 - 1e-6)
    y = np.array(actuals)
    onehot = np.zeros_like(P)
    onehot[np.arange(len(y)), y] = 1

    logloss = float(-np.mean(np.log(P[np.arange(len(y)), y])))
    brier = float(np.mean(np.sum((P - onehot) ** 2, axis=1)))

    base = onehot.mean(axis=0)
    base_ll = float(-np.mean(np.log(np.clip(base[y], 1e-6, 1))))

    # calibrazione: bucket di 10 punti percentuali
    flat_p = P.ravel()
    flat_y = onehot.ravel()
    buckets = []
    for lo in np.arange(0.0, 1.0, 0.1):
        msk = (flat_p >= lo) & (flat_p < lo + 0.1)
        if msk.sum() >= 20:
            buckets.append({
                "range": f"{lo:.0%}-{lo + 0.1:.0%}",
                "attesa": round(float(flat_p[msk].mean()), 3),
                "osservata": round(float(flat_y[msk].mean()), 3),
                "n": int(msk.sum()),
            })

    return {
        "ok": True,
        "n_pred": len(preds),
        "logloss": round(logloss, 4),
        "logloss_baseline": round(base_ll, 4),
        "miglioramento": round(base_ll - logloss, 4),
        "brier": round(brier, 4),
        "calibrazione": buckets,
    }


# ============================================================================
# QUOTE 1 — The Odds API (percorso gratuito)
# ============================================================================
# The Odds API — palinsesto e quote, gratuitamente e senza forzature.
#
# Perche' questo provider.
#
# Il piano gratuito di the-odds-api.com offre 500 richieste al mese con un
# singolo account regolare. Sembrano poche, ma una richiesta restituisce le
# quote di TUTTE le partite di un campionato in una volta: con 6-8 campionati
# seguiti si spendono ~8 richieste al giorno, cioe' ~240 al mese. Ci sta
# comodamente, senza moltiplicare account.
#
# Combinato con football-data.org per lo storico, il sistema completo gira
# a costo zero e con un account per servizio.
#
# Cosa copre il piano gratuito:
#     h2h      -> 1X2
#     totals   -> Over/Under (linee principali)
#     spreads  -> handicap
#     btts     -> Goal/NoGoal (dove il bookmaker lo pubblica)
#
# Coprire meno mercati non e' un problema quanto sembra: sono esattamente i
# mercati piu' liquidi, quelli su cui il modello ha l'affidabilita' piu' alta
# (vedi FAMILY_TRUST). I mercati esotici hanno margini enormi e sono la sede
# tipica degli "edge" fasulli.

BASE = "https://api.the-odds-api.com/v4"
TIMEOUT = (5, 20)

# sport_key di The Odds API -> codice competizione football-data.org.
# I sport_key possono cambiare: `list_sports()` recupera quelli reali e la
# mappa serve solo a collegarli allo storico.
SPORT_TO_FD = {
    "soccer_italy_serie_a": "SA",
    "soccer_epl": "PL",
    "soccer_england_efl_champ": "ELC",
    "soccer_spain_la_liga": "PD",
    "soccer_germany_bundesliga": "BL1",
    "soccer_france_ligue_one": "FL1",
    "soccer_netherlands_eredivisie": "DED",
    "soccer_portugal_primeira_liga": "PPL",
    "soccer_uefa_champs_league": "CL",
    "soccer_brazil_campeonato": "BSA",
}

PRETTY = {
    "soccer_italy_serie_a": ("Serie A", "Italy"),
    "soccer_epl": ("Premier League", "England"),
    "soccer_england_efl_champ": ("Championship", "England"),
    "soccer_spain_la_liga": ("La Liga", "Spain"),
    "soccer_germany_bundesliga": ("Bundesliga", "Germany"),
    "soccer_france_ligue_one": ("Ligue 1", "France"),
    "soccer_netherlands_eredivisie": ("Eredivisie", "Netherlands"),
    "soccer_portugal_primeira_liga": ("Primeira Liga", "Portugal"),
    "soccer_uefa_champs_league": ("UEFA Champions League", "Europe"),
    "soccer_brazil_campeonato": ("Brasileirao Serie A", "Brazil"),
}

EUROPEAN_DEFAULT = [
    "soccer_italy_serie_a", "soccer_epl", "soccer_spain_la_liga",
    "soccer_germany_bundesliga", "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
]


def fd_season(sport_key: str, now: datetime | None = None) -> int:
    """Anno di riferimento della stagione per football-data.

    I campionati europei attraversano due anni solari e football-data li
    identifica con l'anno di inizio; il Brasileirao segue l'anno solare.
    """
    now = now or datetime.now(timezone.utc)
    if sport_key == "soccer_brazil_campeonato":
        return now.year
    return now.year if now.month >= 7 else now.year - 1


class OddsApi:
    def __init__(self, api_key: str, max_calls: int = 15, regions: str = "eu"):
        self.key = (api_key or "").strip()
        self.max_calls = max_calls
        self.regions = regions
        self.calls = 0
        self.remaining: int | None = None   # quota residua dichiarata dal servizio
        self.log: list[str] = []
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(pool_connections=6, pool_maxsize=6))

    @property
    def available(self) -> bool:
        return bool(self.key) and self.calls < self.max_calls

    def _get(self, path: str, params: dict):
        if not self.available:
            self.log.append("OddsAPI: budget locale esaurito")
            return None
        self.calls += 1
        params = {**params, "apiKey": self.key}
        try:
            r = self.session.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            self.log.append(f"OddsAPI {path}: rete KO ({type(e).__name__})")
            return None

        rem = r.headers.get("x-requests-remaining")
        if rem is not None:
            try:
                self.remaining = int(float(rem))
            except ValueError:
                pass

        if r.status_code == 401:
            self.log.append("OddsAPI: chiave non valida")
            return None
        if r.status_code == 429:
            self.log.append("OddsAPI: quota mensile esaurita")
            return None
        if r.status_code == 422:
            self.log.append(f"OddsAPI {path}: parametri rifiutati "
                            f"(mercato o regione non disponibile sul piano)")
            return None
        if r.status_code != 200:
            self.log.append(f"OddsAPI {path}: HTTP {r.status_code}")
            return None
        try:
            return r.json()
        except ValueError:
            self.log.append(f"OddsAPI {path}: risposta non-JSON")
            return None

    def list_sports(self) -> list[dict]:
        """Campionati realmente attivi ora. Evita di sprecare richieste su
        competizioni fuori stagione, che restituirebbero liste vuote."""
        d = self._get("/sports", {})
        return [s for s in (d or []) if str(s.get("key", "")).startswith("soccer_")]

    def league_odds(self, sport_key: str,
                    markets: str = "h2h,totals,spreads,btts",
                    commence_from: str | None = None,
                    commence_to: str | None = None):
        """Quote di tutte le partite imminenti di un campionato: UNA richiesta."""
        params = {
            "regions": self.regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        # Filtro lato server sulla finestra temporale: senza, il provider
        # restituisce tutti gli eventi imminenti (anche a una settimana),
        # e la data scelta in sidebar verrebbe semplicemente ignorata.
        if commence_from:
            params["commenceTimeFrom"] = commence_from
        if commence_to:
            params["commenceTimeTo"] = commence_to
        d = self._get(f"/sports/{sport_key}/odds", params)
        if d is None and "btts" in markets:
            # alcuni piani/regioni non espongono btts: riprova senza
            self.log.append("OddsAPI: riprovo senza il mercato btts")
            d = self._get(f"/sports/{sport_key}/odds",
                          {**params, "markets": "h2h,totals,spreads"})
        return d or []


# --------------------------------------------------------------- parsing

def parse_event(event: dict) -> dict[str, dict]:
    """Da un evento The Odds API alle chiavi canoniche del modello.

    Aggrega tutti i bookmaker: mediana per stimare il prezzo di mercato,
    quota migliore per calcolare l'EV effettivamente ottenibile.
    """
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    acc: dict[str, list[tuple[float, str]]] = {}

    for bm in event.get("bookmakers", []) or []:
        title = bm.get("title", bm.get("key", "?"))
        for mkt in bm.get("markets", []) or []:
            mk = mkt.get("key")
            for oc in mkt.get("outcomes", []) or []:
                name = str(oc.get("name", ""))
                try:
                    price = float(oc.get("price"))
                except (TypeError, ValueError):
                    continue
                if price <= 1.01 or price > 1000:
                    continue
                point = oc.get("point")
                key = None

                if mk == "h2h":
                    if name == home:
                        key = "1X2:1"
                    elif name == away:
                        key = "1X2:2"
                    elif name.lower() == "draw":
                        key = "1X2:X"

                elif mk == "totals" and point is not None:
                    side = name.lower()
                    if side.startswith("over"):
                        key = f"OU:O{float(point):g}"
                    elif side.startswith("under"):
                        key = f"OU:U{float(point):g}"

                elif mk == "spreads" and point is not None:
                    # The Odds API esprime il punto dal lato della squadra
                    if name == home:
                        key = f"AH:H:{float(point):+g}"
                    elif name == away:
                        key = f"AH:A:{float(point):+g}"

                elif mk == "btts":
                    if name.lower().startswith("yes"):
                        key = "BTTS:Y"
                    elif name.lower().startswith("no"):
                        key = "BTTS:N"

                if key:
                    acc.setdefault(key, []).append((price, title))

    out: dict[str, dict] = {}
    for key, lst in acc.items():
        prices = sorted(p for p, _ in lst)
        mid = len(prices) // 2
        median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2
        best, book = max(lst, key=lambda t: t[0])
        out[key] = {"best": best, "median": median,
                    "books": len(lst), "bookmaker": book}
    return out


# ============================================================================
# QUOTE 2 — API-Sports (percorso alternativo)
# ============================================================================
# Client API-Sports con budget di chiamate, cache su disco e rotazione chiavi.
#
# Il collo di bottiglia reale non e' il codice: e' la quota giornaliera.
# Lo storico serve a stimare il modello e cambia lentamente -> cache 7 giorni.
# Le quote pre-match cambiano di continuo -> cache 15 minuti.
# Con questa separazione una giornata tipo costa 15-25 chiamate, non 400.

BASE = "https://v3.football.api-sports.io"
CACHE_DIR = os.environ.get("BETPRO_CACHE", os.path.expanduser("~/.betpro_cache"))
TIMEOUT = (5, 20)


def _cache_path(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    return os.path.join(CACHE_DIR, f"{h}.json")


def cache_get(key: str, ttl: int):
    p = _cache_path(key)
    try:
        if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < ttl:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def cache_put(key: str, value) -> None:
    try:
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump(value, f)
    except Exception:
        pass


class ApiSports:
    def __init__(self, keys: list[str], max_calls: int = 60):
        self.keys = [k for k in keys if k]
        self.ki = 0
        self.max_calls = max_calls
        self.calls = 0
        self.log: list[str] = []
        self.key_errors: list[str] = []
        self.all_keys_failed = False
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=8))

    @property
    def exhausted(self) -> bool:
        return self.calls >= self.max_calls or self.ki >= len(self.keys)

    def _get(self, path: str, params: dict) -> dict | None:
        while self.ki < len(self.keys):
            if self.calls >= self.max_calls:
                self.log.append("budget chiamate esaurito")
                return None
            self.calls += 1
            key = self.keys[self.ki]
            try:
                r = self.session.get(f"{BASE}{path}",
                                     headers={"x-apisports-key": key},
                                     params=params, timeout=TIMEOUT)
            except requests.RequestException as e:
                self.log.append(f"{path}: rete KO ({type(e).__name__}) -> prossima chiave")
                self.ki += 1
                continue

            if r.status_code in (429, 499):
                self.log.append(f"{path}: quota chiave {self.ki + 1} esaurita")
                self.ki += 1
                continue
            if r.status_code in (401, 403):
                self.log.append(f"{path}: chiave {self.ki + 1} non valida")
                self.ki += 1
                continue
            if r.status_code != 200:
                self.log.append(f"{path}: HTTP {r.status_code}")
                return None

            try:
                data = r.json()
            except ValueError:
                self.log.append(f"{path}: risposta non-JSON")
                return None

            errs = data.get("errors")
            if errs:
                msg = str(list(errs.values())[0] if isinstance(errs, dict) else errs[0])
                low = msg.lower()
                # Errori legati alla CHIAVE/ACCOUNT: la chiamata non e' recuperabile
                # con questa chiave ma puo' funzionare con la successiva.
                # "suspended" era il caso mancante: senza, il motore si fermava
                # alla prima chiave senza provare le altre.
                key_level = ("limit", "quota", "suspend", "disabled", "not subscribed",
                             "subscription", "invalid api key", "missing api key",
                             "token", "expired")
                if any(t in low for t in key_level):
                    self.log.append(f"{path}: chiave {self.ki + 1} inutilizzabile "
                                    f"({msg}) -> passo alla successiva")
                    self.ki += 1
                    self.key_errors.append(msg)
                    continue
                self.log.append(f"{path}: {msg}")
                return None
            return data

        # tutte le chiavi consumate senza successo
        self.all_keys_failed = True
        return None

    # ---------------------------------------------------------- endpoints

    def fixtures_of_day(self, day: str, ttl: int = 900) -> list[dict]:
        ck = f"fixtures:{day}"
        c = cache_get(ck, ttl)
        if c is not None:
            return c
        d = self._get("/fixtures", {"date": day, "timezone": "Europe/Rome"})
        out = (d or {}).get("response", []) or []
        if out:
            cache_put(ck, out)
        return out

    def odds_of_day(self, day: str, max_pages: int = 12, ttl: int = 900) -> dict[int, dict]:
        """Tutti i mercati di tutti i bookmaker per la giornata, indicizzati per fixture."""
        ck = f"odds:{day}"
        c = cache_get(ck, ttl)
        if c is not None:
            return {int(k): v for k, v in c.items()}

        out: dict[int, dict] = {}
        page = 1
        while page <= max_pages:
            d = self._get("/odds", {"date": day, "page": page})
            if not d:
                break
            for entry in d.get("response", []) or []:
                fid = ((entry.get("fixture") or {}).get("id"))
                if fid is not None:
                    out[int(fid)] = entry
            total = int(((d.get("paging") or {}).get("total")) or 1)
            if page >= total:
                break
            page += 1
        if out:
            cache_put(ck, {str(k): v for k, v in out.items()})
        return out

    def league_history(self, league_id: int, season: int,
                       ttl: int = 7 * 86400) -> list[dict]:
        """Risultati finali della stagione: la base per la stima Dixon-Coles."""
        ck = f"hist:{league_id}:{season}"
        c = cache_get(ck, ttl)
        if c is not None:
            return c

        rows: list[dict] = []
        page = 1
        while page <= 6:
            d = self._get("/fixtures", {"league": league_id, "season": season,
                                        "status": "FT", "page": page})
            if not d:
                break
            for item in d.get("response", []) or []:
                g = item.get("goals") or {}
                if g.get("home") is None or g.get("away") is None:
                    continue
                teams = item.get("teams") or {}
                rows.append({
                    "home": (teams.get("home") or {}).get("name"),
                    "away": (teams.get("away") or {}).get("name"),
                    "hg": int(g["home"]),
                    "ag": int(g["away"]),
                    "date": ((item.get("fixture") or {}).get("date")),
                })
            total = int(((d.get("paging") or {}).get("total")) or 1)
            if page >= total:
                break
            page += 1

        if rows:
            cache_put(ck, rows)
        return rows

    def injuries_of_day(self, day: str, ttl: int = 3600) -> dict[int, dict[str, int]]:
        ck = f"inj:{day}"
        c = cache_get(ck, ttl)
        if c is not None:
            return {int(k): v for k, v in c.items()}
        d = self._get("/injuries", {"date": day})
        out: dict[int, dict[str, int]] = {}
        for entry in (d or {}).get("response", []) or []:
            fid = ((entry.get("fixture") or {}).get("id"))
            team = ((entry.get("team") or {}).get("name") or "")
            if fid is None:
                continue
            out.setdefault(int(fid), {}).setdefault(team, 0)
            out[int(fid)][team] += 1
        if out:
            cache_put(ck, {str(k): v for k, v in out.items()})
        return out


def days_ago(iso: str, ref: datetime | None = None) -> float:
    ref = ref or datetime.now(timezone.utc)
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return 365.0
    return max(0.0, (ref - d).total_seconds() / 86400.0)


# ============================================================================
# STORICO — football-data.org (gratuito)
# ============================================================================
# football-data.org come fonte dello STORICO.
#
# Il ragionamento architetturale.
#
# Il motore ha bisogno di due cose molto diverse:
#
#   A) storico dei risultati  -> serve a stimare il modello. E' voluminoso
#      (centinaia di partite per lega) ma cambia lentamente.
#   B) quote pre-match        -> servono al confronto. Sono poche per match
#      ma cambiano di continuo e SOLO API-Sports le fornisce.
#
# Prendere anche (A) da API-Sports significa bruciare la quota giornaliera
# sulla parte che potrebbe essere gratuita. football-data.org copre (A) sulle
# principali competizioni europee senza costi, con 10 richieste al minuto.
#
# Risultato: API-Sports viene usata quasi esclusivamente per le quote, e la
# quota giornaliera rende molte più giornate di palinsesto.
#
# Limite del piano gratuito football-data: circa 12 competizioni. Per tutto
# il resto si ricade su API-Sports come prima.

BASE = "https://api.football-data.org/v4"
TIMEOUT = (5, 20)

# Competizioni del piano gratuito football-data.org.
# La chiave e' il nome normalizzato che restituisce API-Sports.
COMPETITION_CODES = {
    "premier league": "PL",
    "championship": "ELC",
    "la liga": "PD",
    "primera division": "PD",
    "laliga": "PD",
    "serie a": "SA",
    "bundesliga": "BL1",
    "ligue 1": "FL1",
    "eredivisie": "DED",
    "primeira liga": "PPL",
    "liga portugal": "PPL",
    "uefa champions league": "CL",
    "champions league": "CL",
    "campeonato brasileiro serie a": "BSA",
    "serie a betano": "BSA",
}


def code_for(league_name: str, country: str = "") -> str | None:
    """Mappa il nome di lega API-Sports sul codice football-data."""
    n = (league_name or "").strip().lower()
    c = (country or "").strip().lower()
    # disambigua le omonimie: "Serie A" esiste in Italia e in Brasile
    if n == "serie a" and c in ("brazil", "brasile"):
        return "BSA"
    if n == "premier league" and c not in ("england", "inghilterra", ""):
        return None
    return COMPETITION_CODES.get(n)


class FootballData:
    """Client con rotazione chiavi e rispetto del limite di 10 richieste/minuto."""

    def __init__(self, keys: list[str], max_calls: int = 40):
        self.keys = [k for k in keys if k]
        self.ki = 0
        self.max_calls = max_calls
        self.calls = 0
        self.log: list[str] = []
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(pool_connections=6, pool_maxsize=6))

    @property
    def available(self) -> bool:
        return bool(self.keys) and self.ki < len(self.keys) and self.calls < self.max_calls

    def _get(self, path: str, params: dict) -> dict | None:
        while self.available:
            self.calls += 1
            try:
                r = self.session.get(f"{BASE}{path}",
                                     headers={"X-Auth-Token": self.keys[self.ki]},
                                     params=params, timeout=TIMEOUT)
            except requests.RequestException as e:
                self.log.append(f"FD {path}: rete KO ({type(e).__name__})")
                self.ki += 1
                continue

            if r.status_code == 429:
                # limite al minuto: con piu' chiavi conviene ruotare invece
                # di restare fermi 60 secondi ad aspettare
                self.log.append(f"FD {path}: chiave {self.ki + 1} a limite/minuto -> ruoto")
                self.ki += 1
                continue
            if r.status_code in (401, 403):
                self.log.append(f"FD {path}: chiave {self.ki + 1} non valida o "
                                f"competizione fuori dal piano gratuito")
                self.ki += 1
                continue
            if r.status_code != 200:
                self.log.append(f"FD {path}: HTTP {r.status_code}")
                return None
            try:
                return r.json()
            except ValueError:
                self.log.append(f"FD {path}: risposta non-JSON")
                return None
        return None

    def season_results(self, code: str, season: int) -> list[dict]:
        """Risultati finali di una stagione, nel formato atteso dal modello."""
        d = self._get(f"/competitions/{code}/matches",
                      {"season": season, "status": "FINISHED"})
        rows: list[dict] = []
        for m in (d or {}).get("matches", []) or []:
            ft = ((m.get("score") or {}).get("fullTime") or {})
            if ft.get("home") is None or ft.get("away") is None:
                continue
            home = (m.get("homeTeam") or {}).get("shortName") or \
                   (m.get("homeTeam") or {}).get("name")
            away = (m.get("awayTeam") or {}).get("shortName") or \
                   (m.get("awayTeam") or {}).get("name")
            if not home or not away:
                continue
            rows.append({"home": home, "away": away,
                         "hg": int(ft["home"]), "ag": int(ft["away"]),
                         "date": m.get("utcDate")})
        return rows


def align_names(fd_rows: list[dict], api_teams: set[str]) -> tuple[list[dict], int]:
    """Allinea i nomi squadra di football-data a quelli di API-Sports.

    I due provider scrivono le squadre in modo diverso ("Inter" vs
    "Internazionale", "Man City" vs "Manchester City"). Senza allineamento
    il modello viene stimato su nomi che poi non corrispondono a nessuna
    partita del palinsesto, e l'affidabilita' risulta zero ovunque.

    Strategia conservativa: match esatto, poi contenimento, poi token comuni.
    Le squadre non risolte restano col nome originale e verranno semplicemente
    saltate a valle: meglio perdere un match che accoppiarne due sbagliate.
    """
    if not api_teams:
        return fd_rows, 0

    lower = {t.lower(): t for t in api_teams}
    mapping: dict[str, str] = {}
    fd_teams = {r["home"] for r in fd_rows} | {r["away"] for r in fd_rows}

    for name in fd_teams:
        n = name.lower()
        if n in lower:
            mapping[name] = lower[n]
            continue
        cand = [t for t in api_teams
                if n in t.lower() or t.lower() in n]
        if len(cand) == 1:
            mapping[name] = cand[0]
            continue
        toks = {w for w in n.replace("-", " ").split() if len(w) > 3}
        scored = []
        for t in api_teams:
            tt = {w for w in t.lower().replace("-", " ").split() if len(w) > 3}
            if toks and tt:
                scored.append((len(toks & tt) / len(toks | tt), t))
        scored.sort(reverse=True)
        if scored and scored[0][0] >= 0.5:
            mapping[name] = scored[0][1]

    out = [{**r,
            "home": mapping.get(r["home"], r["home"]),
            "away": mapping.get(r["away"], r["away"])}
           for r in fd_rows]
    return out, len(mapping)


# ============================================================================
# PARSER — mercati API-Sports verso chiavi canoniche
# ============================================================================
# Mappa i mercati pubblicati da API-Sports sulle chiavi canoniche del modello.
#
# I nomi dei mercati variano tra bookmaker e cambiano nel tempo: il parsing
# avviene per NOME NORMALIZZATO, non per bet_id, ed e' tollerante ai fallimenti.
# Ogni mercato non riconosciuto finisce in `unmatched` e resta visibile
# nella diagnostica, cosi' la copertura si estende in modo incrementale
# invece di fallire in silenzio.

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+.:/\- ]", "", str(s).strip().lower())


_UNSIGNED = re.compile(r"\d+(?:\.\d+)?")


def _pair(v: str) -> tuple[int, int] | None:
    """Estrae una coppia di interi non firmati: '2-3', '2:1', '2 3'."""
    nums = _UNSIGNED.findall(v)
    if len(nums) == 2:
        return int(float(nums[0])), int(float(nums[1]))
    return None


def _num(s: str) -> float | None:
    mm = _NUM.search(str(s))
    return float(mm.group()) if mm else None


def _side(v: str) -> str | None:
    v = _norm(v)
    if v.startswith(("home", "1 ")) or v in ("home", "1"):
        return "1"
    if v.startswith("draw") or v in ("draw", "x"):
        return "X"
    if v.startswith(("away", "2 ")) or v in ("away", "2"):
        return "2"
    return None


def parse_outcome(bet_name: str, value: str) -> str | None:
    """Ritorna la chiave canonica o None se il mercato non e' modellato."""
    b = _norm(bet_name)
    v = _norm(value)
    n = _num(v)

    # esito finale
    if b in ("match winner", "full time result", "1x2", "3way result", "winner"):
        s = _side(v)
        return f"1X2:{s}" if s else None

    if "double chance" in b:
        key = v.replace(" ", "").replace("home", "1").replace("away", "2").replace("draw", "x")
        key = key.replace("/", "").upper()
        return {"1X": "DC:1X", "X1": "DC:1X", "X2": "DC:X2", "2X": "DC:X2",
                "12": "DC:12", "21": "DC:12"}.get(key)

    if "draw no bet" in b:
        s = _side(v)
        return f"DNB:{s}" if s in ("1", "2") else None

    # over / under totali
    if b in ("goals over/under", "over/under", "total goals", "goals over under"):
        if n is None:
            return None
        if v.startswith("o"):
            return f"OU:O{n:g}"
        if v.startswith("u"):
            return f"OU:U{n:g}"
        return None

    # both teams to score
    if "both teams" in b and "half" not in b and "score" in b:
        if v.startswith("y"):
            return "BTTS:Y"
        if v.startswith("n"):
            return "BTTS:N"
        return None

    # esito + over/under  (es. "Home/Over 2.5")
    if b in ("result/total goals", "results/total goals", "result total goals"):
        parts = v.split("/")
        if len(parts) != 2 or n is None:
            return None
        s = _side(parts[0])
        ou = "O" if "over" in parts[1] else ("U" if "under" in parts[1] else None)
        return f"RES_OU:{s}&{ou}{n:g}" if s and ou else None

    # esito + goal/nogoal
    if b in ("results/both teams score", "result/both teams score"):
        parts = v.split("/")
        if len(parts) != 2:
            return None
        s = _side(parts[0])
        yn = "Y" if "yes" in parts[1] else ("N" if "no" in parts[1] else None)
        return f"RES_BTTS:{s}&{yn}" if s and yn else None

    # goal/nogoal + over/under
    if "both teams score" in b and ("over" in b or "total" in b) and n is not None:
        yn = "Y" if v.startswith("y") else ("N" if v.startswith("n") else None)
        ou = "O" if "over" in v else ("U" if "under" in v else None)
        return f"BTTS_OU:{yn}&{ou}{n:g}" if yn and ou else None

    # multigol
    if "multi goals" in b or "multigoal" in b or "goal range" in b:
        pr = _pair(v)
        return f"MULTIGOL:{pr[0]}-{pr[1]}" if pr else None

    # gol squadra
    if b in ("total - home", "home total", "total home"):
        if n is None:
            return None
        return f"TEAM_OU:H:{'O' if v.startswith('o') else 'U'}{n:g}"
    if b in ("total - away", "away total", "total away"):
        if n is None:
            return None
        return f"TEAM_OU:A:{'O' if v.startswith('o') else 'U'}{n:g}"

    # clean sheet / win to nil
    if "clean sheet" in b:
        side = "H" if "home" in b or "home" in v else "A"
        return f"CLEANSHEET:{side}" if v.startswith("y") or "yes" in v else None
    if "win to nil" in b:
        side = "H" if "home" in b or "home" in v else "A"
        return f"WINTONIL:{side}" if v.startswith("y") or "yes" in v else None

    # pari / dispari
    if b in ("odd/even", "goals odd/even", "total goals odd/even"):
        if v.startswith("o"):
            return "ODDEVEN:ODD"
        if v.startswith("e"):
            return "ODDEVEN:EVEN"
        return None

    # risultato esatto
    if b in ("exact score", "correct score"):
        pr = _pair(v)
        return f"CS:{pr[0]}-{pr[1]}" if pr else None

    # numero gol esatto
    if "exact goals number" in b or b == "total goals exact":
        if n is not None:
            return f"EXACT_GOALS:{int(n)}"
        return None

    # handicap asiatico
    if "asian handicap" in b and "half" not in b:
        s = _side(v)
        h = _num(v)
        if s in ("1", "2") and h is not None:
            return f"AH:{'H' if s == '1' else 'A'}:{h:+g}"
        return None

    # handicap europeo (3 vie)
    if ("handicap result" in b or b == "handicap") and n is not None:
        s = _side(v)
        return f"EH:{int(n):+d}:{s}" if s else None

    return None


def parse_fixture_odds(entry: dict, min_books: int = 2) -> dict[str, dict]:
    """Aggrega tutti i bookmaker di un fixture.

    Ritorna {chiave_canonica: {"best": quota_migliore, "median": mediana,
                               "books": n, "bookmaker": nome}}
    La MEDIANA e' quella usata per stimare la probabilita' di mercato
    (piu' robusta di un singolo bookmaker); la MIGLIORE e' quella su cui
    si calcola l'EV, perche' e' la quota che effettivamente giocheresti.
    """
    acc: dict[str, list[tuple[float, str]]] = {}
    unmatched: set[str] = set()

    for bm in entry.get("bookmakers", []) or []:
        bname = bm.get("name", "?")
        for bet in bm.get("bets", []) or []:
            bet_name = bet.get("name", "")
            for val in bet.get("values", []) or []:
                key = parse_outcome(bet_name, val.get("value", ""))
                if key is None:
                    unmatched.add(bet_name)
                    continue
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue
                if odd <= 1.01 or odd > 1000:
                    continue
                acc.setdefault(key, []).append((odd, bname))

    out: dict[str, dict] = {}
    for key, lst in acc.items():
        if len(lst) < min_books:
            continue
        odds = sorted(o for o, _ in lst)
        mid = len(odds) // 2
        median = odds[mid] if len(odds) % 2 else (odds[mid - 1] + odds[mid]) / 2
        best_odd, best_book = max(lst, key=lambda t: t[0])
        out[key] = {"best": best_odd, "median": median,
                    "books": len(lst), "bookmaker": best_book}
    out["__unmatched__"] = {"names": sorted(unmatched)}  # diagnostica
    return out


# ============================================================================
# VALORE — devig, shrinkage, EV, Kelly, strategie
# ============================================================================
# Confronto modello vs mercato: dove il modello vede una discrepanza sfruttabile.
#
# Pipeline per ogni esito:
#   quote bookmaker -> rimozione margine -> prob. equa di mercato
#   prob. modello   -> shrinkage verso il mercato in base all'affidabilita'
#   edge = p_usata - p_mercato ; EV = p_usata * quota_migliore + p_push - 1
#
# Lo shrinkage e' la parte piu' importante e la piu' controintuitiva.
# Un modello stimato su 200 partite produce regolarmente "edge" del 15%
# che sono puro errore di stima. Fidarsi del modello in proporzione a
# quanto e' realmente informato e' cio' che separa uno strumento da un
# generatore di illusioni.

# Affidabilita' strutturale per famiglia di mercato.
# I mercati a bassa liquidita' mostrano edge apparenti enormi perche'
# il bookmaker ci mette un margine altissimo, non perche' ci sia valore.
FAMILY_TRUST = {
    "1X2": 1.00, "DC": 1.00, "DNB": 1.00, "OU": 1.00, "BTTS": 0.95,
    "AH": 0.95, "EH": 0.85, "RES_OU": 0.85, "DC_OU": 0.85, "RES_BTTS": 0.85,
    "BTTS_OU": 0.80, "MULTIGOL": 0.80, "TEAM_OU": 0.80, "TEAM_MULTIGOL": 0.70,
    "CLEANSHEET": 0.75, "WINTONIL": 0.70, "ODDEVEN": 0.60,
    "EXACT_GOALS": 0.55, "MARGIN": 0.50, "CS": 0.45,
}


def family(key: str) -> str:
    return key.split(":")[0]


# Famiglie escluse dalle strategie per impostazione predefinita.
# Gli handicap sono fuori per scelta dell'utente; risultato esatto,
# scarto e numero gol esatto perche' hanno margini enormi e la loro
# stima e' la piu' fragile dell'insieme.
DEFAULT_EXCLUDED = ("AH", "EH", "CS", "MARGIN", "EXACT_GOALS")


def group_of(key: str) -> tuple[str, float] | None:
    """(id gruppo mutuamente esclusivo, somma attesa delle probabilita')."""
    p = key.split(":")
    f = p[0]
    if f == "1X2":
        return "1X2", 1.0
    if f == "DC":
        return "DC", 2.0                      # 1X + X2 + 12 = 2
    if f == "OU":
        return f"OU:{p[1][1:]}", 1.0
    if f == "BTTS":
        return "BTTS", 1.0
    if f == "ODDEVEN":
        return "ODDEVEN", 1.0
    if f == "DNB":
        return "DNB", 1.0                     # condizionato al no-push
    if f == "TEAM_OU":
        return f"TEAM_OU:{p[1]}:{p[2][1:]}", 1.0
    if f == "EH":
        return f"EH:{p[1]}", 1.0
    if f == "AH":
        # la coppia e' (casa a linea h, ospite a linea -h): l'id del gruppo
        # e' sempre la linea vista dalla parte di casa, altrimenti quattro
        # esiti distinti finiscono nello stesso gruppo e il devig sballa.
        line = float(p[2])
        h_line = line if p[1] == "H" else -line
        return f"AH:{h_line:+g}", 1.0
    return None                               # non raggruppabile -> margine di riferimento


@dataclass
class Pick:
    fixture_id: int | None
    kickoff: str
    home: str
    away: str
    league: str
    country: str
    market: str
    p_model: float
    p_push: float
    p_market: float
    p_used: float
    edge: float
    odd: float
    bookmaker: str
    books: int
    ev: float
    kelly: float
    reliability: float
    lam_home: float
    lam_away: float
    reason: str = ""

    def dict(self):
        return asdict(self)


def estimate_margin(odds_map: dict[str, dict]) -> float:
    """Overround medio del match, stimato sui gruppi identificabili."""
    groups: dict[str, tuple[float, float]] = {}
    for key, o in odds_map.items():
        if key.startswith("__"):
            continue
        g = group_of(key)
        if not g:
            continue
        gid, s = g
        acc, exp = groups.get(gid, (0.0, s))
        groups[gid] = (acc + 1.0 / o["median"], exp)
    ratios = [acc / exp for acc, exp in groups.values() if exp > 0 and 0.9 < acc / exp < 1.6]
    return sum(ratios) / len(ratios) if ratios else 1.08


def market_fair_probs(odds_map: dict[str, dict]) -> dict[str, float]:
    """Probabilita' di mercato ripulite dal margine (metodo proporzionale)."""
    ref_margin = estimate_margin(odds_map)
    sums: dict[str, tuple[float, float]] = {}
    for key, o in odds_map.items():
        if key.startswith("__"):
            continue
        g = group_of(key)
        if not g:
            continue
        gid, s = g
        acc, exp = sums.get(gid, (0.0, s))
        sums[gid] = (acc + 1.0 / o["median"], exp)

    fair: dict[str, float] = {}
    for key, o in odds_map.items():
        if key.startswith("__"):
            continue
        raw = 1.0 / o["median"]
        g = group_of(key)
        ratio = None
        if g and g[0] in sums:
            acc, exp = sums[g[0]]
            if exp > 0 and acc > 0:
                ratio = acc / exp
        # Un gruppo INCOMPLETO (il book non pubblica tutti gli esiti, o alcuni
        # sono stati scartati perche' sotto quota minima) produce un rapporto
        # lontano da 1 e, normalizzando, sparerebbe la probabilita' di mercato
        # verso 1.0 generando EV fantasma a tre cifre. In quel caso si ripiega
        # sul margine di riferimento del match.
        divisor = ratio if (ratio is not None and 0.95 <= ratio <= 1.60) else ref_margin
        fair[key] = min(max(raw / divisor, 1e-6), 0.999999)
    return fair


def evaluate_fixture(
    match: dict,
    model_probs: dict[str, tuple[float, float]],
    odds_map: dict[str, dict],
    reliability: float,
    lam: tuple[float, float],
    min_books: int = 2,
) -> list[Pick]:
    if reliability <= 0 or not odds_map:
        return []
    fair = market_fair_probs(odds_map)
    picks: list[Pick] = []

    for key, o in odds_map.items():
        if key.startswith("__") or key not in model_probs:
            continue
        if o["books"] < min_books:
            continue

        pm_win, pm_push = model_probs[key]
        p_mkt = fair[key]
        trust = reliability * FAMILY_TRUST.get(family(key), 0.6)

        # per i mercati con rimborso il confronto e' condizionale al no-push
        if pm_push > 1e-9:
            # Sui mercati con rimborso il devig di gruppo produce gia' una
            # probabilita' CONDIZIONATA al no-push: il confronto va fatto
            # nelle stesse unita', altrimenti l'EV esplode artificialmente.
            denom = max(1e-9, 1.0 - pm_push)
            pm_cond = min(1.0, pm_win / denom)
            p_used_cond = trust * pm_cond + (1 - trust) * min(1.0, p_mkt)
            p_used = p_used_cond * denom
            edge = p_used_cond - min(1.0, p_mkt)
        else:
            p_used = trust * pm_win + (1 - trust) * p_mkt
            edge = p_used - p_mkt

        p_used = min(max(p_used, 0.0), 1.0 - pm_push)
        best = o["best"]
        ev = p_used * best + pm_push - 1.0
        kelly = ev / (best - 1.0) if best > 1.0 else 0.0

        picks.append(Pick(
            fixture_id=match.get("fixture_id"),
            kickoff=match.get("kickoff", ""),
            home=match.get("home", ""),
            away=match.get("away", ""),
            league=match.get("league", ""),
            country=match.get("country", ""),
            market=key,
            p_model=round(pm_win, 5),
            p_push=round(pm_push, 5),
            p_market=round(p_mkt, 5),
            p_used=round(p_used, 5),
            edge=round(edge, 5),
            odd=best,
            bookmaker=o["bookmaker"],
            books=o["books"],
            ev=round(ev, 5),
            kelly=round(max(0.0, min(kelly, 0.25)), 5),
            reliability=round(trust, 3),
            lam_home=round(lam[0], 3),
            lam_away=round(lam[1], 3),
        ))
    return picks


# --------------------------------------------------------------- strategie

EURO_KEYWORDS = (
    "uefa champions league", "champions league", "uefa europa league",
    "europa league", "uefa europa conference league", "conference league",
    "uefa super cup", "euro qualification", "nations league",
)
TOP5 = ("premier league", "la liga", "primera division", "serie a",
        "bundesliga", "ligue 1")


def is_european(p: Pick) -> bool:
    lg = p.league.lower()
    return any(k in lg for k in EURO_KEYWORDS) or any(k in lg for k in TOP5)


def build_strategy(
    picks: list[Pick],
    name: str,
    only_european: bool = False,
    min_ev: float = 0.03,
    min_prob: float = 0.20,
    min_odd: float = 1.20,
    max_odd: float = 15.0,
    min_reliability: float = 0.45,
    max_picks: int = 6,
    one_per_fixture: bool = True,
    excluded_families: tuple[str, ...] = DEFAULT_EXCLUDED,
) -> dict:
    picks = [p for p in picks if family(p.market) not in excluded_families]
    pool = [p for p in picks
            if p.ev >= min_ev
            and p.p_used >= min_prob
            and min_odd <= p.odd <= max_odd
            and p.reliability >= min_reliability]
    if only_european:
        pool = [p for p in pool if is_european(p)]

    pool.sort(key=lambda p: (-p.ev, -p.reliability, -p.books))

    chosen: list[Pick] = []
    seen: set = set()
    for p in pool:
        if one_per_fixture and p.fixture_id in seen:
            continue
        chosen.append(p)
        seen.add(p.fixture_id)
        if len(chosen) >= max_picks:
            break

    combo_p = 1.0
    combo_o = 1.0
    for p in chosen:
        combo_p *= p.p_used
        combo_o *= p.odd

    return {
        "name": name,
        "picks": [p.dict() for p in chosen],
        "combo_prob": round(combo_p, 5) if chosen else 0.0,
        "combo_odd": round(combo_o, 2) if chosen else 0.0,
        "combo_ev": round(combo_p * combo_o - 1.0, 4) if chosen else 0.0,
        "pool_size": len(pool),
    }


# ============================================================================
# COMBO — soglie di quota senza prezzo di mercato
# ============================================================================
# Combo: il problema e la soluzione.
#
# IL PROBLEMA
# I mercati combinati (Esito+Over, Goal+Over, Esito+Goal/NoGoal, Multigol)
# NON sono pubblicati dai provider di quote gratuiti. The Odds API sul piano
# free espone h2h, totals, spreads e btts: le combo non ci sono.
#
# Senza la quota del bookmaker non esiste un edge da misurare. Calcolare un
# "EV" su una combo di cui non conosciamo il prezzo significherebbe inventarlo.
#
# LA SOLUZIONE
# Ribaltare la direzione del confronto. Il modello sa calcolare esattamente
# la probabilita' di ogni combo dalla matrice dei punteggi. Da li' si ricava
# la QUOTA MINIMA sotto la quale la giocata e' matematicamente perdente.
#
# L'app produce quella soglia; tu apri l'app del tuo bookmaker e confronti.
# Se il prezzo esposto e' sopra la soglia, c'e' valore; se e' sotto, no.
# Il lavoro di stima resta al modello, la lettura del prezzo la fai tu.
#
# Non e' un ripiego: e' esattamente lo stesso calcolo che il motore fa sui
# mercati con quota, con l'unico passaggio manuale della lettura del prezzo.
#
# LE TRE SOGLIE
#   quota equa       1 / p            break-even teorico, margine zero
#   quota prudente   1 / p_scontata   include lo sconto per incertezza di stima
#   quota richiesta  prudente x (1+m) include il margine di sicurezza richiesto
#
# Usa sempre la terza. La prima e' solo un riferimento.

# Famiglie combinate: quelle che interessano quando non si vogliono
# gli handicap e si cerca il valore nei mercati "da schedina".
COMBO_FAMILIES = (
    "RES_OU",       # Esito + Over/Under
    "DC_OU",        # Doppia chance + Over/Under
    "RES_BTTS",     # Esito + Goal/NoGoal
    "BTTS_OU",      # Goal/NoGoal + Over/Under
    "MULTIGOL",     # Multigol totale
    "TEAM_MULTIGOL",
    "WINTONIL",
    "CLEANSHEET",
)


def confidence_discount(reliability: float, fam: str) -> float:
    """Sconto applicato alla probabilita' del modello.

    Senza un prezzo di mercato verso cui fare shrinkage, l'unica difesa
    contro l'errore di stima e' abbassare deliberatamente la probabilita'
    prima di trasformarla in soglia. Piu' la stima e' debole, piu' la
    soglia richiesta si alza.
    """
    trust = max(0.0, min(1.0, reliability)) * FAMILY_TRUST.get(fam, 0.6)
    return 0.75 + 0.25 * trust      # da 0.75 (stima debole) a 1.00 (piena)


def combo_board(model_probs: dict[str, tuple[float, float]],
                reliability: float,
                required_margin: float = 0.05,
                min_prob: float = 0.15,
                max_prob: float = 0.92,
                families: tuple[str, ...] = COMBO_FAMILIES) -> list[dict]:
    """Tabella delle combo con le soglie di quota.

    `required_margin` e' il vantaggio minimo che pretendi sopra il
    break-even prudente: 0.05 significa "gioco solo se il book paga
    almeno il 5% in piu' di quanto serva per andare in pari".
    """
    rows: list[dict] = []
    for key, (p_win, p_push) in model_probs.items():
        fam = family(key)
        if fam not in families:
            continue
        if p_push > 1e-9:          # le combo non hanno rimborsi
            continue
        if not (min_prob <= p_win <= max_prob):
            continue

        disc = confidence_discount(reliability, fam)
        p_prud = p_win * disc
        if p_prud <= 0:
            continue

        fair = 1.0 / p_win
        prudent = 1.0 / p_prud
        required = prudent * (1.0 + required_margin)

        rows.append({
            "market": key,
            "descrizione": describe(key),
            "p_modello": round(p_win, 4),
            "p_prudente": round(p_prud, 4),
            "quota_equa": round(fair, 2),
            "quota_prudente": round(prudent, 2),
            "quota_richiesta": round(required, 2),
            "affidabilita": round(reliability * FAMILY_TRUST.get(fam, 0.6), 3),
        })

    rows.sort(key=lambda r: -r["p_modello"])
    return rows


def double_combo(model_probs: dict[str, tuple[float, float]],
                 keys: list[str]) -> dict | None:
    """Combina piu' esiti dello STESSO match.

    Attenzione: gli esiti di una stessa partita NON sono indipendenti.
    Moltiplicare le probabilita' sarebbe sbagliato. Qui non si moltiplica
    nulla: si segnala che il calcolo corretto richiede la probabilita'
    congiunta dalla matrice, che e' gia' disponibile come mercato combinato
    dedicato (RES_OU, RES_BTTS, ecc.). Se la combinazione richiesta non
    esiste tra i 231 mercati, non viene stimata.
    """
    if len(keys) == 1 and keys[0] in model_probs:
        p = model_probs[keys[0]][0]
        return {"keys": keys, "p": p, "quota_equa": round(1 / p, 2) if p > 0 else None}
    return None


def multi_match_combo(picks: list[dict], required_margin: float = 0.05) -> dict:
    """Multipla su partite DIVERSE: qui il prodotto e' legittimo.

    Match diversi sono ragionevolmente indipendenti (non perfettamente:
    stesso campionato, stesse condizioni meteo, ma l'approssimazione regge).
    La probabilita' combinata cala in fretta: e' il motivo per cui le
    multiple lunghe hanno valore atteso pessimo anche partendo da
    selezioni buone.
    """
    if not picks:
        return {"n": 0}
    p = 1.0
    o = 1.0
    for x in picks:
        p *= x["p_used"]
        o *= x["odd"]
    return {
        "n": len(picks),
        "prob": round(p, 5),
        "quota": round(o, 2),
        "quota_equa": round(1 / p, 2) if p > 0 else None,
        "quota_richiesta": round((1 / p) * (1 + required_margin), 2) if p > 0 else None,
        "ev": round(p * o - 1.0, 4),
    }


# ============================================================================
# REGISTRO — staking Kelly frazionario, atteso vs realizzato
# ============================================================================
# Registro delle giocate: la parte che dice se tutto il resto funziona davvero.
#
# Perche' e' il modulo piu' importante del progetto.
#
# Un modello puo' produrre EV positivi tutti i giorni ed essere completamente
# sbagliato. L'unica prova e' il confronto tra cio' che il modello ha promesso
# e cio' che e' realmente accaduto, accumulato su decine di giocate.
#
# Senza registro non esiste apprendimento: si ricordano le vincite, si
# dimenticano le perdite, e dopo sei mesi non si sa nulla di piu' di oggi.
#
# PERSISTENZA
# Streamlit Cloud ha filesystem effimero: non c'e' un database. Il registro
# vive nella sessione e si esporta/importa via CSV. E' un passaggio manuale,
# ma e' anche l'unico che non dipende da un servizio esterno.
#
# STAKING
# Kelly pieno massimizza la crescita di lungo periodo ma con oscillazioni
# insostenibili, e va a zero se le probabilita' sono sovrastimate — che e'
# esattamente il rischio di un modello casalingo. Si usa Kelly frazionario:
# un quarto e' lo standard prudente. La frazione e' regolabile ma il tetto
# per singola giocata resta.

CAMPI = ["data", "partita", "lega", "mercato", "quota", "p_modello",
         "ev_atteso", "puntata", "esito", "ritorno"]

ESITI = ["aperta", "vinta", "persa", "rimborsata"]


def stake_for(pick: dict, bankroll: float, kelly_fraction: float,
              max_stake_pct: float = 0.02, min_stake: float = 1.0) -> float:
    """Puntata consigliata in euro.

    Tre protezioni sovrapposte, in ordine di severita':
      1. Kelly frazionario sulla frazione gia' calcolata dal motore
      2. tetto percentuale sul bankroll per singola giocata
      3. arrotondamento e puntata minima
    """
    k = max(0.0, float(pick.get("kelly", 0.0))) * kelly_fraction
    stake = bankroll * min(k, max_stake_pct)
    if stake < min_stake:
        return 0.0
    return round(stake, 2)


def row_from_pick(pick: dict, stake: float) -> dict:
    return {
        "data": datetime.now().strftime("%Y-%m-%d"),
        "partita": f"{pick['home']} - {pick['away']}",
        "lega": pick.get("league", ""),
        "mercato": pick.get("market", ""),
        "quota": pick.get("odd", 0.0),
        "p_modello": round(float(pick.get("p_used", 0.0)), 4),
        "ev_atteso": round(float(pick.get("ev", 0.0)), 4),
        "puntata": stake,
        "esito": "aperta",
        "ritorno": 0.0,
    }


def settle(row: dict) -> float:
    """Ritorno netto della singola giocata, in euro."""
    try:
        stake = float(row.get("puntata") or 0)
        odd = float(row.get("quota") or 0)
    except (TypeError, ValueError):
        return 0.0
    esito = str(row.get("esito", "aperta")).strip().lower()
    if esito == "vinta":
        return round(stake * (odd - 1.0), 2)
    if esito == "persa":
        return round(-stake, 2)
    return 0.0          # aperta o rimborsata


def summarize(rows: list[dict]) -> dict:
    """Confronto tra atteso e realizzato, piu' calibrazione per fascia.

    Il numero da guardare e' `scarto`: se dopo 100+ giocate il realizzato
    resta molto sotto l'atteso, il modello sta sovrastimando le proprie
    probabilita' e le soglie vanno alzate.
    """
    chiuse = [r for r in rows
              if str(r.get("esito", "")).lower() in ("vinta", "persa")]
    if not chiuse:
        return {"n": 0, "n_aperte": len(rows)}

    puntato = sum(float(r.get("puntata") or 0) for r in chiuse)
    realizzato = sum(settle(r) for r in chiuse)
    atteso = sum(float(r.get("puntata") or 0) * float(r.get("ev_atteso") or 0)
                 for r in chiuse)
    vinte = sum(1 for r in chiuse if str(r["esito"]).lower() == "vinta")

    # calibrazione: la probabilita' dichiarata regge al confronto coi fatti?
    fasce = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        gruppo = [r for r in chiuse
                  if lo <= float(r.get("p_modello") or 0) < lo + 0.2]
        if len(gruppo) >= 5:
            attesa = sum(float(r["p_modello"]) for r in gruppo) / len(gruppo)
            osservata = sum(1 for r in gruppo
                            if str(r["esito"]).lower() == "vinta") / len(gruppo)
            fasce.append({
                "fascia": f"{lo:.0%}-{lo + 0.2:.0%}",
                "attesa": round(attesa, 3),
                "osservata": round(osservata, 3),
                "n": len(gruppo),
            })

    return {
        "n": len(chiuse),
        "n_aperte": len(rows) - len(chiuse),
        "puntato": round(puntato, 2),
        "realizzato": round(realizzato, 2),
        "atteso": round(atteso, 2),
        "scarto": round(realizzato - atteso, 2),
        "roi": round(realizzato / puntato, 4) if puntato > 0 else 0.0,
        "roi_atteso": round(atteso / puntato, 4) if puntato > 0 else 0.0,
        "win_rate": round(vinte / len(chiuse), 3),
        "calibrazione": fasce,
    }


def to_csv(rows: list[dict]) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CAMPI, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in CAMPI})
    return buf.getvalue()


def from_csv(text: str) -> list[dict]:
    import csv
    import io
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        row = {k: r.get(k, "") for k in CAMPI}
        for num in ("quota", "p_modello", "ev_atteso", "puntata", "ritorno"):
            try:
                row[num] = float(row[num]) if row[num] not in ("", None) else 0.0
            except (TypeError, ValueError):
                row[num] = 0.0
        if str(row.get("esito", "")).lower() not in ESITI:
            row["esito"] = "aperta"
        out.append(row)
    return out


# ============================================================================
# MOTIVAZIONI — spiegazioni deterministiche
# ============================================================================
# Motivazioni deterministiche: il "perche'" di ogni selezione.
#
# Ogni frase e' derivata da un numero calcolato, mai generata liberamente.
# Se una motivazione non e' supportata da un parametro del modello,
# semplicemente non viene scritta.

def _pct(values: dict[str, float], team: str) -> float | None:
    if team not in values or len(values) < 4:
        return None
    arr = np.array(list(values.values()))
    return float((arr < values[team]).mean())


def _lbl(p: float | None) -> str:
    if p is None:
        return "non valutabile"
    if p >= 0.85:
        return "top della lega"
    if p >= 0.65:
        return "sopra media"
    if p >= 0.35:
        return "nella media"
    if p >= 0.15:
        return "sotto media"
    return "fondo lega"


def explain(pick: dict, fit, market_probs: dict[str, tuple[float, float]]) -> str:
    """Costruisce la motivazione completa di una selezione."""
    home, away = pick["home"], pick["away"]
    lam_h, lam_a = pick["lam_home"], pick["lam_away"]
    tot = lam_h + lam_a

    att_h = _lbl(_pct(fit.attack, home))
    att_a = _lbl(_pct(fit.attack, away))
    def_h = _lbl(_pct({k: -v for k, v in fit.defence.items()}, home))
    def_a = _lbl(_pct({k: -v for k, v in fit.defence.items()}, away))

    bits: list[str] = []

    # 1) cosa dice il modello in termini di gol attesi
    bits.append(
        f"**Gol attesi**: {home} {lam_h:.2f} – {away} {lam_a:.2f} "
        f"(totale {tot:.2f}). Attacco {home}: {att_h}; difesa {home}: {def_h}. "
        f"Attacco {away}: {att_a}; difesa {away}: {def_a}. "
        f"Fattore campo stimato sulla lega: +{fit.home_adv:.2f} in scala log."
    )

    # 2) perche' proprio questa classe di esito
    fam = pick["market"].split(":")[0]
    ranked = sorted(
        ((k, v[0]) for k, v in market_probs.items() if k.split(":")[0] == fam),
        key=lambda t: -t[1])
    pos = next((i for i, (k, _) in enumerate(ranked) if k == pick["market"]), None)
    if pos is not None:
        bits.append(
            f"**Classe di esito**: {describe(pick['market'])}. "
            f"All'interno della famiglia «{fam}» il modello la colloca "
            f"al {pos + 1}° posto su {len(ranked)} per probabilita'."
        )

    # 3) la discrepanza rispetto al mercato
    delta = pick["edge"] * 100
    bits.append(
        f"**Discrepanza**: modello {pick['p_used']*100:.1f}% contro mercato "
        f"{pick['p_market']*100:.1f}% → scarto di {delta:+.1f} punti. "
        f"Quota migliore {pick['odd']} ({pick['bookmaker']}, {pick['books']} book confrontati), "
        f"EV {pick['ev']*100:+.1f}%, frazione di Kelly {pick['kelly']*100:.1f}%."
    )

    # 4) da dove nasce lo scarto
    driver = []
    if fam in ("OU", "MULTIGOL", "EXACT_GOALS", "BTTS", "BTTS_OU"):
        if tot >= 3.1:
            driver.append(f"il totale atteso {tot:.2f} e' alto rispetto alla media di lega")
        elif tot <= 2.3:
            driver.append(f"il totale atteso {tot:.2f} e' basso: partita compressa")
        if min(lam_h, lam_a) >= 1.1:
            driver.append("entrambe le squadre hanno attesa di gol superiore a 1.1, "
                          "il che sostiene i mercati con entrambe a segno")
        elif min(lam_h, lam_a) <= 0.75:
            driver.append("una delle due ha attesa di gol sotto 0.75, "
                          "il che deprime i mercati con entrambe a segno")
    if fam in ("1X2", "DC", "DNB", "AH", "EH", "MARGIN", "WINTONIL", "CLEANSHEET"):
        gap = lam_h - lam_a
        if abs(gap) >= 0.6:
            fav = home if gap > 0 else away
            driver.append(f"lo scarto di gol attesi ({gap:+.2f}) indica {fav} "
                          f"nettamente favorita nel modello")
        else:
            driver.append(f"lo scarto di gol attesi e' contenuto ({gap:+.2f}): "
                          f"partita equilibrata, il che alza il peso del pareggio")
    if driver:
        bits.append("**Driver**: " + "; ".join(driver) + ".")

    # 5) limiti dichiarati
    caveat = [f"affidabilita' della stima {pick['reliability']*100:.0f}%"]
    if pick["books"] < 4:
        caveat.append(f"solo {pick['books']} bookmaker: prezzo di mercato poco robusto")
    if pick["p_push"] > 0:
        caveat.append(f"probabilita' di rimborso {pick['p_push']*100:.1f}%")
    n_h = fit.matches_per_team.get(home, 0)
    n_a = fit.matches_per_team.get(away, 0)
    if min(n_h, n_a) < 20:
        caveat.append(f"campione ridotto ({home}: {n_h} gare, {away}: {n_a})")
    if not fit.converged:
        caveat.append("la stima della lega non ha raggiunto piena convergenza")
    bits.append("**Limiti**: " + "; ".join(caveat) + ".")

    return "\n\n".join(bits)


# ============================================================================
# APP — interfaccia Streamlit
# ============================================================================
# Bet-Pro | Quant Engine v3 — app Streamlit.
#
# FLUSSO IN DUE FASI, ed e' il punto centrale del file.
#
# Streamlit riesegue l'intero script a ogni click, spostamento di slider o
# apertura di un expander. Se il calcolo pesante sta dentro `if st.button(...)`,
# alla prima interazione successiva quel blocco non viene eseguito e i risultati
# svaniscono: l'app sembra "resettarsi da sola".
#
# Qui il calcolo pesante (rete + stima dei modelli) gira SOLO su richiesta
# esplicita e deposita tutto in `st.session_state`. I filtri leggono da li'
# e sono istantanei: nessuna chiamata API, nessuna ristima.
#
#   FASE 1  [Carica ed elabora]  ->  rete, modelli, 231 mercati  ->  session_state
#   FASE 2  filtri e tab          ->  solo lettura dallo stato



TZ = ZoneInfo("Europe/Rome")

st.set_page_config(page_title="Bet-Pro v6", page_icon="📐", layout="wide")

ss = st.session_state
ss.setdefault("bundle", None)        # risultati della fase 1
ss.setdefault("model_sig", None)     # firma dei parametri usati per calcolare
ss.setdefault("backtests", {})       # cache dei backtest per lega
ss.setdefault("error", None)
ss.setdefault("registro", [])       # giocate registrate (tab Registro)


def secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


KEYS = [k.strip() for k in secret("API_FOOTBALL_KEYS", "").split(",") if k.strip()]
FD_KEYS = [k.strip() for k in secret("API_FOOTBALL_DATA_KEYS", "").split(",") if k.strip()]
ODDS_API_KEY = secret("ODDS_API_KEY", "").strip()


# =============================================================================
# FASE 1 — calcolo pesante (una sola volta, su richiesta)
# =============================================================================

@st.cache_resource(show_spinner=False, max_entries=64)
def fit_league(_client: ApiSports | None, _fd: FootballData | None, league_id,
               season: int, league_name: str, country: str,
               teams_today: tuple[str, ...], xi: float, ridge: float,
               fd_code: str | None = None):
    """Stima il modello di una lega.

    Ordine delle fonti per lo storico, deliberato:
      1. football-data.org  -> gratuito, non intacca la quota API-Sports
      2. API-Sports         -> fallback per le leghe fuori dal piano gratuito

    `_client` e `_fd` non entrano nella chiave di cache (prefisso underscore).
    """
    rows, source = [], "—"

    code = fd_code or code_for(league_name, country)
    if _fd is not None and code and _fd.available:
        rows = _fd.season_results(code, season)
        if len(rows) < 90:
            rows = rows + _fd.season_results(code, season - 1)
        if rows:
            rows, matched = align_names(rows, set(teams_today))
            source = f"football-data ({code}, {matched} squadre allineate)"

    if len(rows) < 60 and _client is not None and isinstance(league_id, int):
        rows = _client.league_history(league_id, season)
        if len(rows) < 90:
            rows = rows + _client.league_history(league_id, season - 1)
        source = "API-Sports"

    if len(rows) < 60:
        return None, rows, source

    fit = fit_dixon_coles(
        [r["home"] for r in rows], [r["away"] for r in rows],
        [r["hg"] for r in rows], [r["ag"] for r in rows],
        [days_ago(r["date"]) for r in rows],
        xi=xi, ridge=ridge, league=league_name)
    return fit, rows, source


def collect_odds_api(oa: OddsApi, max_leagues: int, day_str: str,
                     status) -> tuple[list, dict, dict]:
    """Palinsesto + quote da The Odds API. Una richiesta per campionato.

    Ritorna la stessa forma del percorso API-Sports, cosi' il resto della
    pipeline (stima, valutazione, strategie) non cambia di una riga.
    """
    status.update(label="1/4 · Campionati attivi…")
    active = {s["key"] for s in oa.list_sports()}
    wanted = [k for k in EUROPEAN_DEFAULT if k in active] or list(EUROPEAN_DEFAULT)
    for k in SPORT_TO_FD:
        if k in active and k not in wanted:
            wanted.append(k)
    wanted = wanted[:max_leagues]

    # finestra: dalle 00:00 alle 23:59 del giorno scelto, in UTC
    day = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=TZ)
    win_from = day.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    win_to = (day + timedelta(days=1) - timedelta(seconds=1)).astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries, odds_by_fid, league_meta = [], {}, {}

    for i, sk in enumerate(wanted, 1):
        status.update(label=f"2/4 · Quote {i}/{len(wanted)}: {PRETTY.get(sk, (sk,))[0]}")
        if not oa.available:
            oa.log.append("budget richieste esaurito: campionati successivi saltati")
            break
        name, country = PRETTY.get(sk, (sk.replace("soccer_", "").replace("_", " ").title(), ""))
        season = fd_season(sk)
        lkey = (sk, season)

        for ev in oa.league_odds(sk, commence_from=win_from, commence_to=win_to):
            fid = ev.get("id")
            home, away = ev.get("home_team"), ev.get("away_team")
            if not fid or not home or not away:
                continue
            try:
                ko_dt = datetime.fromisoformat(str(ev["commence_time"]).replace("Z", "+00:00"))
            except Exception:
                continue
            if ko_dt <= datetime.now(ko_dt.tzinfo):   # gia' iniziata
                continue

            parsed = parse_event(ev)
            if not parsed:
                continue

            odds_by_fid[fid] = parsed
            entries.append({"fixture_id": fid,
                            "kickoff": ko_dt.astimezone(TZ).strftime("%d/%m %H:%M"),
                            "home": home, "away": away,
                            "league": name, "country": country,
                            "league_key": lkey})
            meta = league_meta.setdefault(lkey, {"name": name, "country": country,
                                                 "teams": set(), "fd_code": SPORT_TO_FD.get(sk),
                                                 "season": season, "n": 0})
            meta["teams"].update((home, away))
            meta["n"] += 1

    return entries, odds_by_fid, league_meta


def run_pipeline(day_str: str, max_calls: int, max_leagues: int,
                 xi: float, ridge: float, status) -> dict:
    """Due percorsi di raccolta, poi tronco comune.

    GRATUITO   The Odds API (palinsesto + quote) + football-data (storico).
               Un account per servizio, nessuna forzatura sui limiti.
    API-SPORTS percorso storico, usato solo se non c'e' ODDS_API_KEY.

    Dal punto in cui entrambi hanno prodotto `entries` + `odds_by_fid`
    il codice e' identico: stima, valutazione, strategie.
    """
    t0 = time.time()
    fd = FootballData(FD_KEYS, max_calls=max(20, max_leagues * 3)) if FD_KEYS else None
    oa = OddsApi(ODDS_API_KEY, max_calls=max(4, max_leagues + 2)) if ODDS_API_KEY else None
    client = ApiSports(KEYS, max_calls=max_calls) if KEYS else None
    logs: list[str] = []

    # ------------------------------------------------------ raccolta
    if oa is not None:
        mode = "The Odds API + football-data (gratuito)"
        entries, odds_by_fid, league_meta = collect_odds_api(
            oa, max_leagues, day_str, status)
        unmatched: set[str] = set()
    elif client is not None:
        mode = "API-Sports"
        entries, odds_by_fid, league_meta, unmatched = collect_api_sports(
            client, day_str, max_leagues, status)
    else:
        return {"empty": "Nessuna fonte di quote configurata. Servono "
                         "`ODDS_API_KEY` oppure `API_FOOTBALL_KEYS`.",
                "log": [], "calls": 0}

    logs += (oa.log if oa else []) + (client.log if client else [])

    if not entries:
        if client is not None and (client.all_keys_failed or client.key_errors):
            reason = ("**Nessuna chiave API-Sports utilizzabile.**\n\n"
                      + "\n".join(f"- `{e}`" for e in dict.fromkeys(client.key_errors)))
            if any("suspend" in e.lower() for e in client.key_errors):
                reason += ("\n\nUn account sospeso si sblocca solo dal pannello del "
                           "provider. In alternativa passa al percorso gratuito "
                           "impostando `ODDS_API_KEY`.")
        elif oa is not None and oa.remaining == 0:
            reason = ("**Quota mensile di The Odds API esaurita.** "
                      "Si azzera all'inizio del mese.")
        else:
            reason = ("Nessuna partita con quote disponibili in questo momento "
                      "(i provider hanno risposto correttamente).")
        return {"empty": reason, "log": logs, "calls": (client.calls if client else 0),
                "oa_calls": oa.calls if oa else 0}

    # ------------------------------------------------------ stima modelli
    top = sorted(league_meta.items(), key=lambda kv: -kv[1]["n"])[:max_leagues]
    status.update(label=f"3/4 · Stima dei modelli ({len(top)} leghe)…")
    fits, hist, sources = {}, {}, {}
    for i, (k, meta) in enumerate(top, 1):
        status.update(label=f"3/4 · Modello {i}/{len(top)}: {meta['name']}")
        try:
            fit, rows, src = fit_league(
                client, fd, meta.get("league_id", k[0]), meta["season"],
                meta["name"], meta["country"], tuple(sorted(meta["teams"])),
                xi, ridge, fd_code=meta.get("fd_code"))
        except Exception as e:
            logs.append(f"stima {meta['name']}: {type(e).__name__} {e}")
            continue
        if fit is not None:
            fits[k], hist[k], sources[k] = fit, rows, src

    logs += (fd.log if fd else [])

    if not fits:
        return {"empty": "Nessun modello stimabile: storico insufficiente o non "
                         "recuperabile. Controlla la tab Diagnostica: senza chiavi "
                         "football-data lo storico gratuito non è disponibile.",
                "log": logs, "calls": (client.calls if client else 0),
                "oa_calls": oa.calls if oa else 0}

    # ------------------------------------------------------ valutazione
    status.update(label="4/4 · Confronto modello vs mercato…")
    picks, ctx, n_modelled = [], {}, 0

    for e in entries:
        fit = fits.get(e["league_key"])
        if fit is None:
            continue
        lam = fit.lambdas(e["home"], e["away"])
        rel = fit.reliability(e["home"], e["away"])
        odds_map = odds_by_fid.get(e["fixture_id"])
        if lam is None or rel <= 0 or not odds_map:
            continue

        model_probs = all_markets(score_matrix(lam[0], lam[1], fit.rho))
        # min_books=1: il filtro vero è in fase 2, così cambiarlo non
        # richiede di rifare la pipeline.
        picks.extend(p.dict() for p in
                     evaluate_fixture(e, model_probs, odds_map, rel, lam, min_books=1))
        ctx[e["fixture_id"]] = {"league_key": e["league_key"],
                                "model_probs": model_probs,
                                "reliability": rel,
                                "label": f"{e['kickoff']} · {e['home']} – "
                                         f"{e['away']} ({e['league']})"}
        n_modelled += 1

    return {
        "day": day_str,
        "mode": mode,
        "picks": picks,
        "ctx": ctx,
        "fits": fits,
        "hist": hist,
        "n_fixtures": len(entries),
        "n_modelled": n_modelled,
        "unmatched": sorted(unmatched),
        "sources": sources,
        "log": logs,
        "calls": client.calls if client else 0,
        "fd_calls": fd.calls if fd else 0,
        "oa_calls": oa.calls if oa else 0,
        "oa_remaining": oa.remaining if oa else None,
        "elapsed": round(time.time() - t0, 1),
    }


def collect_api_sports(client: ApiSports, day_str: str, max_leagues: int, status):
    """Percorso storico: palinsesto e quote da API-Sports."""
    status.update(label="1/4 · Palinsesto del giorno…")
    fixtures = [f for f in client.fixtures_of_day(day_str)
                if ((f.get("fixture") or {}).get("status") or {}).get("short")
                in ("NS", "TBD")]
    if not fixtures:
        return [], {}, {}, set()

    status.update(label="2/4 · Quote di tutti i bookmaker…")
    odds_raw = client.odds_of_day(day_str)

    entries, odds_by_fid, meta_by_key, unmatched = [], {}, {}, set()
    for f in fixtures:
        fx, lg = f.get("fixture") or {}, f.get("league") or {}
        fid = fx.get("id")
        if fid is None or lg.get("id") is None or lg.get("season") is None:
            continue
        if fid not in odds_raw:
            continue
        parsed = parse_fixture_odds(odds_raw[fid], min_books=1)
        unmatched |= set(parsed.pop("__unmatched__", {}).get("names", []))
        if not parsed:
            continue

        teams = f.get("teams") or {}
        home = (teams.get("home") or {}).get("name", "")
        away = (teams.get("away") or {}).get("name", "")
        try:
            ko = datetime.fromisoformat(fx.get("date", "")).astimezone(TZ).strftime("%d/%m %H:%M")
        except Exception:
            ko = "—"

        lkey = (int(lg["id"]), int(lg["season"]))
        odds_by_fid[fid] = parsed
        entries.append({"fixture_id": fid, "kickoff": ko, "home": home, "away": away,
                        "league": lg.get("name", ""), "country": lg.get("country", ""),
                        "league_key": lkey})
        m = meta_by_key.setdefault(lkey, {"name": lg.get("name", "?"),
                                          "country": lg.get("country", ""),
                                          "teams": set(), "fd_code": None,
                                          "season": int(lg["season"]),
                                          "league_id": int(lg["id"]), "n": 0})
        m["teams"].update((home, away))
        m["n"] += 1

    return entries, odds_by_fid, meta_by_key, unmatched


# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    st.header("① Dati e modello")
    st.caption("Cambiare questi valori richiede un nuovo caricamento.")
    day = st.date_input("Giornata", value=datetime.now(TZ).date())
    max_leagues = st.slider("Leghe da modellare", 2, 20, 8)
    max_calls = st.slider("Budget chiamate API", 10, 150, 45, 5)
    xi = st.slider("Time decay ξ", 0.0005, 0.0060, 0.0019, 0.0005,
                   help="Più alto = più peso alle partite recenti. 0.0019 ≈ emivita 1 anno.")
    ridge = st.slider("Shrinkage (ridge)", 0.0, 0.15, 0.02, 0.01,
                      help="Più alto = squadre più schiacciate verso la media di lega.")

    load = st.button("🔄 Carica ed elabora", type="primary", use_container_width=True)

    st.divider()
    st.header("② Filtri")
    st.caption("Istantanei: nessuna chiamata API, nessuna ristima.")
    min_ev = st.slider("EV minimo", 0.00, 0.25, 0.04, 0.01)
    min_rel = st.slider("Affidabilità minima", 0.0, 1.0, 0.45, 0.05)
    min_books = st.slider("Bookmaker minimi", 1, 10, 3)
    min_odd, max_odd = st.slider("Fascia di quota", 1.0, 30.0, (1.20, 12.0), 0.1)
    max_picks = st.slider("Selezioni per strategia", 1, 10, 5)
    one_per_fixture = st.checkbox("Max una selezione per partita", value=True)
    escludi_handicap = st.checkbox("Escludi handicap", value=True,
                                   help="Handicap asiatico ed europeo fuori dalle strategie.")

    st.divider()
    st.header("③ Bankroll")
    bankroll = st.number_input("Bankroll (€)", min_value=10.0, value=200.0, step=10.0)
    kelly_frac = st.select_slider("Frazione di Kelly", [0.10, 0.25, 0.50, 1.00],
                                  value=0.25,
                                  help="Kelly pieno massimizza la crescita ma ha "
                                       "oscillazioni insostenibili e va a zero se "
                                       "le probabilità sono sovrastimate. Un quarto "
                                       "è lo standard prudente.")
    max_stake_pct = st.slider("Tetto per singola giocata (% bankroll)",
                              0.005, 0.05, 0.02, 0.005, format="%.3f")

    st.divider()
    st.header("④ Combo")
    st.caption("Soglie di quota da confrontare con l'app del tuo bookmaker.")
    margine = st.slider("Margine richiesto sopra il break-even", 0.00, 0.30, 0.05, 0.01)
    combo_prob_min = st.slider("Probabilità minima combo", 0.05, 0.80, 0.20, 0.05)

sig = (day.isoformat(), max_leagues, xi, ridge)


# =============================================================================
# HEADER
# =============================================================================

st.title("📐 Bet-Pro | Quant Engine v6")
st.caption("Dixon-Coles indipendente · 231 classi di esito · confronto contro le quote reali")

if not KEYS and not ODDS_API_KEY:
    st.error(
        "**Manca la configurazione delle quote.**\n\n"
        "Percorso consigliato, gratuito e regolare — un account per servizio:\n\n"
        "```\n"
        "ODDS_API_KEY = \"la_tua_chiave\"                  # the-odds-api.com, quote\n"
        "API_FOOTBALL_DATA_KEYS = \"fd1,fd2\"              # football-data.org, storico\n"
        "```\n\n"
        "In alternativa `API_FOOTBALL_KEYS` per il percorso API-Sports.\n\n"
        "Su Streamlit Cloud: *Manage app → Settings → Secrets*. "
        "Mai nel repository."
    )
    st.stop()

if load:
    ss.error = None
    ss.backtests = {}
    try:
        with st.status("Elaborazione…", expanded=True) as status:
            ss.bundle = run_pipeline(day.strftime("%Y-%m-%d"), max_calls,
                                     max_leagues, xi, ridge, status)
            ss.model_sig = sig
            status.update(label="Completato", state="complete", expanded=False)
    except Exception:
        ss.bundle = None
        ss.error = traceback.format_exc()

if ss.error:
    st.error("Errore durante l'elaborazione. Traccia completa qui sotto.")
    st.code(ss.error, language="text")

if ss.bundle is None:
    st.info(
        "**Premi «Carica ed elabora» nella sidebar per iniziare.**\n\n"
        "La prima esecuzione su una lega nuova scarica lo storico della stagione "
        "e costa qualche chiamata in più; da lì in poi resta in cache per 7 giorni. "
        "I filtri della sezione ② si applicano dopo, senza ricaricare nulla."
    )
    st.stop()

B = ss.bundle

if B.get("empty"):
    st.warning(B["empty"])
    with st.expander("Diagnostica"):
        st.write(B.get("log") or "nessun errore registrato")
        st.write(f"Chiamate usate: {B.get('calls', 0)}")
    st.stop()

if ss.model_sig != sig:
    st.warning(
        "I parametri della sezione ① sono cambiati dopo l'ultimo caricamento. "
        "I risultati mostrati sono ancora quelli precedenti: premi "
        "**Carica ed elabora** per aggiornarli."
    )

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Partite in programma", B["n_fixtures"])
c2.metric("Match modellati", B["n_modelled"])
c3.metric("Esiti valutati", len(B["picks"]))
_rem = B.get("oa_remaining")
c4.metric(
    "Richieste",
    f"{B.get('oa_calls', 0) or B.get('calls', 0)} + {B.get('fd_calls', 0)}",
    help="quote + storico. " + (f"Residue su The Odds API questo mese: {_rem}."
                                if _rem is not None else ""))
c5.metric("Tempo", f"{B['elapsed']}s")
st.caption(f"Fonte dati: {B.get('mode', '—')}"
           + (f" · richieste residue questo mese: {_rem}" if _rem is not None else ""))


# =============================================================================
# FASE 2 — filtri (istantanei) e visualizzazione
# =============================================================================

pool = [p for p in B["picks"] if p["books"] >= min_books]


def strategy(name: str, euro: bool):
    class P:  # adattatore leggero: build_strategy lavora su oggetti con attributi
        def __init__(self, d):
            self.__dict__.update(d)

        def dict(self):
            return {k: v for k, v in self.__dict__.items()}

    excl = DEFAULT_EXCLUDED if escludi_handicap else \
        tuple(f for f in DEFAULT_EXCLUDED if f not in ("AH", "EH"))
    return build_strategy([P(d) for d in pool], name, only_european=euro,
                          min_ev=min_ev, min_odd=min_odd, max_odd=max_odd,
                          min_reliability=min_rel, max_picks=max_picks,
                          one_per_fixture=one_per_fixture,
                          excluded_families=excl)


s1 = strategy("Strategia 1 — Top Pick (tutte le leghe)", False)
s2 = strategy("Strategia 2 — Europee", True)

tab_str, tab_combo, tab_all, tab_reg, tab_val, tab_diag = st.tabs(
    ["🎯 Strategie", "🧩 Combo", "📊 Tutti gli esiti", "📒 Registro",
     "🔬 Validazione", "🧰 Diagnostica"])


with tab_str:
    for s in (s1, s2):
        st.subheader(s["name"])
        if not s["picks"]:
            tutti = [p for p in B["picks"] if p["books"] >= min_books]
            if s["name"].endswith("Europee"):
                tutti = [p for p in tutti
                         if any(k in p["league"].lower()
                                for k in ("champions", "premier", "liga",
                                          "serie a", "bundesliga", "ligue 1"))]
            blocchi = {
                "EV minimo": sum(1 for p in tutti if p["ev"] < min_ev),
                "affidabilità minima": sum(1 for p in tutti
                                           if p["reliability"] < min_rel),
                "fascia di quota": sum(1 for p in tutti
                                       if not (min_odd <= p["odd"] <= max_odd)),
            }
            peggiore = max(blocchi, key=blocchi.get) if tutti else None
            msg = (f"Nessuna selezione supera i filtri (candidati: {s['pool_size']} "
                   f"su {len(tutti)} esiti disponibili).")
            if peggiore and blocchi[peggiore]:
                msg += (f" Il filtro che scarta di più è **{peggiore}**: "
                        f"esclude {blocchi[peggiore]} esiti.")
            if tutti:
                best = max(tutti, key=lambda p: p["ev"])
                msg += (f" Il miglior EV disponibile oggi è "
                        f"{best['ev']*100:+.1f}% su {describe(best['market'])}.")
            st.info(msg)
            st.divider()
            continue

        a, b, c = st.columns(3)
        a.metric("Quota combinata", s["combo_odd"])
        b.metric("Probabilità modello", f"{s['combo_prob']*100:.1f}%")
        c.metric("EV combinato", f"{s['combo_ev']*100:+.1f}%")

        for p in s["picks"]:
            stake = stake_for(p, bankroll, kelly_frac, max_stake_pct)
            with st.expander(
                f"{p['kickoff']} · **{p['home']} – {p['away']}** · "
                f"{describe(p['market'])} @ {p['odd']} · EV {p['ev']*100:+.1f}% "
                f"· puntata {stake:.2f} €"
            ):
                info = B["ctx"].get(p["fixture_id"])
                if not info:
                    st.write("Contesto non disponibile.")
                    continue
                fit = B["fits"].get(info["league_key"])
                if fit is None:
                    st.write("Modello non disponibile.")
                    continue
                st.markdown(explain(p, fit, info["model_probs"]))

                sc1, sc2 = st.columns([2, 1])
                sc1.markdown(
                    f"**Puntata consigliata: {stake:.2f} €** — Kelly "
                    f"{p['kelly']*100:.1f}% × frazione {kelly_frac:g}, "
                    f"con tetto al {max_stake_pct*100:.1f}% del bankroll."
                    + ("\n\nSotto la puntata minima: il vantaggio non giustifica "
                       "il rischio a questo bankroll." if stake == 0 else "")
                )
                if stake > 0 and sc2.button(
                        "📌 Registra", key=f"reg_{s['name'][:12]}_{p['fixture_id']}_{p['market']}",
                        use_container_width=True):
                    ss.registro.append(row_from_pick(p, stake))
                    st.success("Aggiunta al registro.")
        st.divider()


with tab_combo:
    st.markdown(
        "I mercati combinati non sono pubblicati dai provider gratuiti: senza il "
        "prezzo del bookmaker non esiste un EV da calcolare. Quindi il confronto "
        "va ribaltato — qui trovi la **quota minima** sotto la quale la combo è "
        "matematicamente perdente. Apri l'app del tuo bookmaker e confronta: "
        "se paga più della *quota richiesta*, c'è valore."
    )

    fixtures_with_ctx = sorted(
        ((fid, info.get("label", str(fid))) for fid, info in B["ctx"].items()),
        key=lambda t: t[1])

    if not fixtures_with_ctx:
        st.info("Nessuna partita modellata in questo caricamento.")
    else:
        label_to_fid = {lbl: fid for fid, lbl in fixtures_with_ctx}
        scelto = st.selectbox("Partita", list(label_to_fid.keys()))
        fid = label_to_fid[scelto]
        info = B["ctx"].get(fid)

        if not info:
            st.warning("Contesto non disponibile per questa partita.")
        else:
            rel = float(info.get("reliability", 0.0))
            rows = combo_board(info["model_probs"], reliability=rel,
                               required_margin=margine, min_prob=combo_prob_min)
            if not rows:
                st.info("Nessuna combo supera la probabilità minima impostata.")
            else:
                st.dataframe([{
                    "Combo": r["descrizione"],
                    "P modello %": round(r["p_modello"] * 100, 1),
                    "Quota equa": r["quota_equa"],
                    "Quota prudente": r["quota_prudente"],
                    "Quota richiesta": r["quota_richiesta"],
                    "Affid. %": round(r["affidabilita"] * 100),
                } for r in rows], use_container_width=True, height=460)

                st.caption(
                    "**Quota equa** = break-even teorico (1/p). "
                    "**Quota prudente** include lo sconto per incertezza di stima: "
                    "più il modello è poco informato su quella partita, più si alza. "
                    "**Quota richiesta** aggiunge il margine di sicurezza che hai "
                    f"impostato ({margine*100:.0f}%). Usa sempre quest'ultima."
                )

    st.divider()
    st.subheader("Multipla su partite diverse")
    st.caption("Su match diversi il prodotto delle probabilità è legittimo. "
               "Sulla stessa partita no: gli esiti sono correlati, e per quello "
               "esistono i mercati combinati dedicati nella tabella sopra.")
    for s in (s1, s2):
        mc = multi_match_combo(s["picks"], required_margin=margine)
        if mc.get("n"):
            a, b_, c, d = st.columns(4)
            a.metric(f"{s['name'].split('—')[0].strip()} · eventi", mc["n"])
            b_.metric("Quota offerta", mc["quota"])
            c.metric("Quota richiesta", mc["quota_richiesta"])
            d.metric("EV", f"{mc['ev']*100:+.1f}%")


with tab_all:
    st.caption("Tutte le classi di esito pubblicate dai bookmaker e coperte dal modello, "
               "ordinate per valore atteso.")
    rows = sorted(pool, key=lambda p: -p["ev"])
    table = [{
        "Ora": p["kickoff"],
        "Match": f"{p['home']} – {p['away']}",
        "Lega": p["league"],
        "Mercato": describe(p["market"]),
        "Quota": p["odd"],
        "Book": p["bookmaker"],
        "N book": p["books"],
        "P modello %": round(p["p_used"] * 100, 1),
        "P mercato %": round(p["p_market"] * 100, 1),
        "Edge": round(p["edge"] * 100, 1),
        "EV %": round(p["ev"] * 100, 1),
        "Kelly %": round(p["kelly"] * 100, 1),
        "Affid. %": round(p["reliability"] * 100),
    } for p in rows]

    st.dataframe(table[:1500], use_container_width=True, height=620)

    if table:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
        st.download_button("⬇️ Scarica CSV completo", buf.getvalue(),
                           file_name=f"betpro_{B['day']}.csv", mime="text/csv")


with tab_reg:
    st.markdown(
        "**È la tab che dice se tutto il resto funziona davvero.** Un modello può "
        "produrre EV positivi ogni giorno ed essere sbagliato: l'unica prova è il "
        "confronto tra promesso e accaduto, accumulato su decine di giocate."
    )

    up = st.file_uploader("Carica un registro salvato (CSV)", type="csv")
    if up is not None and st.button("Importa nel registro"):
        try:
            ss.registro = from_csv(up.getvalue().decode("utf-8"))
            st.success(f"Importate {len(ss.registro)} righe.")
        except Exception as e:
            st.error(f"CSV non leggibile: {e}")

    if not ss.registro:
        st.info("Registro vuoto. Aggiungi selezioni dal pulsante **📌 Registra** "
                "nella tab Strategie, poi torna qui per aggiornare gli esiti.")
    else:
        st.caption("Aggiorna la colonna **esito** quando le partite si chiudono. "
                   "Le righe restano `aperta` finché non le settli.")
        edited = st.data_editor(
            ss.registro,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "esito": st.column_config.SelectboxColumn("esito", options=ESITI),
                "quota": st.column_config.NumberColumn("quota", format="%.2f"),
                "puntata": st.column_config.NumberColumn("puntata €", format="%.2f"),
                "p_modello": st.column_config.NumberColumn("p modello", format="%.3f"),
                "ev_atteso": st.column_config.NumberColumn("EV atteso", format="%.3f"),
            },
            key="editor_registro",
        )
        if isinstance(edited, list):
            ss.registro = edited

        st.download_button("⬇️ Salva registro (CSV)", to_csv(ss.registro),
                           file_name="betpro_registro.csv", mime="text/csv")

        r = summarize(ss.registro)
        st.divider()
        if not r.get("n"):
            st.info(f"Nessuna giocata ancora chiusa ({r.get('n_aperte', 0)} aperte).")
        else:
            a, b_, c, d = st.columns(4)
            a.metric("Giocate chiuse", r["n"], f"{r['n_aperte']} aperte")
            b_.metric("Realizzato", f"{r['realizzato']:+.2f} €",
                      f"atteso {r['atteso']:+.2f} €")
            c.metric("ROI", f"{r['roi']*100:+.1f}%",
                     f"atteso {r['roi_atteso']*100:+.1f}%")
            d.metric("Tasso di vittoria", f"{r['win_rate']*100:.0f}%")

            if r["n"] < 50:
                st.info(f"Con {r['n']} giocate il campione è troppo piccolo per "
                        "concludere alcunché: la varianza domina. Serve almeno "
                        "un centinaio di risultati prima di giudicare il modello.")
            elif r["scarto"] < -0.15 * max(r["puntato"], 1):
                st.error("Il realizzato è molto sotto l'atteso su un campione "
                         "ormai significativo: il modello sta sovrastimando le "
                         "proprie probabilità. Alza l'EV minimo e l'affidabilità "
                         "minima, oppure aumenta lo shrinkage.")

            if r["calibrazione"]:
                st.markdown("**Calibrazione reale** — se il modello dice 60%, "
                            "deve vincere circa il 60% delle volte.")
                st.dataframe(r["calibrazione"], use_container_width=True)

        if st.button("🗑️ Svuota registro"):
            ss.registro = []
            st.rerun()


with tab_val:
    st.caption("Se il modello non batte il baseline e non è calibrato su una lega, "
               "gli edge di quella lega sono rumore. Il backtest è pesante: "
               "si esegue su richiesta, una lega alla volta.")
    for k, fit in B["fits"].items():
        col_a, col_b = st.columns([3, 1])
        col_a.markdown(f"**{fit.league}** · {fit.n_matches} partite in archivio · "
                       f"fattore campo {fit.home_adv:+.2f} · ρ {fit.rho:+.3f}")
        if col_b.button("Esegui backtest", key=f"bt_{k}", use_container_width=True):
            rows = [{"home": r["home"], "away": r["away"], "hg": r["hg"],
                     "ag": r["ag"], "days_ago": days_ago(r["date"])}
                    for r in B["hist"][k]]
            with st.spinner(f"Walk-forward su {fit.league}…"):
                ss.backtests[str(k)] = walk_forward(rows, xi=xi, ridge=ridge)

        res = ss.backtests.get(str(k))
        if res:
            if not res.get("ok"):
                st.write(res.get("reason"))
            else:
                m1, m2, m3 = st.columns(3)
                m1.metric("Log-loss", res["logloss"],
                          f"{-res['miglioramento']:+.4f} vs baseline",
                          delta_color="inverse")
                m2.metric("Brier", res["brier"])
                m3.metric("Predizioni fuori campione", res["n_pred"])
                if res["miglioramento"] <= 0:
                    st.error("Il modello NON batte il baseline su questa lega: "
                             "non dare peso ai suoi edge.")
                if res["calibrazione"]:
                    st.dataframe(res["calibrazione"], use_container_width=True)
        st.divider()


with tab_diag:
    st.subheader("Leghe modellate")
    st.dataframe([{
        "Lega": f.league, "Squadre": len(f.teams), "Partite storico": f.n_matches,
        "Fonte storico": B.get("sources", {}).get(k, "—"),
        "Fattore campo": round(f.home_adv, 3), "rho": round(f.rho, 3),
        "Convergenza": f.converged,
    } for k, f in B["fits"].items()], use_container_width=True)
    st.caption("Se la fonte è football-data, controlla il numero di squadre allineate: "
               "un allineamento parziale riduce l'affidabilità su alcune partite.")

    st.subheader("Log delle chiamate")
    st.write(B["log"] or "nessun errore registrato")

    st.subheader("Mercati pubblicati ma non modellati")
    st.caption("Estendi `engine/odds_parser.py` per coprirli. "
               "Primo/secondo tempo, corner, cartellini e marcatori sono esclusi "
               "per scelta: richiedono modelli separati.")
    st.write(B["unmatched"] or "nessuno")

    if st.button("🗑️ Svuota cache modelli e ricarica da zero"):
        fit_league.clear()
        ss.bundle = None
        ss.backtests = {}
        st.rerun()


st.divider()
st.caption(
    "Le probabilità del modello sono stime con errore, non certezze. Un EV positivo "
    "segnala una discrepanza rispetto al mercato, non un profitto: si realizza solo "
    "su volume, con staking disciplinato, ed è compatibile con lunghe serie negative. "
    "Controlla sempre la tab Validazione prima di dare peso a un edge."
)
