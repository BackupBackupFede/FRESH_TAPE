"""Fresh Tape v2 (local) : IPO et spin-offs US de plus de N mois qui performent encore.

Sources :
  - IPO : calendrier public Nasdaq (api.nasdaq.com/api/ipo/calendar), section "priced",
    toutes bourses US (Nasdaq, NYSE, NYSE American).
  - Spin-offs : formulaires 10-12B déposés sur EDGAR (index trimestriels de la SEC), complétés
    par les 18 spin-offs de la v1. Prix de référence = première clôture.
  - Cours, secteur, capitalisation : yfinance (Yahoo Finance).

EDGAR exige une adresse de contact : variable d'environnement SEC_CONTACT (secret GitHub),
sinon sec_contact.txt (une ligne). Sans elle, les spin-offs sont limitées à la liste de la v1.

Usage :
  python freshtape.py                 # 6 mois mini, depuis 2025-01
  python freshtape.py --months 7 --start 2025-07 --min-price 2

Sorties :
  fresh_tape.md    rapport lisible sur GitHub (candidats, entrées depuis le dernier passage, backtest)
  fresh_tape.csv   tout l'univers ; la colonne `candidat` sert à repérer les entrées au passage suivant
  output/freshtape_AAAA-MM-JJ.html   tableau triable, en local
Ce n'est pas un conseil d'investissement.
"""
import argparse
import html
import json
import os
import re
import sys
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
OUT = ROOT / "output"
V1_DATA = ROOT / "freshtape_v1_data.json"
V1_SNAPSHOT = date(2026, 9, 24)
V1_START = date(2025, 7, 1)
SEC_CONTACT = ROOT / "sec_contact.txt"
SPIN_OVERRIDES = ROOT / "spinoff_overrides.json"
REPORT_MD = ROOT / "fresh_tape.md"
REPORT_CSV = ROOT / "fresh_tape.csv"

NASDAQ_URL = "https://api.nasdaq.com/api/ipo/calendar?date={ym}"
SEC_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
US_EXCHANGES = ("NASDAQ", "NYSE")

SPAC_NAME = re.compile(r"\b(acquisition|acquisitions|blank check|spac)\b", re.I)
BANK_NAME = re.compile(r"\b(bancorp|bancshares|bankshares|bank|savings|federal|financial|mhc)\b", re.I)
FORM10 = re.compile(r"^(10-12B(?:/A)?)\s+(.+?)\s{2,}(\d+)\s+(\d{4}-\d{2}-\d{2})")
SAVINGS_SIC = {6035, 6036}  # caisses d'épargne : presque toujours d'anciennes mutualistes


# ---------------------------------------------------------------- collecte IPO

def month_range(start: str, end: date):
    y, m = map(int, start.split("-"))
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_month(ym: str, today: date) -> list[dict]:
    """Lit un mois du calendrier Nasdaq. Les mois clos depuis plus de 40 jours sont mis en cache."""
    path = CACHE / f"nasdaq_{ym}.json"
    y, m = map(int, ym.split("-"))
    month_end = date(y + (m == 12), m % 12 + 1, 1)
    frozen = (today - month_end).days > 40
    if frozen and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    r = requests.get(NASDAQ_URL.format(ym=ym), headers=HEADERS, timeout=30)
    r.raise_for_status()
    rows = ((r.json().get("data") or {}).get("priced") or {}).get("rows") or []
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    time.sleep(0.5)
    return rows


