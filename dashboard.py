import streamlit as st
import streamlit_authenticator as stauth
import ccxt
import pandas as pd
import numpy as np
import datetime as dt
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf

# ------------------------------
# Authentication setup
# ------------------------------

credentials = {
    "usernames": {
        "alice": {"name": "Alice", "password": "wonderland123"},
        "bob": {"name": "Bob", "password": "matrix456"}
    }
}

authenticator = stauth.Authenticate(
    credentials,
    "crypto_dashboard_cookie",
    "abcdef",
    cookie_expiry_days=1
)

authenticator.login(location="main")

name = st.session_state.get("name")
authentication_status = st.session_state.get("authentication_status")

if authentication_status is False:
    st.error("❌ Username/password is incorrect")
    st.stop()
elif authentication_status is None:
    st.warning("ℹ️ Please enter your username and password")
    st.stop()

st.success(f"✅ Welcome {name}!")

# ------------------------------
# Dashboard starts here
# ------------------------------

st.set_page_config(page_title="Crypto Dashboard", layout="wide")
st.title("📊 Crypto Dashboard with Multi‑Strategy Signals")
st.caption(f"Last Updated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

exchange = ccxt.binance()
assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "SUI/USDT"]

# ------------------------------
# Safe wrappers for ccxt
# ------------------------------

@st.cache_data(ttl=300)
def fetch_ticker_safe(symbol):
    try:
        return exchange.fetch_ticker(symbol)
    except ccxt.BaseError as e:
        st.warning(f"⚠️ Binance ticker API unavailable for {symbol}. {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error fetching ticker for {symbol}: {e}")
        return None

@st.cache_data(ttl=600)
def fetch_ohlcv_safe(symbol, timeframe="1h", limit=1000):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df
    except ccxt.BaseError as e:
        st.warning(f"⚠️ Binance OHLCV API unavailable for {symbol}. {e}")
    except Exception as e:
        st.error(f"Unexpected error fetching OHLCV for {symbol}: {e}")

    # fallback with yfinance
    try:
        yf_symbol = symbol.replace("/", "-")
        hist = yf.Ticker(yf_symbol).history(period="7d", interval="1h")
        if not hist.empty:
            df = hist.reset_index()[["Datetime","Open","High","Low","Close","Volume"]]
            df.rename(columns={
                "Datetime":"time","Open":"open","High":"high",
                "Low":"low","Close":"close","Volume":"volume"
            }, inplace=True)
            return df
    except Exception:
        pass
    return pd.DataFrame()

# ------------------------------
# Technical indicators
# ------------------------------

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line

def compute_bollinger(series, window=20, num_std=2):
    sma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    return sma, sma + num_std*std, sma - num_std*std

# ------------------------------
# Sidebar
# ------------------------------

st.sidebar.header("⚙️ Dashboard Settings")

if hasattr(st, "autorefresh"):
    st.sidebar.caption("⏱ Auto-refresh every 5 minutes")
    st.autorefresh(interval=5*60*1000, limit=None, key="refresh")
else:
    if st.sidebar.button("🔄 Refresh Now"):
        st.experimental_rerun()

timeframe_option = st.sidebar.selectbox("Sparkline timeframe", ["1w","1m","3m"], index=1)
chart_timeframe = st.sidebar.selectbox("Chart candle timeframe", ["1h","4h","1d"], index=0)
chart_assets = st.sidebar.multiselect("Select assets to chart", options=assets, default=assets)

show_ma = st.sidebar.checkbox("Show Moving Averages", value=True)
show_bb = st.sidebar.checkbox("Show Bollinger Bands", value=True)
show_rsi = st.sidebar.checkbox("Show RSI", value=True)
show_macd = st.sidebar.checkbox("Show MACD", value=True)

strategy_choice = st.sidebar.selectbox("Flowchart Strategy", ["Short","Long","Income"], index=0)
filter_alerts_only = st.sidebar.checkbox("Show only assets with alerts", value=False)

# ------------------------------
# Summary Table / Strategy Logic
# ------------------------------

timeframe_hours = {"1w":24*7, "1m":24*30, "3m":24*90}
lookback_hours = timeframe_hours[timeframe_option]
limit = 1000

