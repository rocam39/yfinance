"""
app.py - Streamlit frontend. Contains no trading logic.
Run with:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

import strategy as S

st.set_page_config(page_title="Candle Signal Monitor", layout="wide")
st.title("1-Minute Candle Signal Monitor")

# ---------------- Sidebar ----------------

with st.sidebar:
    ticker_input = st.text_input("NSE/BSE ticker", value="RELIANCE.NS",
                                 help="e.g. RELIANCE.NS or RELIANCE.BO")
    running = st.toggle("Start monitoring", value=False)
    rows_to_show = st.slider("Candles to display", 10, 200, 40)
    st.caption(f"Refreshes every {S.POLL_INTERVAL_SECONDS}s. "
               "Strategy rules and settings are in strategy.py.")

symbol = S.normalize_ticker(ticker_input)

# ---------------- Session state ----------------

state = st.session_state
state.setdefault("active_symbol", None)
state.setdefault("seen", set())
state.setdefault("log", [])


def reset_for(sym):
    state.active_symbol = sym
    state.seen = set()
    state.log = []


def color_signal(col):
    colors = {"BUY": "background-color: #1b5e20; color: white",
              "SELL": "background-color: #b71c1c; color: white"}
    return [colors.get(v, "") for v in col]


# ---------------- Live monitor ----------------

@st.fragment(run_every=S.POLL_INTERVAL_SECONDS)
def monitor(sym: str):
    try:
        candles = S.fetch_candles(sym)
        df = S.compute_signals(candles)
    except Exception as exc:
        st.error(f"Data error: {exc}. Retrying in {S.POLL_INTERVAL_SECONDS}s.")
        return

    if df.empty:
        st.info("No completed candles available yet.")
        return

    # First load after start: treat existing candles as baseline so
    # stale historical signals are not reported as new.
    if not state.seen:
        state.seen = set(df.index)
        st.toast(f"Baseline set at {df.index[-1].strftime('%H:%M')}")
    else:
        new_rows = df[~df.index.isin(state.seen)]
        for ts, row in new_rows.iterrows():
            state.seen.add(ts)
            if row["Signal"] != "HOLD":
                state.log.insert(0, {
                    "Time": ts.strftime("%Y-%m-%d %H:%M"),
                    "Symbol": sym,
                    "Signal": row["Signal"],
                    "Open": row["Open"], "High": row["High"],
                    "Low": row["Low"], "Close": row["Close"],
                })
                st.toast(f"{row['Signal']} {sym} @ {row['Open']:.2f}")

    last = df.iloc[-1]
    market = "Open" if S.is_market_open() else "Closed"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Symbol", sym)
    c2.metric("Market", market)
    c3.metric("Last candle", df.index[-1].strftime("%H:%M"))
    c4.metric("Last signal", last["Signal"])

    st.subheader("Recent candles")
    view = df.tail(rows_to_show).iloc[::-1].copy()
    view.index = view.index.strftime("%Y-%m-%d %H:%M")
    st.dataframe(
        view.style.apply(color_signal, subset=["Signal"])
            .format({c: "{:.2f}" for c in
                     ["Open", "High", "Low", "Close", "PrevClose"]},
                    na_rep="-"),
        use_container_width=True,
    )

    st.subheader("New BUY/SELL signals since monitoring started")
    if state.log:
        st.dataframe(pd.DataFrame(state.log), use_container_width=True,
                     hide_index=True)
    else:
        st.caption("None yet.")


if not symbol:
    st.warning("Enter a ticker.")
elif running:
    if state.active_symbol != symbol:
        reset_for(symbol)
    monitor(symbol)
else:
    state.active_symbol = None
    state.seen = set()
    st.info("Toggle **Start monitoring** in the sidebar to begin.")
