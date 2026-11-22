#!/usr/bin/env python3
"""
SMI Bot – powiadomienia na Telegram ze strategii
"SMI Strategy – surjithctly version". Nie wymaga TradingView ani dodatkowych
bibliotek – wystarczy Python 3.8+.

Uruchomienie:
  python smi_bot.py --test     # wysyła testowe powiadomienie na Telegram
  python smi_bot.py --status   # pokazuje aktualne SMI (porównaj z TradingView)
  python smi_bot.py --loop     # działa non stop, sprawdza po zamknięciu każdej świecy
  python smi_bot.py            # jedno sprawdzenie (np. dla GitHub Actions / crona)
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

# ============================ KONFIGURACJA ============================

# (źródło, symbol w źródle, nazwa w powiadomieniu)
# Źródło "yahoo" = Yahoo Finance (darmowe, bez klucza). Indeksy i surowce
# to kontrakty futures – najbliższe CFD-kom typu US100 / GOLD / WTI u brokerów.
SYMBOLS = [
    ("yahoo", "NQ=F",     "US100"),
    ("binance_fx", "PAXGUSDT", "GOLD"),   # PAXG = token złota 1:1 do XAUUSD spot
    ("yahoo", "CL=F",     "WTI"),
    ("yahoo", "NG=F",     "NATGAS"),
    ("yahoo", "JPY=X",    "USDJPY"),
    ("yahoo", "GBPJPY=X", "GBPJPY"),
    ("yahoo", "CHF=X",    "USDCHF"),
    ("yahoo", "EURCHF=X", "EURCHF"),
    ("yahoo", "^VIX",     "VIX"),
    ("yahoo", "ZW=F",     "WHEAT"),
    ("yahoo", "ZC=F",     "CORN"),
    ("yahoo", "CC=F",     "COCOA"),
    # ("binance", "BTCUSDT", "BTCUSDT"),   # krypto, gdyby kiedyś było potrzebne
]

# Interwały: 1m, 5m, 15m, 30m, 1h, 4h, 1d
INTERVALS = ["1h", "4h"]

# Świece 4h są składane z 1h. Godzina startu pierwszej świecy 4h wg czasu
# Nowego Jorku: 17 => świece 17,21,01,05,09,13 NY (standard forex / większość
# brokerów CFD na TradingView). Jeśli SMI na H4 różni się od Twojego wykresu,
# spróbuj 18 albo 0 (=> świece 00,04,08... UTC wtedy ustaw H4_ANCHOR_UTC = True).
H4_ANCHOR_NY_HOUR = 17
H4_ANCHOR_UTC = False

# Parametry SMI (jak w Pine)
LEN, R, SK = 14, 5, 3

# Trójkąty
UPPER, LOWER = 65, -65
# Reguły strategii
LONG_ENTRY, LONG_EXIT = -75, 60
SHORT_ENTRY, SHORT_EXIT = 75, -60

# Jakie powiadomienia wysyłać
ALERT_TRIANGLES = False  # pierwszy czerwony / zielony trójkąt
ALERT_ENTRIES = True     # wejście LONG / SHORT
ALERT_EXITS = False      # zamknięcie pozycji wg strategii

# True  = alert przy KAŻDYM przebiciu -75 (LONG) / +75 (SHORT), niezależnie od pozycji
# False = jak w strategii TradingView: wejście tylko, gdy nie ma otwartej pozycji
ENTRIES_IGNORE_POSITION = True

# Telegram – wpisz tutaj albo ustaw jako zmienne środowiskowe
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")      # token od @BotFather
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # Twoje chat id

STATE_FILE = os.getenv("STATE_FILE", "smi_state.json")

# ======================================================================

INTERVAL_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "4h": 14400, "1d": 86400}
YAHOO_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                  "1h": "60m", "1d": "1d"}
YAHOO_RANGE = {"1m": "5d", "5m": "30d", "15m": "60d", "30m": "60d",
               "1h": "365d", "1d": "5y"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) smi-bot"}


def http_get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


# ---------------------------- DANE ----------------------------

def fetch_binance(symbol, interval):
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": 1000})
    last_err = None
    for host in ("https://data-api.binance.vision", "https://api.binance.com"):
        try:
            data = http_get_json(f"{host}/api/v3/klines?{q}")
            break
        except Exception as e:  # noqa
            last_err = e
    else:
        raise RuntimeError(f"Binance: {last_err}")
    now_ms = time.time() * 1000
    return [{"t": int(k[0] / 1000), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])}
            for k in data if k[6] < now_ms]          # tylko zamknięte świece


def fetch_yahoo_raw(symbol, interval):
    q = urllib.parse.urlencode({"interval": YAHOO_INTERVAL[interval],
                                "range": YAHOO_RANGE[interval]})
    path = f"/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}"
    last_err = None
    for host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
        try:
            data = http_get_json(host + path)
            break
        except Exception as e:  # noqa
            last_err = e
            time.sleep(2)
    else:
        raise RuntimeError(f"Yahoo: {last_err}")
    res = data["chart"]["result"][0]
    ts = res.get("timestamp") or []
    qt = res["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(ts):
        h, l, c = qt["high"][i], qt["low"][i], qt["close"][i]
        if h is None or l is None or c is None:
            continue
        bars.append({"t": int(t), "h": float(h), "l": float(l), "c": float(c)})
    step = INTERVAL_SEC[interval]
    if step < 86400 and bars:
        # usuń "ucięte" punkty końca sesji (np. 22:59) – zostaw świece na regularnej siatce
        grid = Counter(b["t"] % step for b in bars).most_common(1)[0][0]
        bars = [b for b in bars if b["t"] % step == grid]
        # usuń dane z weekendu (pt 17:00 – nd 17:00 czasu Nowego Jorku)
        bars = [b for b in bars if not is_weekend_ny(b["t"])]
    return bars


def is_weekend_ny(t):
    d = datetime.fromtimestamp(t + ny_utc_offset_h(t) * 3600, timezone.utc)
    wd, hr = d.weekday(), d.hour   # pon=0 ... nd=6
    return (wd == 4 and hr >= 17) or wd == 5 or (wd == 6 and hr < 17)


def only_closed(bars, step):
    now = time.time()
    return [b for b in bars if b["t"] + step <= now]


def ny_utc_offset_h(t):
    """Przesunięcie Nowego Jorku względem UTC (-4 lato / -5 zima), bez zależności."""
    d = datetime.fromtimestamp(t, timezone.utc)
    y = d.year
    mar1 = datetime(y, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)
    nov1 = datetime(y, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7, hours=6)
    return -4 if dst_start <= d < dst_end else -5


def h4_bucket_start(t):
    step = 14400
    if H4_ANCHOR_UTC:
        return (t // step) * step
    off = ny_utc_offset_h(t) * 3600
    anchor = H4_ANCHOR_NY_HOUR * 3600
    local = t + off
    start_local = ((local - anchor) // step) * step + anchor
    return start_local - off


def resample_4h(bars_1h):
    out = []
    for b in bars_1h:
        k = h4_bucket_start(b["t"])
        if out and out[-1]["t"] == k:
            o = out[-1]
            o["h"] = max(o["h"], b["h"])
            o["l"] = min(o["l"], b["l"])
            o["c"] = b["c"]
        else:
            out.append({"t": k, "h": b["h"], "l": b["l"], "c": b["c"]})
    return only_closed(out, 14400)


_cache = {}


def fetch(source, symbol, interval):
    if source == "binance":
        return fetch_binance(symbol, interval)
    if source == "binance_fx":
        # dane 1h z Binance, bez weekendu (jak rynek spot), H4 składane jak na forexie
        key = (source, symbol)
        if key not in _cache:
            _cache[key] = [x for x in fetch_binance(symbol, "1h") if not is_weekend_ny(x["t"])]
        raw = _cache[key]
        return resample_4h(raw) if interval == "4h" else raw
    if source != "yahoo":
        raise RuntimeError(f"Nieznane źródło: {source}")
    base = "1h" if interval == "4h" else interval
    key = (symbol, base)
    if key not in _cache:
        _cache[key] = fetch_yahoo_raw(symbol, base)
    raw = _cache[key]
    if interval == "4h":
        return resample_4h(only_closed(raw, 3600))
    return only_closed(raw, INTERVAL_SEC[interval])


# ---------------------------- SMI (1:1 z Pine) ----------------------------

def rolling(src, n, fn):
    out = []
    for i in range(len(src)):
        if i < n - 1:
            out.append(None)
            continue
        w = src[i - n + 1:i + 1]
        out.append(None if any(v is None for v in w) else fn(w))
    return out


def ema(src, n):
    """Jak ta.ema w Pine: start od pierwszej dostępnej wartości."""
    alpha = 2 / (n + 1)
    out, prev = [], None
    for v in src:
        if v is None:
            prev = None
            out.append(None)
            continue
        prev = v if prev is None else alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def calc_smi(bars):
    high = [b["h"] for b in bars]
    low = [b["l"] for b in bars]
    close = [b["c"] for b in bars]
    hh = rolling(high, LEN, max)
    ll = rolling(low, LEN, min)
    mom, dmom = [], []
    for i in range(len(bars)):
        if hh[i] is None or ll[i] is None:
            mom.append(None)
            dmom.append(None)
        else:
            mom.append(close[i] - (hh[i] + ll[i]) / 2)
            dmom.append(hh[i] - ll[i])
    smom = ema(ema(mom, R), R)
    sdmom = ema(ema(dmom, R), R)
    raw = [None if a is None or b is None or b == 0 else 100 * (a / (b / 2))
           for a, b in zip(smom, sdmom)]
    return rolling(raw, SK, lambda w: sum(w) / len(w))


# ---------------------------- SYGNAŁY ----------------------------

def find_events(bars, smi):
    """Zwraca listę (indeks_świecy, typ) – symuluje strategię jak TradingView
    (zlecenie z zamknięcia świecy wykonuje się na otwarciu następnej)."""
    events = []
    pos, pending = 0, None
    for i, s in enumerate(smi):
        if pending is not None:
            pos, pending = pending, None
        prev = smi[i - 1] if i > 0 else None
        if s is None:
            continue
        if prev is not None:
            if s > UPPER and prev <= UPPER:
                events.append((i, "red"))
            if s < LOWER and prev >= LOWER:
                events.append((i, "green"))
        if ENTRIES_IGNORE_POSITION and prev is not None:
            if s < LONG_ENTRY <= prev:
                events.append((i, "long"))
            if s > SHORT_ENTRY >= prev:
                events.append((i, "short"))
        if pos == 0 and s < LONG_ENTRY:
            pending = 1
            if not ENTRIES_IGNORE_POSITION:
                events.append((i, "long"))
        elif pos == 0 and s > SHORT_ENTRY:
            pending = -1
            if not ENTRIES_IGNORE_POSITION:
                events.append((i, "short"))
        elif pos > 0 and s > LONG_EXIT:
            pending = 0
            events.append((i, "close_long"))
        elif pos < 0 and s < SHORT_EXIT:
            pending = 0
            events.append((i, "close_short"))
    return events, pos if pending is None else pending


EVENT_TEXT = {
    "red":         ("🟥▼", "CZERWONY trójkąt (SMI > 65)", ALERT_TRIANGLES),
    "green":       ("🟩▲", "ZIELONY trójkąt (SMI < -65)", ALERT_TRIANGLES),
    "long":        ("🟢", "WEJŚCIE LONG (SMI < -75)", ALERT_ENTRIES),
    "short":       ("🔴", "WEJŚCIE SHORT (SMI > 75)", ALERT_ENTRIES),
    "close_long":  ("✅", "ZAMKNIJ LONG (SMI > 60)", ALERT_EXITS),
    "close_short": ("✅", "ZAMKNIJ SHORT (SMI < -60)", ALERT_EXITS),
}


# ---------------------------- TELEGRAM ----------------------------

def notify(title, text):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print(f"(brak TELEGRAM_TOKEN / TELEGRAM_CHAT_ID) {title} | {text}")
        return
    try:
        body = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID,
                                       "text": f"{title}\n{text}"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=body, headers=UA)
        urllib.request.urlopen(req, timeout=30).read()
        print(f"WYSŁANO: {title} | {text}")
    except Exception as e:
        print(f"[Telegram] błąd: {e} | {title}", file=sys.stderr)


def fmt_time(t):
    """Czas otwarcia świecy w czasie polskim."""
    d = datetime.fromtimestamp(t, timezone.utc)
    y = d.year
    # czas letni w UE: ostatnia niedziela marca 01:00 UTC – ostatnia niedziela października 01:00 UTC
    def last_sunday(month):
        nxt = datetime(y, month + 1, 1, tzinfo=timezone.utc)
        last = nxt - timedelta(days=1)
        return last - timedelta(days=(last.weekday() + 1) % 7)
    start = last_sunday(3) + timedelta(hours=1)
    end = last_sunday(10) + timedelta(hours=1)
    off = 2 if start <= d < end else 1
    return (d + timedelta(hours=off)).strftime("%Y-%m-%d %H:%M")


def fmt_price(p):
    return f"{p:.5f}".rstrip("0").rstrip(".") if p < 10 else f"{p:.2f}"


# ---------------------------- LOGIKA ----------------------------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def check_all(status_only=False):
    _cache.clear()
    state = load_state()
    for source, symbol, name in SYMBOLS:
        for interval in INTERVALS:
            key = f"{source}:{symbol}:{interval}"
            try:
                bars = fetch(source, symbol, interval)
            except Exception as e:
                print(f"[{name} {interval}] błąd pobierania danych: {e}", file=sys.stderr)
                continue
            if len(bars) < LEN + 4 * R + SK + 2:
                print(f"[{name} {interval}] za mało danych ({len(bars)} świec)", file=sys.stderr)
                continue
            smi = calc_smi(bars)
            events, pos = find_events(bars, smi)
            last_t = bars[-1]["t"]
            if status_only:
                p = {1: "LONG", -1: "SHORT", 0: "brak"}[pos]
                print(f"{name:7} {interval:3} | świeca {fmt_time(last_t)} | "
                      f"close {fmt_price(bars[-1]['c']):>10} | SMI {smi[-1]:7.2f} | pozycja: {p}")
                continue
            seen = state.get(key)
            if seen is None:
                seen = bars[-2]["t"]  # pierwszy start: tylko ostatnia zamknięta świeca
            new_idx = [i for i, b in enumerate(bars) if b["t"] > seen][-5:]
            for i, kind in events:
                if i not in new_idx:
                    continue
                emoji, label, enabled = EVENT_TEXT[kind]
                if not enabled:
                    continue
                notify(f"{emoji} {name} {interval.upper()} – {label}",
                       f"Świeca: {fmt_time(bars[i]['t'])} (PL)\n"
                       f"Cena: {fmt_price(bars[i]['c'])} | SMI: {smi[i]:.2f}")
            state[key] = last_t
        time.sleep(0.5)  # grzecznie wobec Yahoo
    if not status_only:
        save_state(state)


def replay(day, send_all=False):
    """Wysyła sygnał(y) z danego dnia (data wg czasu polskiego, RRRR-MM-DD)."""
    found = []
    for source, symbol, name in SYMBOLS:
        for interval in INTERVALS:
            try:
                bars = fetch(source, symbol, interval)
            except Exception as e:
                print(f"[{name} {interval}] błąd pobierania danych: {e}", file=sys.stderr)
                continue
            smi = calc_smi(bars)
            events, _ = find_events(bars, smi)
            for i, kind in events:
                if fmt_time(bars[i]["t"])[:10] == day and EVENT_TEXT[kind][2]:
                    found.append((bars[i]["t"], name, interval, kind, bars[i]["c"], smi[i]))
        time.sleep(0.5)
    found.sort()
    print(f"Sygnały z {day}: {len(found)}")
    for t, name, interval, kind, c, v in found:
        print(f"  {fmt_time(t)} | {name} {interval} | {EVENT_TEXT[kind][1]} | cena {fmt_price(c)} | SMI {v:.2f}")
    if not found:
        notify("ℹ️ Historia", f"Brak sygnałów z dnia {day}.")
        return
    for t, name, interval, kind, c, v in (found if send_all else found[-1:]):
        emoji, label, _ = EVENT_TEXT[kind]
        notify(f"{emoji} [HISTORIA] {name} {interval.upper()} – {label}",
               f"Świeca: {fmt_time(t)} (PL)\nCena: {fmt_price(c)} | SMI: {v:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="działaj non stop")
    ap.add_argument("--status", action="store_true", help="pokaż aktualne SMI")
    ap.add_argument("--test", action="store_true", help="wyślij testowe powiadomienie")
    ap.add_argument("--replay", metavar="RRRR-MM-DD", help="wyślij ostatni sygnał z danego dnia")
    ap.add_argument("--all", action="store_true", help="z --replay: wyślij wszystkie sygnały z dnia")
    a = ap.parse_args()

    for iv in INTERVALS:
        if iv not in INTERVAL_SEC:
            sys.exit(f"Nieobsługiwany interwał: {iv}")
    if a.replay:
        replay(a.replay, a.all)
        return
    if a.test:
        notify("✅ SMI Bot działa", "To jest testowe powiadomienie.")
        return
    if a.status:
        check_all(status_only=True)
        return
    if not a.loop:
        check_all()
        return

    step = min(min(INTERVAL_SEC[i] for i in INTERVALS), 3600)
    print(f"SMI Bot uruchomiony: {[n for _, _, n in SYMBOLS]}, {INTERVALS}. Ctrl+C aby zakończyć.")
    while True:
        try:
            check_all()
        except Exception as e:
            print(f"Błąd: {e}", file=sys.stderr)
        now = time.time()
        wake = math.floor(now / step) * step + step + 60  # minutę po zamknięciu świecy
        time.sleep(max(5, wake - now))


if __name__ == "__main__":
    main()