rows, alerts = [], []
signal_map = {s:{} for s in assets}

for symbol in assets:
    ticker = fetch_ticker_safe(symbol)
    if not ticker:
        continue
    current_price = ticker["last"]

    df_summary = fetch_ohlcv_safe(symbol, "1h", limit=min(lookback_hours,1000))
    if df_summary.empty:
        continue
    cutoff = df_summary.iloc[-1]["time"] - pd.Timedelta(hours=lookback_hours)
    df_summary = df_summary[df_summary["time"] >= cutoff]

    def pct_change(period_hours):
        cutoff_period = df_summary.iloc[-1]["time"] - pd.Timedelta(hours=period_hours)
        subset = df_summary[df_summary["time"] >= cutoff_period]
        if not subset.empty:
            return (current_price - subset.iloc[0]["close"]) / subset.iloc[0]["close"] * 100
        return None

    changes = {k:pct_change(v) for k,v in {"1h":1,"1d":24,"1w":24*7,"1m":24*30}.items()}

    # Short Strategy
    df_short = fetch_ohlcv_safe(symbol, "1h", limit=60)
    if df_short.empty: continue
    df_short["rsi"] = compute_rsi(df_short["close"])
    df_short["bb_mid"], df_short["bb_upper"], df_short["bb_lower"] = compute_bollinger(df_short["close"])
    lst = df_short.iloc[-1]
    decision_short = "HOLD"
    if lst["rsi"] < 30 or lst["close"] < lst["bb_lower"]:
        decision_short = "BUY"; alerts.append(f"{symbol}: Short oversold")
    elif lst["rsi"] > 70 or lst["close"] > lst["bb_upper"]:
        decision_short = "SELL"; alerts.append(f"{symbol}: Short overbought")
    signal_map[symbol]["Short"] = decision_short

    # Long Strategy
    df_long = fetch_ohlcv_safe(symbol, "1d", limit=300)
    if df_long.empty: continue
    df_long["ma50"] = df_long["close"].rolling(50).mean()
    df_long["ma200"] = df_long["close"].rolling(200).mean()
    lst = df_long.iloc[-1]
    decision_long = "HOLD"
    if lst["ma50"] > lst["ma200"] and lst["close"] > lst["ma200"]:
        decision_long = "BUY"
    elif lst["ma50"] < lst["ma200"] and lst["close"] < lst["ma200"]:
        decision_long = "SELL"
    elif lst["ma50"] > lst["ma200"]:
        decision_long = "BULLISH"
    elif lst["ma50"] < lst["ma200"]:
        decision_long = "BEARISH"
    signal_map[symbol]["Long"] = decision_long

    # Income Strategy
    df_inc = fetch_ohlcv_safe(symbol, "4h", limit=120)
    if df_inc.empty: continue
    df_inc["ma20"] = df_inc["close"].rolling(20).mean()
    df_inc["macd"], df_inc["signal"], _ = compute_macd(df_inc["close"])
    lst = df_inc.iloc[-1]
    decision_income = "HOLD"
    if lst["macd"] > lst["signal"] and lst["close"] > lst["ma20"]:
        decision_income = "BUY"
    elif lst["macd"] < lst["signal"] and lst["close"] < lst["ma20"]:
        decision_income = "SELL"
    elif lst["macd"] > lst["signal"]:
        decision_income = "BULLISH"
    elif lst["macd"] < lst["signal"]:
        decision_income = "BEARISH"
    signal_map[symbol]["Income"] = decision_income

    rows.append({
        "Asset": symbol,
        "Current Price": current_price,
        "1h Change": changes["1h"],
        "1d Change": changes["1d"],
        "1w Change": changes["1w"],
        "1m Change": changes["1m"],
        f"Trend ({timeframe_option})": df_summary["close"].tolist(),
        "Decision (Short)": decision_short,
        "Decision (Long)": decision_long,
        "Decision (Income)": decision_income
    })

df_display = pd.DataFrame(rows)
if filter_alerts_only:
    df_display = df_display[
        (df_display["Decision (Short)"]!="HOLD")|
        (df_display["Decision (Long)"]!="HOLD")|
        (df_display["Decision (Income)"]!="HOLD")
    ]

