"""
strategy.py  -  ALL trading logic and settings live in this file.

Edit this file to change how signals are generated. The Streamlit
frontend (app.py) only displays whatever this module produces.

Public API used by app.py:
    INDICES                     -> dict of index name -> Yahoo symbol
    normalize_ticker(text)      -> str
    is_market_open(now=None)    -> bool
    fetch_candles(symbol)       -> DataFrame of COMPLETED 1-min candles
    compute_signals(candles)    -> same DataFrame + PrevClose, Signal columns
    POLL_INTERVAL_SECONDS       -> refresh rate used by the frontend
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

# =====================================================================
# SETTINGS
# =====================================================================

TIMEZONE = "Asia/Kolkata"
DEFAULT_SUFFIX = ".NS"            # appended if ticker has no .NS / .BO

INTERVAL = "1m"
HISTORY_PERIOD = "5d"             # >1 day so the first candle of today
                                  # can be compared with yesterday's close
POLL_INTERVAL_SECONDS = 20
CANDLE_GRACE_SECONDS = 15         # wait this long after a minute ends
                                  # before trusting the candle

MARKET_OPEN = (9, 15)             # IST (hour, minute)
MARKET_CLOSE = (15, 30)

TICK_SIZE = 0.05                  # stocks: prices rounded to this before comparing
TICK_SIZE_INDEX = 0.01            # indices: values are quoted to 2 decimals

# Indices offered in the frontend dropdown: display name -> Yahoo symbol.
# Add or remove entries here and the dropdown updates automatically.
INDICES = {
    "Nifty 50": "^NSEI",
    "Sensex": "^BSESN",
    "Bank Nifty": "^NSEBANK",
    "Nifty IT": "^CNXIT",
    "Nifty Next 50": "^NSMIDCP",
}

# What to emit when a condition is met. Swap these to reverse the strategy.
#   Conventional (trend):       open==low  & gap up   -> BUY
#                               open==high & gap down -> SELL
#   Reversal (fade):            set LOW -> "SELL" and HIGH -> "BUY"
SIGNAL_WHEN_OPEN_EQUALS_LOW = "BUY"
SIGNAL_WHEN_OPEN_EQUALS_HIGH = "SELL"



REQUIRE_GAP = True                # open must be above/below previous close
SKIP_FLAT_CANDLES = True          # ignore candles where High == Low
REQUIRE_SAME_SESSION = False      # False: first candle of the day is compared
                                  # with the previous day's last close


# =====================================================================
# HELPERS
# =====================================================================

def normalize_ticker(text: str) -> str:
    symbol = text.strip().upper()
    if symbol.startswith("^"):          # index symbols take no suffix
        return symbol
    if symbol and not symbol.endswith((".NS", ".BO")):
        symbol += DEFAULT_SUFFIX
    return symbol


def tick_size_for(symbol: str) -> float:
    return TICK_SIZE_INDEX if symbol.startswith("^") else TICK_SIZE


def is_market_open(now: pd.Timestamp | None = None) -> bool:
    now = now or pd.Timestamp.now(tz=TIMEZONE)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1],
                        second=0, microsecond=0)
    end = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1],
                      second=0, microsecond=0)
    return start <= now < end


def _tick(price: float, tick: float) -> float:
    """Round a price to the nearest tick so comparisons are exact."""
    return round(round(price / tick) * tick, 4)


# =====================================================================
# DATA
# =====================================================================

def fetch_candles(symbol: str) -> pd.DataFrame:
    """Download 1-minute candles and return only completed ones."""
    candles = yf.Ticker(symbol).history(
        period=HISTORY_PERIOD,
        interval=INTERVAL,
        auto_adjust=False,
        prepost=False,
        timeout=15,
    )

    if candles.empty:
        raise ValueError(
            "No candle data returned. Check the symbol, market hours, "
            "connection, or data availability."
        )

    if candles.index.tz is None:
        candles.index = candles.index.tz_localize(TIMEZONE)
    else:
        candles.index = candles.index.tz_convert(TIMEZONE)

    ohlc = ["Open", "High", "Low", "Close"]
    candles = candles.dropna(subset=ohlc).sort_index()
    candles = candles[~candles.index.duplicated(keep="last")]

    # A candle's timestamp is its START. Keep only candles whose minute
    # ended at least CANDLE_GRACE_SECONDS ago.
    cutoff = pd.Timestamp.now(tz=TIMEZONE) - pd.Timedelta(seconds=CANDLE_GRACE_SECONDS)
    completed = candles[(candles.index + pd.Timedelta(minutes=1)) <= cutoff]

    cols = ohlc + (["Volume"] if "Volume" in completed.columns else [])
    return completed[cols]


# =====================================================================
# STRATEGY  (edit this part to change the rules)
# =====================================================================

def generate_signal(candle: pd.Series, previous_close: float,
                    tick: float = TICK_SIZE) -> str:
    """
    Return "BUY", "SELL" or "HOLD" for one completed candle.

    candle          : row with Open / High / Low / Close (/ Volume)
    previous_close  : close of the candle before it (NaN if unavailable)
    tick            : tick size used to round prices before comparing
    """
    if pd.isna(previous_close):
        return "HOLD"

    o = _tick(float(candle["Open"]), tick)
    h = _tick(float(candle["High"]), tick)
    l = _tick(float(candle["Low"]), tick)
    prev = _tick(float(previous_close), tick)

    if SKIP_FLAT_CANDLES and h == l:
        return "HOLD"

    open_equals_low = o == l
    open_equals_high = o == h

    gap_up = o > prev
    gap_down = o < prev

    if open_equals_low and (gap_up or not REQUIRE_GAP):
        return SIGNAL_WHEN_OPEN_EQUALS_LOW

    if open_equals_high and (gap_down or not REQUIRE_GAP):
        return SIGNAL_WHEN_OPEN_EQUALS_HIGH

    return "HOLD"


def compute_signals(candles: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    """Add PrevClose and Signal columns to every candle."""
    tick = tick_size_for(symbol)
    df = candles.copy()
    df["PrevClose"] = df["Close"].shift(1)

    if REQUIRE_SAME_SESSION:
        dates = pd.Series(df.index.date, index=df.index)
        new_session = dates != dates.shift(1)
        df.loc[new_session, "PrevClose"] = float("nan")

    df["Signal"] = [
        generate_signal(row, row["PrevClose"], tick) for _, row in df.iterrows()
    ]
    return df
