"""
Minimalny klient danych TradingView (websocket, bez logowania).

Pobiera świece OHLC tak samo jak wykres TradingView, w trybie anonimowym
(darmowym). Nie wymaga konta ani hasła. To nieoficjalny interfejs –
TradingView może go zmienić.
"""

import json
import random
import re
import string
import time

import pandas as pd
from websocket import create_connection

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
HEADERS = ["Origin: https://data.tradingview.com"]
_SPLIT = re.compile(r"~m~\d+~m~")
_ERRORS = {"symbol_error", "series_error", "critical_error", "protocol_error"}


def _session(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def _wrap(payload: str) -> str:
    return f"~m~{len(payload)}~m~{payload}"


def _msg(func: str, params: list) -> str:
    return _wrap(json.dumps({"m": func, "p": params}, separators=(",", ":")))


def get_bars(symbol: str, interval_minutes: int, n_bars: int = 300, timeout: float = 25) -> pd.DataFrame:
    """
    symbol: 'GIEŁDA:TICKER', np. 'OANDA:XAUUSD'
    interval_minutes: 5, 30, 60 ...
    Zwraca DataFrame (Open, High, Low, Close, Volume) z indeksem UTC = czas otwarcia świecy.
    Ostatnia świeca może być jeszcze otwarta.
    """
    ws = create_connection(WS_URL, header=HEADERS, timeout=timeout)
    try:
        cs = _session("cs_")
        qs = _session("qs_")

        def send(func, params):
            ws.send(_msg(func, params))

        send("set_auth_token", ["unauthorized_user_token"])
        send("chart_create_session", [cs, ""])
        send("quote_create_session", [qs])
        send("quote_set_fields", [qs, "lp", "ch", "chp", "update_mode"])
        send("quote_add_symbols", [qs, symbol, {"flags": ["force_permission"]}])
        send("quote_fast_symbols", [qs, symbol])
        send("resolve_symbol", [cs, "symbol_1",
                                "=" + json.dumps({"symbol": symbol, "adjustment": "splits"})])
        send("create_series", [cs, "s1", "s1", "symbol_1", str(interval_minutes), n_bars])
        send("switch_timezone", [cs, "Etc/UTC"])

        bars: dict = {}
        done = False
        deadline = time.time() + timeout
        while not done and time.time() < deadline:
            raw = ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            for part in _SPLIT.split(raw):
                if not part:
                    continue
                if part.startswith("~h~"):          # heartbeat – odsyłamy
                    ws.send(_wrap(part))
                    continue
                try:
                    msg = json.loads(part)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                m = msg.get("m")
                if m in ("timescale_update", "du"):
                    p = msg.get("p", [])
                    series = p[1].get("s1", {}).get("s", []) if len(p) > 1 and isinstance(p[1], dict) else []
                    for b in series:
                        v = b.get("v", [])
                        if len(v) >= 5:
                            bars[v[0]] = v[:6] if len(v) >= 6 else v[:5] + [0.0]
                elif m == "series_completed":
                    done = True
                elif m in _ERRORS:
                    raise RuntimeError(f"TradingView {m}: {msg.get('p')}")
        if not bars:
            raise RuntimeError(f"brak świec z TradingView dla {symbol} ({interval_minutes}m)")
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass

    rows = [bars[k] for k in sorted(bars)]
    df = pd.DataFrame(rows, columns=["time", "Open", "High", "Low", "Close", "Volume"])
    df.index = pd.to_datetime(df.pop("time"), unit="s", utc=True)
    return df.astype(float)