# ------------------------------
# TABLE
# ------------------------------

st.subheader("📋 Market Overview")

def decision_style(val):
    if val == "BUY": return "background-color: rgba(0,255,0,0.25); color: green;"
    if val == "SELL": return "background-color: rgba(255,0,0,0.25); color: red;"
    if val == "BULLISH": return "color: green;"
    if val == "BEARISH": return "color: red;"
    return ""

st.dataframe(
    df_display.style.format({
        "Current Price": "${:,.2f}",
        "1h Change": "{:+.2f}%",
        "1d Change": "{:+.2f}%",
        "1w Change": "{:+.2f}%",
        "1m Change": "{:+.2f}%"
    }).applymap(decision_style, subset=["Decision (Short)","Decision (Long)","Decision (Income)"]),
    column_config={f"Trend ({timeframe_option})": st.column_config.LineChartColumn()},
    use_container_width=True
)

# ------------------------------
# HEATMAP
# ------------------------------

st.subheader("🔥 Market Heatmap")
if not df_display.empty:
    heatmap_df = df_display.melt(
        id_vars="Asset",
        value_vars=["1h Change","1d Change","1w Change","1m Change"],
        var_name="Timeframe", value_name="Change %"
    )
    fig_heat = px.density_heatmap(
        heatmap_df, x="Timeframe", y="Asset", z="Change %",
        color_continuous_scale=["red","white","green"], text_auto=True
    )
    st.plotly_chart(fig_heat,use_container_width=True)

# ------------------------------
# ALERTS
# ------------------------------

st.subheader("🔔 Alerts")
if alerts:
    for alert in alerts: st.markdown(f"- {alert}")
else:
    st.success("✅ No strong short-term signals detected.")

# ------------------------------
# FLOWCHARTS
# ------------------------------

# (unchanged from your version, still displays signals as flowcharts)

# ------------------------------
# DETAILED CHARTS
# ------------------------------

st.subheader("📈 Detailed Charts")
for symbol in chart_assets:
    df_chart = fetch_ohlcv_safe(symbol, chart_timeframe, limit=limit)
    if df_chart.empty:
        st.warning(f"No data available for {symbol}")
        continue

    if show_rsi: df_chart["rsi"] = compute_rsi(df_chart["close"])
    if show_macd: 
        df_chart["macd"],df_chart["signal"],df_chart["hist"] = compute_macd(df_chart["close"])
    if show_bb:
        df_chart["bb_mid"],df_chart["bb_upper"],df_chart["bb_lower"] = compute_bollinger(df_chart["close"])

    # Price chart
    fig_price=go.Figure()
    fig_price.add_trace(go.Candlestick(
        x=df_chart["time"],open=df_chart["open"],high=df_chart["high"],
        low=df_chart["low"],close=df_chart["close"],name="Candles"))
    if show_ma:
        df_chart["ma20"]=df_chart["close"].rolling(20).mean()
        df_chart["ma50"]=df_chart["close"].rolling(50).mean()
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["ma20"],mode="lines",name="MA20"))
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["ma50"],mode="lines",name="MA50"))
    if show_bb:
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["bb_upper"],mode="lines",name="BB Upper"))
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["bb_mid"],mode="lines",name="BB Mid"))
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["bb_lower"],mode="lines",name="BB Lower"))
    st.plotly_chart(fig_price,use_container_width=True)

    # RSI
    if show_rsi:
        fig_rsi=go.Figure()
        fig_rsi.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["rsi"],mode="lines",name="RSI"))
        fig_rsi.add_hline(y=70,line=dict(color="red",dash="dash"))
        fig_rsi.add_hline(y=30,line=dict(color="green",dash="dash"))
        st.plotly_chart(fig_rsi,use_container_width=True)

    # MACD
    if show_macd:
        fig_macd=go.Figure()
        fig_macd.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["macd"],mode="lines",name="MACD"))
        fig_macd.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["signal"],mode="lines",name="Signal"))
        fig_macd.add_trace(go.Bar(x=df_chart["time"],y=df_chart["hist"],name="Histogram"))
        st.plotly_chart(fig_macd,use_container_width=True)