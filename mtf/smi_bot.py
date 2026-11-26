#!/usr/bin/env python3
"""
SMI multi-timeframe bot -> Telegram.

Liczy Stochastic Momentum Index (te same wzory co strategia Pine
"SMI Strategy – surjithctly version") na interwałach M5, M30 i H1
i wysyła sygnał na Telegram, gdy:
  * LONG  – SMI < LONG_LEVEL  (domyślnie -70) jednocześnie na M5, M30 i H1
  * SHORT – SMI > SHORT_LEVEL (domyślnie  75) jednocześnie na M5, M30 i H1

Liczone są tylko ZAMKNIĘTE świece (bez repaintingu).
Stan (żeby nie wysyłać tego samego sygnału co 5 minut) trzymany jest w state.json.
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests


# ---------------------------------------------------------------- konfiguracja

def env_str(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value if value else default


def env_num(name: str, default: float, cast=float):
    value = os.getenv(name, "").strip()
    return cast(value) if value else default


# Format: NAZWA=GIEŁDA:TICKER (dane z TradingView). Ticker bez ":" = Yahoo Finance.
DEFAULT_SYMBOLS = (
    "US100=OANDA:NAS100USD,"
    "DE40=OANDA:DE30EUR,"
    "XAUUSD=OANDA:XAUUSD,"
    "WTI=OANDA:WTICOUSD,"
    "USDJPY=OANDA:USDJPY,"
    "USDCHF=OANDA:USDCHF"
)


def parse_symbols(raw: str) -> list:
    out = []
    for item in raw.replace("\n", ",").split(","):
        item = item.strip()
        if not item:
            continue
        name, _, ticker = item.partition("=")
        out.append((name.strip(), ticker.strip()) if ticker else (item, item))
    return out


SYMBOLS = parse_symbols(env_str("SYMBOLS", DEFAULT_SYMBOLS))

SMI_LENGTH = env_num("SMI_LENGTH", 14, int)
SMI_R = env_num("SMI_R", 5, int)
SMI_SMOOTH = env_num("SMI_SMOOTH", 3, int)

LONG_LEVEL = env_num("LONG_LEVEL", -70.0)
SHORT_LEVEL = env_num("SHORT_LEVEL", 75.0)
# Po sygnale kolejny sygnał w tym samym kierunku jest możliwy dopiero, gdy
# SMI na którymkolwiek interwale wyjdzie ze strefy o co najmniej tyle punktów.
REARM_MARGIN = env_num("REARM_MARGIN", 5.0)

DISPLAY_TZ = env_str("DISPLAY_TZ", "Europe/Warsaw")
SEND_TEST = env_str("SEND_TEST", "false").lower() == "true"
STATE_FILE = Path(env_str("STATE_FILE", "state.json"))

# (nazwa, interwał yfinance, ile historii pobrać, długość świecy w minutach)
TIMEFRAMES = [
    ("M5", "5m", "5d", 5),
    ("M30", "30m", "1mo", 30),
    ("H1", "60m", "3mo", 60),
]

MIN_BARS = 60


# ---------------------------------------------------------------- wskaźnik

def pine_ema(series: pd.Series, length: int) -> pd.Series:
    """EMA liczona jak ta.ema w Pine: start od SMA z pierwszych `length` wartości."""
    vals = series.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    alpha = 2.0 / (length + 1)
    prev = np.nan
    run = 0  # ile kolejnych wartości nie-NaN
    for i, v in enumerate(vals):
        if np.isnan(v):
            run = 0
            if not np.isnan(prev):
                out[i] = prev
            continue
        run += 1
        if np.isnan(prev):
            if run >= length:
                prev = vals[i - length + 1: i + 1].mean()
                out[i] = prev
        else:
            prev = alpha * v + (1 - alpha) * prev
            out[i] = prev
    return pd.Series(out, index=series.index)


def compute_smi(df: pd.DataFrame, length: int, r: int, smooth: int) -> pd.Series:
    hh = df["High"].rolling(length).max()
    ll = df["Low"].rolling(length).min()
    mid = (hh + ll) / 2

    mom = df["Close"] - mid
    dmom = hh - ll

    smom = pine_ema(pine_ema(mom, r), r)
    sdmom = pine_ema(pine_ema(dmom, r), r)

    smi_raw = pd.Series(np.where(sdmom != 0, 100 * (smom / (sdmom / 2)), 0.0), index=df.index)
    smi_raw[sdmom.isna()] = np.nan
    return smi_raw.rolling(smooth).mean()


# ---------------------------------------------------------------- dane

def _download(symbol: str, interval: str, period: str, minutes: int) -> pd.DataFrame:
    if ":" in symbol:  # TradingView
        import tv_feed
        return tv_feed.get_bars(symbol, minutes, n_bars=300)
    import yfinance as yf  # Yahoo Finance
    return yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False, prepost=False)


def fetch_closed_bars(symbol: str, interval: str, period: str, minutes: int) -> pd.DataFrame:
    last_err = None
    df = None
    for attempt in range(3):
        try:
            df = _download(symbol, interval, period, minutes)
            if df is not None and not df.empty:
                break
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(2 * (attempt + 1))
    if df is None or df.empty:
        raise RuntimeError(f"brak danych {interval} ({last_err or 'pusta odpowiedź'})")

    df = df.dropna(subset=["High", "Low", "Close"])
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

    # Odrzuć świecę, która jeszcze się nie zamknęła.
    now = pd.Timestamp.now(tz="UTC")
    if len(df) and df.index[-1].tz_convert("UTC") + pd.Timedelta(minutes=minutes) > now:
        df = df.iloc[:-1]

    if len(df) < MIN_BARS:
        raise RuntimeError(f"za mało świec {interval}: {len(df)}")
    return df


# ---------------------------------------------------------------- telegram

def send_telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chat_ids:
        print("[DRY RUN – brak TELEGRAM_TOKEN / TELEGRAM_CHAT_ID]\n" + text)
        return
    for chat_id in chat_ids:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram {resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------- stan

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Uszkodzony state.json – zaczynam od nowa")
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- logika

def fmt_time(ts: pd.Timestamp) -> str:
    return ts.tz_convert(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}".replace(",", " ")
    return f"{p:.3f}" if p >= 10 else f"{p:.5f}"


def build_message(kind: str, symbol: str, readings: dict) -> str:
    if kind == "LONG":
        head = f"🟢 LONG | {symbol}"
        cond = f"SMI < {LONG_LEVEL:g} na M5, M30 i H1"
    elif kind == "SHORT":
        head = f"🔴 SHORT | {symbol}"
        cond = f"SMI > {SHORT_LEVEL:g} na M5, M30 i H1"
    else:
        head = f"🧪 TEST | {symbol}"
        cond = f"Progi: LONG < {LONG_LEVEL:g}, SHORT > {SHORT_LEVEL:g}"

    smi_line = " | ".join(f"{tf}: {r['smi']:.2f}" for tf, r in readings.items())
    m5 = readings["M5"]
    return (
        f"{head}\n{cond}\n{smi_line}\n"
        f"Cena: {fmt_price(m5['close'])}\n"
        f"Świeca M5: {fmt_time(m5['time'])} ({DISPLAY_TZ})"
    )


def read_symbol(symbol: str) -> dict:
    readings = {}
    for name, interval, period, minutes in TIMEFRAMES:
        df = fetch_closed_bars(symbol, interval, period, minutes)
        smi = compute_smi(df, SMI_LENGTH, SMI_R, SMI_SMOOTH).dropna()
        if smi.empty:
            raise RuntimeError(f"nie da się policzyć SMI na {name}")
        readings[name] = {
            "smi": float(smi.iloc[-1]),
            "time": smi.index[-1],
            "close": float(df["Close"].loc[smi.index[-1]]),
        }
    return readings


def process_symbol(symbol: str, readings: dict, st: dict) -> None:
    smis = [r["smi"] for r in readings.values()]
    long_now = all(x < LONG_LEVEL for x in smis)
    short_now = all(x > SHORT_LEVEL for x in smis)
    stamp = fmt_time(readings["M5"]["time"])

    # LONG
    if long_now and st.get("long_armed", True):
        send_telegram(build_message("LONG", symbol, readings))
        st["long_armed"] = False
        st["last_long"] = stamp
        print(f"[{symbol}] >>> wysłano LONG")
    elif not st.get("long_armed", True) and any(x > LONG_LEVEL + REARM_MARGIN for x in smis):
        st["long_armed"] = True

    # SHORT
    if short_now and st.get("short_armed", True):
        send_telegram(build_message("SHORT", symbol, readings))
        st["short_armed"] = False
        st["last_short"] = stamp
        print(f"[{symbol}] >>> wysłano SHORT")
    elif not st.get("short_armed", True) and any(x < SHORT_LEVEL - REARM_MARGIN for x in smis):
        st["short_armed"] = True

    st.setdefault("long_armed", True)
    st.setdefault("short_armed", True)


def main() -> int:
    state = load_state()
    before = json.dumps(state, sort_keys=True)
    errors = 0

    for symbol, ticker in SYMBOLS:
        try:
            readings = read_symbol(ticker)
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"[{symbol}] BŁĄD danych: {e}")
            continue

        print(f"[{symbol}] " + " | ".join(
            f"{tf} {r['smi']:7.2f} @ {fmt_time(r['time'])}" for tf, r in readings.items()
        ))

        try:
            if SEND_TEST:
                send_telegram(build_message("TEST", symbol, readings))
            else:
                process_symbol(symbol, readings, state.setdefault(symbol, {}))
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"[{symbol}] BŁĄD wysyłki: {e}")

    if json.dumps(state, sort_keys=True) != before:
        save_state(state)

    # Błąd zwracamy tylko, gdy nic się nie udało – GitHub wyśle wtedy maila.
    return 1 if errors and errors >= len(SYMBOLS) else 0


if __name__ == "__main__":
    sys.exit(main())
