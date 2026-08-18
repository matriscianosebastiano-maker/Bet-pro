"""
Bet-Pro | Quant Engine v3 — VERSIONE MONOFILE
=============================================

Tutto il progetto in un unico file, pensato per essere incollato direttamente
come `app.py` in un repo GitHub e deployato su Streamlit Community Cloud
senza creare sottocartelle.

Serve solo un altro file nel repo: requirements.txt

    streamlit>=1.36
    requests>=2.31
    numpy>=1.26
    scipy>=1.11

E i secret, che NON vanno nel repo ma in
Streamlit Cloud -> Manage app -> Settings -> Secrets:

    API_FOOTBALL_KEYS = "chiave1,chiave2,chiave3"

Struttura interna (cerca i banner ===== per navigare):
  1. Modello Dixon-Coles
  2. Generazione dei 231 mercati
  3. Backtest walk-forward
  4. Client API con budget e cache
  5. Parser dei mercati bookmaker
  6. Motore di valore
  7. Motivazioni
  8. Interfaccia Streamlit
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
# DATI — client API-Sports con budget e cache
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
                msg = list(errs.values())[0] if isinstance(errs, dict) else errs[0]
                if "limit" in str(msg).lower() or "quota" in str(msg).lower():
                    self.log.append(f"{path}: limite piano ({msg}) -> prossima chiave")
                    self.ki += 1
                    continue
                self.log.append(f"{path}: {msg}")
                return None
            return data
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
# PARSER — mercati bookmaker verso chiavi canoniche
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
) -> dict:
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

st.set_page_config(page_title="Bet-Pro v3", page_icon="📐", layout="wide")

ss = st.session_state
ss.setdefault("bundle", None)        # risultati della fase 1
ss.setdefault("model_sig", None)     # firma dei parametri usati per calcolare
ss.setdefault("backtests", {})       # cache dei backtest per lega
ss.setdefault("error", None)


def secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


KEYS = [k.strip() for k in secret("API_FOOTBALL_KEYS", "").split(",") if k.strip()]


# =============================================================================
# FASE 1 — calcolo pesante (una sola volta, su richiesta)
# =============================================================================

@st.cache_resource(show_spinner=False, max_entries=64)
def fit_league(_client: ApiSports, league_id: int, season: int,
               league_name: str, xi: float, ridge: float):
    """Cache per (lega, stagione, parametri). `_client` non entra nella chiave."""
    rows = _client.league_history(league_id, season)
    if len(rows) < 90:
        rows = rows + _client.league_history(league_id, season - 1)
    if len(rows) < 60:
        return None, rows
    fit = fit_dixon_coles(
        [r["home"] for r in rows], [r["away"] for r in rows],
        [r["hg"] for r in rows], [r["ag"] for r in rows],
        [days_ago(r["date"]) for r in rows],
        xi=xi, ridge=ridge, league=league_name)
    return fit, rows


def run_pipeline(day_str: str, max_calls: int, max_leagues: int,
                 xi: float, ridge: float, status) -> dict:
    t0 = time.time()
    client = ApiSports(KEYS, max_calls=max_calls)

    status.update(label="1/4 · Palinsesto del giorno…")
    fixtures = [
        f for f in client.fixtures_of_day(day_str)
        if ((f.get("fixture") or {}).get("status") or {}).get("short") in ("NS", "TBD")
    ]
    if not fixtures:
        return {"empty": "Nessuna partita in programma per questa data.",
                "log": client.log, "calls": client.calls}

    leagues: dict[tuple[int, int], dict] = {}
    for f in fixtures:
        lg = f.get("league") or {}
        if lg.get("id") is None or lg.get("season") is None:
            continue
        k = (int(lg["id"]), int(lg["season"]))
        leagues.setdefault(k, {"name": lg.get("name", "?"),
                               "country": lg.get("country", ""), "n": 0})
        leagues[k]["n"] += 1
    top = sorted(leagues.items(), key=lambda kv: -kv[1]["n"])[:max_leagues]

    status.update(label="2/4 · Quote di tutti i bookmaker…")
    odds_raw = client.odds_of_day(day_str)

    status.update(label=f"3/4 · Stima dei modelli ({len(top)} leghe)…")
    fits, hist = {}, {}
    for i, (k, meta) in enumerate(top, 1):
        status.update(label=f"3/4 · Modello {i}/{len(top)}: {meta['name']}")
        try:
            fit, rows = fit_league(client, k[0], k[1], meta["name"], xi, ridge)
        except Exception as e:
            client.log.append(f"stima {meta['name']}: {type(e).__name__} {e}")
            continue
        if fit is not None:
            fits[k] = fit
            hist[k] = rows

    if not fits:
        return {"empty": "Nessun modello stimabile: storico insufficiente "
                         "o quota API esaurita. Controlla la tab Diagnostica.",
                "log": client.log, "calls": client.calls}

    status.update(label="4/4 · Confronto modello vs mercato…")
    picks, ctx, unmatched = [], {}, set()
    n_modelled = 0

    for f in fixtures:
        fx = f.get("fixture") or {}
        lg = f.get("league") or {}
        fid = fx.get("id")
        if lg.get("id") is None or lg.get("season") is None or fid is None:
            continue
        fit = fits.get((int(lg["id"]), int(lg["season"])))
        if fit is None or fid not in odds_raw:
            continue

        teams = f.get("teams") or {}
        home = (teams.get("home") or {}).get("name", "")
        away = (teams.get("away") or {}).get("name", "")
        lam = fit.lambdas(home, away)
        rel = fit.reliability(home, away)
        if lam is None or rel <= 0:
            continue

        model_probs = all_markets(score_matrix(lam[0], lam[1], fit.rho))
        odds_map = parse_fixture_odds(odds_raw[fid], min_books=1)
        unmatched |= set(odds_map.pop("__unmatched__", {}).get("names", []))
        if not odds_map:
            continue

        try:
            ko = datetime.fromisoformat(fx.get("date", "")).astimezone(TZ).strftime("%d/%m %H:%M")
        except Exception:
            ko = "—"

        match = {"fixture_id": fid, "kickoff": ko, "home": home, "away": away,
                 "league": lg.get("name", ""), "country": lg.get("country", "")}
        # min_books=1 qui: il filtro vero e' applicato in fase 2, cosi'
        # cambiarlo non richiede di rifare la pipeline.
        picks.extend(p.dict() for p in
                     evaluate_fixture(match, model_probs, odds_map, rel, lam, min_books=1))
        ctx[fid] = {"league_key": (int(lg["id"]), int(lg["season"])),
                    "model_probs": model_probs}
        n_modelled += 1

    return {
        "day": day_str,
        "picks": picks,
        "ctx": ctx,
        "fits": fits,
        "hist": hist,
        "n_fixtures": len(fixtures),
        "n_modelled": n_modelled,
        "unmatched": sorted(unmatched),
        "log": client.log,
        "calls": client.calls,
        "elapsed": round(time.time() - t0, 1),
    }


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

sig = (day.isoformat(), max_leagues, xi, ridge)


# =============================================================================
# HEADER
# =============================================================================

st.title("📐 Bet-Pro | Quant Engine v3")
st.caption("Dixon-Coles indipendente · 231 classi di esito · confronto contro le quote reali")

if not KEYS:
    st.error(
        "**Manca la configurazione.** Serve almeno una chiave API-Sports.\n\n"
        "In locale: crea `.streamlit/secrets.toml` con "
        "`API_FOOTBALL_KEYS = \"chiave1,chiave2\"`.\n\n"
        "Su Streamlit Cloud: *Manage app → Settings → Secrets* e incolla la stessa riga."
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
c4.metric("Chiamate API", B["calls"])
c5.metric("Tempo", f"{B['elapsed']}s")


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

    return build_strategy([P(d) for d in pool], name, only_european=euro,
                          min_ev=min_ev, min_odd=min_odd, max_odd=max_odd,
                          min_reliability=min_rel, max_picks=max_picks,
                          one_per_fixture=one_per_fixture)


s1 = strategy("Strategia 1 — Top Pick (tutte le leghe)", False)
s2 = strategy("Strategia 2 — Europee", True)

tab_str, tab_all, tab_val, tab_diag = st.tabs(
    ["🎯 Strategie", "📊 Tutti gli esiti", "🔬 Validazione", "🧰 Diagnostica"])


with tab_str:
    for s in (s1, s2):
        st.subheader(s["name"])
        if not s["picks"]:
            st.info(f"Nessuna selezione supera i filtri correnti "
                    f"(candidati nel pool: {s['pool_size']}). "
                    f"Prova ad abbassare EV minimo o affidabilità minima.")
            st.divider()
            continue

        a, b, c = st.columns(3)
        a.metric("Quota combinata", s["combo_odd"])
        b.metric("Probabilità modello", f"{s['combo_prob']*100:.1f}%")
        c.metric("EV combinato", f"{s['combo_ev']*100:+.1f}%")

        for p in s["picks"]:
            with st.expander(
                f"{p['kickoff']} · **{p['home']} – {p['away']}** · "
                f"{describe(p['market'])} @ {p['odd']} · EV {p['ev']*100:+.1f}%"
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
        st.divider()


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
        "Fattore campo": round(f.home_adv, 3), "rho": round(f.rho, 3),
        "Convergenza": f.converged,
    } for f in B["fits"].values()], use_container_width=True)

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