def to_float(s):
    try:
        return float(str(s).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_ipos(start: str, today: date) -> pd.DataFrame:
    rows = []
    for ym in month_range(start, today):
        for r in fetch_month(ym, today):
            tk = (r.get("proposedTickerSymbol") or "").strip().upper()
            exch = (r.get("proposedExchange") or "").strip()
            if not tk or not exch.upper().startswith(US_EXCHANGES):
                continue
            rows.append({
                "ticker": tk,
                "name": (r.get("companyName") or "").strip(),
                "date": datetime.strptime(r["pricedDate"], "%m/%d/%Y").date(),
                "refPrice": to_float(r.get("proposedSharePrice")),
                "dealSize": to_float(r.get("dollarValueOfSharesOffered")),
                "exch": exch,
                "type": "ipo",
            })
    df = pd.DataFrame(rows).drop_duplicates("ticker", keep="last")
    return df.sort_values("date", ascending=False).reset_index(drop=True)


def is_spac_by_name(row) -> bool:
    if row["type"] != "ipo":
        return False
    if SPAC_NAME.search(row["name"]):
        return True
    # Les SPAC cotent en unités (suffixe U) à 10 $ pile.
    return row["refPrice"] == 10.0 and len(row["ticker"]) == 5 and row["ticker"].endswith("U")


# ---------------------------------------------------------------- collecte EDGAR / spin-offs

def sec_get(url: str):
    """GET sur sec.gov avec l'adresse de contact exigée par la SEC ; None si elle manque."""
    contact = os.environ.get("SEC_CONTACT", "").strip()
    if not contact and SEC_CONTACT.exists():
        contact = SEC_CONTACT.read_text(encoding="utf-8").strip()
    if "@" not in contact:
        return None
    r = requests.get(url, headers={"User-Agent": f"FreshTape {contact}"}, timeout=60)
    r.raise_for_status()
    time.sleep(0.15)  # la SEC tolère 10 requêtes/s
    return r


def fetch_form10_quarter(y: int, q: int, today: date):
    """Lignes 10-12B d'un index trimestriel EDGAR. Les trimestres clos sont mis en cache."""
    path = CACHE / f"edgar_form10_{y}Q{q}.json"
    q_end = date(y + (q == 4), (q * 3) % 12 + 1, 1)
    if q_end < today - timedelta(days=5) and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    r = sec_get(SEC_INDEX_URL.format(y=y, q=q))
    if r is None:
        return None
    rows = [m.groups() for m in map(FORM10.match, r.text.splitlines()) if m]
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def load_sec_tickers() -> dict:
    """CIK -> (ticker, nom, bourse), d'après le fichier de tickers courant de la SEC."""
    r = sec_get(SEC_TICKERS_URL)
    if r is None:
        return {}
    return {cik: (tk, name, exch) for cik, name, tk, exch in r.json()["data"]}


def load_spinoffs(start: str, today: date, sec_tickers: dict) -> pd.DataFrame:
    """Spin-offs : sociétés ayant déposé un 10-12B (dès un an avant `start`), plus celles de la v1.

    La date de première cotation n'est pas dans EDGAR : elle est fixée plus tard d'après Yahoo."""
    rows = {}
    y0 = int(start[:4]) - 1
    filings = {}
    for y in range(y0, today.year + 1):
        for q in range(1, 5):
            if date(y, 3 * q - 2, 1) > today:
                break
            lines = fetch_form10_quarter(y, q, today)
            if lines is None:
                print("    pas de sec_contact.txt : spin-offs limitées à la liste v1")
                filings = {}
                break
            for _, name, cik, filed in lines:
                cik, filed = int(cik), date.fromisoformat(filed)
                if cik not in filings or filed < filings[cik][1]:
                    filings[cik] = (name, filed)
        else:
            continue
        break
    for cik, (name, filed) in filings.items():
        tk, sec_name, exch = sec_tickers.get(cik, (None, None, None))
        if not tk or not exch or not exch.upper().startswith(US_EXCHANGES) or "-" in tk:
            continue  # pas encore coté, OTC, ou cotation « when-issued »
        rows[tk] = {"ticker": tk, "name": sec_name or name, "date": None, "filed": filed,
                    "exch": exch, "parent": None, "cik": cik}
    if V1_DATA.exists():
        for r in json.loads(V1_DATA.read_text(encoding="utf-8")):
            if r["type"] != "spinoff":
                continue
            rec = rows.setdefault(r["ticker"], {"ticker": r["ticker"], "name": r["name"],
                                                "filed": None, "exch": r["exch"], "cik": None})
            rec["date"] = date.fromisoformat(r["date"])
            rec["parent"] = r["parent"]
    # Corrections à la main (maisons mères connues, faux positifs) : spinoff_overrides.json.
    if SPIN_OVERRIDES.exists():
        ov = json.loads(SPIN_OVERRIDES.read_text(encoding="utf-8"))
        for tk, reason in ov.get("exclude", {}).items():
            if rows.pop(tk, None):
                print(f"    {tk} écarté : {reason}")
        for tk, parent in ov.get("parents", {}).items():
            if tk in rows and not rows[tk].get("parent"):
                rows[tk]["parent"] = parent
    df = pd.DataFrame(rows.values())
    df["type"], df["refPrice"], df["dealSize"] = "spinoff", None, None
    return df


def resolve_spinoff_dates(df: pd.DataFrame, closes: pd.DataFrame, dl_start: date) -> pd.DataFrame:
    """Date de spin-off = première clôture Yahoo. Écarte les titres qui cotaient déjà avant
    leur 10-12B (sociétés existantes qui changent de cotation, tickers réutilisés)."""
    dropped = []
    for i, r in df[(df["type"] == "spinoff") & df["date"].isna()].iterrows():
        s = closes[r["ticker"]].dropna() if r["ticker"] in closes else pd.Series(dtype=float)
        if s.empty:
            dropped.append(f"{r['ticker']} (pas de cours)")
            continue
        first = s.index[0].date()
        if first <= dl_start + timedelta(days=7) or (r["filed"] and first < r["filed"]):
            dropped.append(f"{r['ticker']} (cotait déjà)")
            continue
        df.at[i, "date"] = first
    if dropped:
        print("    10-12B écartés : " + ", ".join(dropped))
    return df[df["date"].notna()].reset_index(drop=True)


def tag_mutual_conversions(df: pd.DataFrame, sec_tickers: dict):
    """Les conversions de banques mutualistes s'introduisent à 10 $ pile. Le code SIC EDGAR
    (6035/6036, caisses d'épargne) confirme ; sinon l'étiquette reste au conditionnel."""
    by_ticker = {tk: cik for cik, (tk, _, _) in sec_tickers.items()}
    mask = (df["type"] == "ipo") & (df["refPrice"] == 10.0) & ~df["spac"] & df["name"].str.contains(BANK_NAME)
    for i in df[mask].index:
        cik = by_ticker.get(df.at[i, "ticker"])
        sic = None
        if cik:
            r = sec_get(SEC_SUBMISSIONS_URL.format(cik=cik))
            sic = int(r.json().get("sic") or 0) if r is not None else None
        df.at[i, "note"] = "conversion mutualiste" if sic in SAVINGS_SIC else "conversion mutualiste ?"


# ---------------------------------------------------------------- cours

def download_closes(tickers: list[str], start: date) -> pd.DataFrame:
    yf.set_tz_cache_location(str(CACHE / "yf_tz"))
    frames = []
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        d = yf.download(chunk, start=start.isoformat(), auto_adjust=False, progress=False,
                        threads=True, group_by="column")
        if d.empty:
            continue
        c = d["Close"]
        if isinstance(c, pd.Series):
            c = c.to_frame(chunk[0])
        frames.append(c)
    closes = pd.concat(frames, axis=1) if frames else pd.DataFrame()
    closes = closes.loc[:, ~closes.columns.duplicated()]
    # Les téléchargements groupés de Yahoo perdent parfois des titres : 2e passe, un par un.
    missing = [t for t in tickers if t not in closes or closes[t].dropna().empty]
    for tk in missing:
        try:
            h = yf.Ticker(tk).history(start=start.isoformat(), auto_adjust=False)
        except Exception:
            continue
        if not h.empty:
            h.index = h.index.tz_localize(None).normalize()
            closes = closes.drop(columns=tk, errors="ignore").join(h["Close"].rename(tk), how="outer")
    return closes


def fetch_info(tickers: list[str]) -> dict:
    """Secteur, industrie, capitalisation. Le secteur est mis en cache, la capitalisation non."""
    path = CACHE / "yf_info.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = {}
    for tk in tickers:
        try:
            i = yf.Ticker(tk).info or {}
        except Exception:
            i = {}
        prev = cache.get(tk, {})
        rec = {
            "sector": i.get("sector") or prev.get("sector"),
            "industry": i.get("industry") or prev.get("industry"),
            "mc": round(i["marketCap"] / 1e6) if i.get("marketCap") else None,
            "longName": i.get("longName") or prev.get("longName"),
        }
        cache[tk] = {k: rec[k] for k in ("sector", "industry", "longName")}
        out[tk] = rec
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ---------------------------------------------------------------- calculs

def pct(a, b):
    return None if a is None or b is None or not b else round((a / b - 1) * 100, 1)


def metrics(row, s: pd.Series, spy: pd.Series, months: int, hold_days: int) -> dict:
    s = s.dropna()
    s = s[s.index.date >= row["date"]]
    if s.empty:
        return {"status": "pas de cours"}
    first, last = float(s.iloc[0]), float(s.iloc[-1])
    ref = row["refPrice"] or first
    # Un regroupement d'actions relève tout l'historique Yahoo, pas le prix d'IPO.
    split_suspect = row["refPrice"] is not None and first / row["refPrice"] > 8
    ma50 = s.iloc[-50:].mean() if len(s) >= 50 else None
    m = {
        "status": "ok",
        "price": round(last, 2),
        "lastDate": s.index[-1].date(),
        "firstClose": round(first, 2),
        "ret": pct(last, ref),
        "retFirstClose": pct(last, first),
        "ret1m": pct(last, float(s.iloc[-22])) if len(s) > 22 else None,
        "ret3m": pct(last, float(s.iloc[-64])) if len(s) > 64 else None,
        "fromHigh": pct(last, float(s.max())),
        "aboveMa50": None if ma50 is None else bool(last > ma50),
        "splitSuspect": split_suspect,
    }
    # Point de signal (cotation + N mois) et rendement des hold_days séances suivantes, pour le backtest.
    sig_day = pd.Timestamp(row["date"] + timedelta(days=round(months * 30.44)))
    after = s[s.index >= sig_day]
    if len(after) > hold_days:
        p0, p1 = float(after.iloc[0]), float(after.iloc[hold_days])
        d0, d1 = after.index[0], after.index[hold_days]
        spy_w = spy[(spy.index >= d0) & (spy.index <= d1)]
        m.update({
            "sigRet": pct(p0, ref if not split_suspect else first),
            "fwdRet": pct(p1, p0),
            "fwdSpy": pct(float(spy_w.iloc[-1]), float(spy_w.iloc[0])) if len(spy_w) > 1 else None,
        })
    return m


def backtest(df: pd.DataFrame, months: int, hold_days: int):
    bt = df[(~df["spac"]) & df.get("fwdRet").notna()].copy() if "fwdRet" in df else pd.DataFrame()
    if bt.empty:
        print("\nBacktest : pas assez d'historique.")
        return None
    bt["excess"] = bt["fwdRet"] - bt["fwdSpy"]
    lines = []
    for kind, label_kind in (("ipo", "IPO"), ("spinoff", "Spin-offs")):
        sub = bt[bt["type"] == kind]
        for label, g in ((f"{label_kind} positives à M+{months} (signal)", sub[sub["sigRet"] > 0]),
                         (f"{label_kind} négatives à M+{months}", sub[sub["sigRet"] <= 0]),
                         (f"{label_kind} toutes", sub)):
            if g.empty:
                continue
            lines.append({
                "groupe": label, "n": len(g),
                "moyenne %": round(g["fwdRet"].mean(), 1),
                "médiane %": round(g["fwdRet"].median(), 1),
                "% gagnantes": round((g["fwdRet"] > 0).mean() * 100),
                "vs SPY moy. %": round(g["excess"].mean(), 1),
                "vs SPY méd. %": round(g["excess"].median(), 1),
            })
    res = pd.DataFrame(lines)
    print(f"\nBacktest : achat à cotation + {months} mois, conservation {hold_days} séances "
          f"(titres assez anciens, hors SPAC)")
    print(res.to_string(index=False))
    return res


# ---------------------------------------------------------------- sorties

def fmt(v, suffix=""):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/d"
    if isinstance(v, float):
        return f"{v:+.1f}{suffix}" if suffix == " %" else f"{v:,.2f}{suffix}"
    return f"{v}{suffix}"


def write_html(cand: pd.DataFrame, bt, args, today: date, path: Path, n_universe: int):
    cols = [("ticker", "Ticker"), ("name", "Société"), ("kind", "Type"), ("date", "Cotation"),
            ("age", "Âge (mois)"), ("refPrice", "Prix IPO"), ("price", "Cours"), ("ret", "Perf. réf."),
            ("retFirstClose", "Perf. 1re clôture"), ("ret3m", "3 mois"), ("ret1m", "1 mois"),
            ("fromHigh", "Depuis plus haut"), ("trend", "Tendance"), ("sector", "Secteur"),
            ("mc", "Cap. (M$)"), ("exch", "Bourse"), ("parent", "Maison mère"), ("note", "Note"),
            ("new", "Nouveau")]
    pct_cols = {"ret", "retFirstClose", "ret3m", "ret1m", "fromHigh"}
    body = []
    for _, r in cand.iterrows():
        tds = []
        for k, _ in cols:
            v = r.get(k)
            if k in pct_cols:
                txt = fmt(v, " %")
                cls = "" if txt == "n/d" else ("pos" if v > 0 else "neg")
                sort = "" if txt == "n/d" else v
                tds.append(f'<td class="num {cls}" data-v="{sort}">{txt}</td>')
            elif k in ("refPrice", "price", "age"):
                tds.append(f'<td class="num" data-v="{"" if pd.isna(v) else v}">{fmt(v)}</td>')
            elif k == "mc":
                tds.append(f'<td class="num" data-v="{"" if pd.isna(v) else v}">'
                           f'{"n/d" if pd.isna(v) else f"{int(v):,}".replace(",", " ")}</td>')
            elif k in ("note", "new") and (v is None or pd.isna(v)):
                tds.append("<td></td>")
            else:
                tds.append(f"<td>{html.escape(fmt(v))}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    head = "".join(f'<th data-k="{i}">{html.escape(t)}</th>' for i, (_, t) in enumerate(cols))
    bt_html = bt.to_html(index=False, border=0, classes="bt") if bt is not None else "<p>n/d</p>"
    n_ipo, n_spin = (cand["type"] == "ipo").sum(), (cand["type"] == "spinoff").sum()
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fresh Tape v2</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--line:#e3e2dc;--pos:#137a3d;--neg:#b42318;--hd:#f0efe9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe6;--mut:#9a9992;--line:#2c2c2a;--pos:#4cc47a;--neg:#f07267;--hd:#1f1f1d}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px}}
h1{{margin:0 0 4px;font-size:22px}} .mut{{color:var(--mut)}} .wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;margin-top:12px}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:left}}
th{{background:var(--hd);cursor:pointer;position:sticky;top:0}} td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}} table.bt{{width:auto}}
</style></head><body>
<h1>Fresh Tape v2 — snapshot du {today:%d/%m/%Y}</h1>
<p class="mut">IPO et spin-offs US depuis {args.start}, âge ≥ {args.months:g} mois, hors SPAC, perf. depuis la référence &gt; 0,
cours ≥ {args.min_price:g} $. {len(cand)} titres ({n_ipo} IPO, {n_spin} spin-offs) sur {n_universe} cotations.
Cours figés à la date du snapshot (relancer le script pour les mettre à jour).
Référence = prix d'IPO, ou première clôture pour les spin-offs (qui n'ont pas de prix d'introduction).
« Tendance » = au-dessus de la moyenne 50 séances et 3 mois positif.
« Nouveau » : « seuil franchi » = a passé {args.months:g} mois depuis la v1 du 24/09/2026 ; « absent v1 » = manquait dans la v1 ; « avant v1 » = cotation antérieure à juillet 2025, hors du périmètre de la v1.
« Conversion mutualiste » = banque introduite à 10 $ avec un code SIC de caisse d'épargne ; « ? » = indice par le nom seulement.
Une perf. 3 mois à 0,0 % signale souvent un titre qui ne traite presque pas.
Sources : calendrier IPO Nasdaq, EDGAR (formulaires 10-12B), Yahoo Finance (yfinance). Valeur inconnue = n/d.</p>
<div class="wrap"><table id="t"><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
<h2>Backtest rapide</h2>
<p class="mut">Achat de chaque titre (hors SPAC) à cotation + {args.months:g} mois, conservé {args.hold} séances. Petit échantillon, biais du survivant
(les titres radiés n'ont plus de cours sur Yahoo) : indicatif seulement.</p>
{bt_html}
<p class="mut">Ce document n'est pas un conseil d'investissement.</p>
<script>
document.querySelectorAll('#t th').forEach(th=>th.onclick=()=>{{
 const i=+th.dataset.k, tb=document.querySelector('#t tbody'), rows=[...tb.rows];
 const dir=th.dataset.d=th.dataset.d==='1'?'-1':'1';
 const val=r=>{{const c=r.cells[i];return c.dataset.v!==undefined?(c.dataset.v===''?null:+c.dataset.v):c.textContent}};
 rows.sort((a,b)=>{{const x=val(a),y=val(b);if(x===null)return 1;if(y===null)return -1;
  return (typeof x==='number'?x-y:String(x).localeCompare(y))*dir}});
 rows.forEach(r=>tb.appendChild(r));}});
</script></body></html>"""
    path.write_text(page, encoding="utf-8")


def md_table(rows: pd.DataFrame) -> str:
    cols = [("ticker", "Ticker"), ("name", "Société"), ("kind", "Type"), ("date", "Cotation"),
            ("age", "Âge (mois)"), ("ret", "Perf. réf."), ("ret3m", "3 mois"), ("trend", "Tendance"),
            ("sector", "Secteur"), ("mc", "Cap. (M$)"), ("parent", "Maison mère"), ("note", "Note"),
            ("new", "Nouveau")]
    out = ["| " + " | ".join(t for _, t in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in rows.iterrows():
        cells = []
        for k, _ in cols:
            v = r.get(k)
            if k in ("ret", "ret3m"):
                cells.append(fmt(v, " %"))
            elif k == "mc":
                cells.append("n/d" if pd.isna(v) else f"{int(v):,}".replace(",", " "))
            elif k in ("note", "new", "parent") and (v is None or pd.isna(v)):
                cells.append("")
            elif k == "age":
                cells.append(f"{v:.1f}")
            else:
                cells.append(fmt(v).replace("|", "/"))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def write_md(cand, entrants, bt, args, today: date, n_universe: int, first_run: bool):
    n_ipo, n_spin = (cand["type"] == "ipo").sum(), (cand["type"] == "spinoff").sum()
    if first_run:
        new_txt = "_Premier passage : pas de comparaison possible._"
    elif entrants.empty:
        new_txt = "_Aucune entrée depuis le passage précédent._"
    else:
        new_txt = md_table(entrants)
    bt_txt = "n/d" if bt is None else "\n".join(
        ["| " + " | ".join(bt.columns) + " |", "|" + "---|" * len(bt.columns)]
        + ["| " + " | ".join(str(v) for v in row) + " |" for row in bt.itertuples(index=False)])
    REPORT_MD.write_text(f"""# Fresh Tape — snapshot du {today:%d/%m/%Y}

IPO et spin-offs US cotées depuis {args.start}, âge ≥ {args.months:g} mois, hors SPAC, au-dessus de leur
référence, cours ≥ {args.min_price:g} $ : **{len(cand)} titres** ({n_ipo} IPO, {n_spin} spin-offs) sur {n_universe} cotations.

## Entrées depuis le dernier passage

{new_txt}

## Tous les candidats

Triés par performance depuis la référence (prix d'IPO, ou première clôture pour une spin-off).

{md_table(cand)}

## Backtest rapide

Achat de chaque titre (hors SPAC) à cotation + {args.months:g} mois, conservé {args.hold} séances.
Petit échantillon et biais du survivant (les titres radiés n'ont plus de cours sur Yahoo) : indicatif seulement.

{bt_txt}

## Lecture

- « Tendance » : au-dessus de la moyenne 50 séances et 3 mois positif.
- « Nouveau » : « seuil franchi » = a passé {args.months:g} mois depuis la v1 du 24/09/2026 ; « absent v1 » = manquait
  dans la v1 ; « avant v1 » = cotation antérieure à juillet 2025.
- « Conversion mutualiste » : banque introduite à 10 $ avec un code SIC de caisse d'épargne ; « ? » = indice par le nom seulement.
- Une perf. 3 mois à 0,0 % signale souvent un titre qui ne traite presque pas.
- Sources : calendrier IPO Nasdaq, EDGAR (formulaires 10-12B), Yahoo Finance. Valeur inconnue = n/d.
- Cours figés à la date du snapshot.

*Travail d'analyse quantitative, sans valeur de conseil en investissement.*
""", encoding="utf-8")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", type=float, default=6, help="ancienneté minimale en mois (défaut 6)")
    ap.add_argument("--start", default="2025-01", help="premier mois de cotation, AAAA-MM (défaut 2025-01)")
    ap.add_argument("--min-price", type=float, default=1.0, help="cours minimal en $ (défaut 1)")
    ap.add_argument("--hold", type=int, default=63, help="séances de détention pour le backtest (défaut 63 ≈ 3 mois)")
    ap.add_argument("--no-info", action="store_true", help="ne pas lire secteur/capitalisation (plus rapide)")
    args = ap.parse_args()

    today = date.today()
    start_day = date.fromisoformat(args.start + "-01")
    CACHE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    print(f"1/5 Calendrier Nasdaq depuis {args.start}…")
    ipos = load_ipos(args.start, today)
    print(f"    {len(ipos)} IPO")

    print("2/5 Spin-offs (EDGAR 10-12B + v1)…")
    sec_tickers = load_sec_tickers()
    spins = load_spinoffs(args.start, today, sec_tickers)
    print(f"    {len(spins)} spin-offs possibles")

    # Une société à la fois dans le calendrier IPO et dans EDGAR garde sa ligne IPO (elle a un prix).
    both = sorted(set(ipos["ticker"]) & set(spins["ticker"]))
    if both:
        print("    aussi au calendrier IPO, gardées comme IPO : " + ", ".join(both))
    df = pd.concat([ipos, spins], ignore_index=True).drop_duplicates("ticker").reset_index(drop=True)
    df["spac"] = df.apply(is_spac_by_name, axis=1)
    print(f"    {df['spac'].sum()} SPAC détectées par le nom")

    print("3/5 Cours Yahoo…")
    dl_start = min(ipos["date"].min(), start_day) - timedelta(days=5)
    closes = download_closes(df.loc[~df["spac"], "ticker"].tolist() + ["SPY"], dl_start)
    spy = closes["SPY"].dropna() if "SPY" in closes else pd.Series(dtype=float)
    df = resolve_spinoff_dates(df, closes, dl_start)
    df = df[df["date"] >= start_day].reset_index(drop=True)
    recs = [metrics(r, closes[r["ticker"]] if r["ticker"] in closes else pd.Series(dtype=float),
                    spy, args.months, args.hold) if not r["spac"] else {"status": "SPAC"}
            for _, r in df.iterrows()]
    df = pd.concat([df, pd.DataFrame(recs)], axis=1)
    df["kind"] = df["type"].map({"ipo": "IPO", "spinoff": "Spin-off"})
    df["age"] = df["date"].map(lambda d: round((today - d).days / 30.44, 1))
    df["trend"] = df.apply(lambda r: "oui" if r.get("aboveMa50") and (r.get("ret3m") or 0) > 0
                           else ("non" if r.get("status") == "ok" else None), axis=1)
    # Si le prix d'IPO est faussé par un regroupement d'actions, on mesure depuis la 1re clôture.
    df.loc[df["splitSuspect"] == True, "ret"] = df["retFirstClose"]

    cand_mask = ((df["status"] == "ok") & (df["age"] >= args.months)
                 & (df["ret"] > 0) & (df["price"] >= args.min_price))
    print(f"    {(df['status'] == 'ok').sum()} titres cotés, {cand_mask.sum()} candidats")

    print("4/5 Secteurs, capitalisations, conversions mutualistes…")
    if not args.no_info:
        info = fetch_info(df.loc[cand_mask, "ticker"].tolist())
        for k in ("sector", "industry", "mc"):
            df[k] = df["ticker"].map(lambda t: info.get(t, {}).get(k))
        shell = df["industry"] == "Shell Companies"
        if shell.any():
            print(f"    {shell.sum()} société(s) écran (SPAC) repérée(s) par Yahoo : "
                  + ", ".join(df.loc[shell, "ticker"]))
            df.loc[shell, "spac"] = True
            cand_mask &= ~shell
    else:
        df["sector"] = df["industry"] = df["mc"] = None
    df["note"] = None
    tag_mutual_conversions(df, sec_tickers)
    print(f"    {df['note'].notna().sum()} conversion(s) mutualiste(s) étiquetée(s)")

    # "Nouveau" : a franchi le seuil d'âge depuis le snapshot v1, ou manquait dans la période
    # couverte par la v1 (trou de janvier 2026, etc.). Les cotations antérieures à la v1 sont signalées à part.
    v1 = {r["ticker"] for r in json.loads(V1_DATA.read_text(encoding="utf-8"))} if V1_DATA.exists() else set()
    v1_cut = V1_SNAPSHOT - timedelta(days=round(args.months * 30.44))
    df["new"] = df.apply(lambda r: "seuil franchi" if r["date"] > v1_cut
                         else "avant v1" if r["date"] < V1_START
                         else "absent v1" if r["ticker"] not in v1 else None, axis=1)

    print("5/5 Backtest et sorties…")
    bt = backtest(df, int(args.months), args.hold)
    cand = df[cand_mask].sort_values("ret", ascending=False)

    # Entrées : candidats absents du passage précédent (lu dans fresh_tape.csv avant de l'écraser).
    first_run = not REPORT_CSV.exists()
    prev = set()
    if not first_run:
        p = pd.read_csv(REPORT_CSV, sep=";", decimal=",")
        if "candidat" in p:
            prev = set(p.loc[p["candidat"].astype(str) == "True", "ticker"])
        else:
            first_run = True
    entrants = cand.iloc[0:0] if first_run else cand[~cand["ticker"].isin(prev)]

    stamp = today.isoformat()
    df["candidat"] = cand_mask
    csv_cols = ["ticker", "name", "kind", "candidat", "date", "age", "exch", "parent", "refPrice", "firstClose",
                "price", "lastDate", "ret", "retFirstClose", "ret1m", "ret3m", "fromHigh", "aboveMa50", "trend",
                "splitSuspect", "spac", "note", "sector", "industry", "mc", "dealSize", "status", "new"]
    df[csv_cols].sort_values(["candidat", "ret"], ascending=False).to_csv(
        REPORT_CSV, index=False, encoding="utf-8-sig", sep=";", decimal=",")
    write_md(cand, entrants, bt, args, today, len(df), first_run)
    write_html(cand, bt, args, today, OUT / f"freshtape_{stamp}.html", len(df))

    show = cand[["ticker", "name", "kind", "date", "age", "ret", "ret3m", "trend", "note", "new"]].copy()
    show["name"] = show["name"].str.slice(0, 30)
    print(f"\nCandidats ({len(cand)}) :")
    print(show.fillna("").to_string(index=False))
    print("\nPar rapport à la v1 : " + ", ".join(f"{k} = {v}" for k, v in cand["new"].value_counts().items()))
    print("Entrées depuis le dernier passage : "
          + ("premier passage" if first_run else (", ".join(entrants["ticker"]) or "aucune")))
    print(f"Fichiers : {REPORT_MD}\n           {REPORT_CSV}\n           {OUT / f'freshtape_{stamp}.html'}")


if __name__ == "__main__":
    sys.exit(main())
