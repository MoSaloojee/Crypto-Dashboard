import streamlit as st
import streamlit_authenticator as stauth
import ccxt
import pandas as pd
import numpy as np
import datetime as dt
import plotly.graph_objects as go
import plotly.express as px

# ------------------------------
# Authentication setup
# ------------------------------

# Define credentials (plaintext pwd auto-hashed internally)
credentials = {
    "usernames": {
        "alice": {
            "name": "Alice",
            "password": "wonderland123"
        },
        "bob": {
            "name": "Bob",
            "password": "matrix456"
        }
    }
}

# Create authenticator instance
authenticator = stauth.Authenticate(
    credentials,
    "crypto_dashboard_cookie",  # Cookie name
    "abcdef",                   # Secret key
    cookie_expiry_days=1
)

# ------------------------------
# Login Widget (new syntax)
# ------------------------------
authenticator.login(location="main")

name = st.session_state.get("name")
authentication_status = st.session_state.get("authentication_status")
username = st.session_state.get("username")

if authentication_status is False:
    st.error("❌ Username/password is incorrect")
    st.stop()

elif authentication_status is None:
    st.warning("ℹ️ Please enter your username and password")
    st.stop()

# If login succeeded
st.success(f"✅ Welcome {name}!")

# ------------------------------
# Dashboard starts here
# ------------------------------

st.set_page_config(page_title="Crypto Dashboard", layout="wide")

st.title("📊 Crypto Dashboard with Multi‑Strategy Signals")
st.caption(f"Last Updated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- SETTINGS ---
exchange = ccxt.binance()
assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "SUI/USDT"]

# --- FUNCTIONS ---
def get_ohlcv(symbol, timeframe="1h", since=None, limit=1000):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    return macd, signal_line, hist

def compute_bollinger(series, window=20, num_std=2):
    sma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return sma, upper, lower

# --- SIDEBAR SETTINGS ---
st.sidebar.header("⚙️ Dashboard Settings")

if hasattr(st, "autorefresh"):
    st.sidebar.caption("⏱ Auto-refresh every 5 minutes")
    st.autorefresh(interval=5 * 60 * 1000, limit=None, key="refresh")
else:
    if st.sidebar.button("🔄 Refresh Now"):
        st.experimental_rerun()

timeframe_option = st.sidebar.selectbox("Sparkline timeframe", ["1w", "1m", "3m"], index=1)
chart_timeframe = st.sidebar.selectbox("Chart candle timeframe", ["1h", "4h", "1d"], index=0)
chart_assets = st.sidebar.multiselect("Select assets to chart", options=assets, default=assets)

# Indicator toggles
show_ma = st.sidebar.checkbox("Show Moving Averages (MA20 & MA50)", value=True)
show_bb = st.sidebar.checkbox("Show Bollinger Bands", value=True)
show_rsi = st.sidebar.checkbox("Show RSI", value=True)
show_macd = st.sidebar.checkbox("Show MACD", value=True)

# Flowchart strategy selector
strategy_choice = st.sidebar.selectbox(
    "Flowchart Strategy", ["Short", "Long", "Income"], index=0
)

filter_alerts_only = st.sidebar.checkbox("Show only assets with alerts", value=False)

# --- SUMMARY TABLE ---
timeframe_hours = {"1w": 24*7, "1m": 24*30, "3m": 24*90}
lookback_hours = timeframe_hours[timeframe_option]
limit = 1000

rows, alerts = [], []
signal_map = {s:{} for s in assets}  # {asset: {Short, Long, Income}}

for symbol in assets:
    ticker = exchange.fetch_ticker(symbol)
    current_price = ticker["last"]

    # Base dataframe for sparkline
    df_summary = get_ohlcv(symbol, "1h", limit=min(lookback_hours, 1000))
    cutoff = df_summary.iloc[-1]["time"] - pd.Timedelta(hours=lookback_hours)
    df_summary = df_summary[df_summary["time"] >= cutoff]

    def pct_change(period_hours):
        cutoff_period = df_summary.iloc[-1]["time"] - pd.Timedelta(hours=period_hours)
        subset = df_summary[df_summary["time"] >= cutoff_period]
        if not subset.empty:
            old_price = subset.iloc[0]["close"]
            return (current_price - old_price) / old_price * 100
        return None

    changes = {k: pct_change(v) for k,v in {"1h":1,"1d":24,"1w":24*7,"1m":24*30}.items()}

    # --- STRATEGY 1: SHORT TERM ---
    df_short = get_ohlcv(symbol, "1h", limit=60)
    df_short["rsi"] = compute_rsi(df_short["close"])
    df_short["bb_mid"], df_short["bb_upper"], df_short["bb_lower"] = compute_bollinger(df_short["close"])
    lst = df_short.iloc[-1]
    decision_short = "HOLD"
    if lst["rsi"] < 30 or lst["close"] < lst["bb_lower"]:
        decision_short = "BUY"
        alerts.append(f"{symbol} Short-Term: Oversold (RSI {lst['rsi']:.1f})")
    elif lst["rsi"] > 70 or lst["close"] > lst["bb_upper"]:
        decision_short = "SELL"
        alerts.append(f"{symbol} Short-Term: Overbought (RSI {lst['rsi']:.1f})")
    signal_map[symbol]["Short"] = decision_short

    # --- STRATEGY 2: LONG TERM ---
    df_long = get_ohlcv(symbol, "1d", limit=300)
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

    # --- STRATEGY 3: INCOME ---
    df_inc = get_ohlcv(symbol, "4h", limit=120)
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
df_display_filtered = df_display if not filter_alerts_only else df_display[
    (df_display["Decision (Short)"]!="HOLD")|(df_display["Decision (Long)"]!="HOLD")|(df_display["Decision (Income)"]!="HOLD")
]

# --- TABLE ---
st.subheader("📋 Market Overview with Multi‑Strategy Decisions")

def decision_style(val):
    if val == "BUY": return "background-color: rgba(0,255,0,0.25); color: green;"
    if val == "SELL": return "background-color: rgba(255,0,0,0.25); color: red;"
    if val == "BULLISH": return "background-color: rgba(0,255,0,0.15); color: green;"
    if val == "BEARISH": return "background-color: rgba(255,0,0,0.15); color: red;"
    if val == "HOLD": return "background-color: rgba(200,200,200,0.15); color: white;"
    return ""

st.dataframe(
    df_display_filtered.style.format({
        "Current Price": "${:,.2f}",
        "1h Change": "{:+.2f}%",
        "1d Change": "{:+.2f}%",
        "1w Change": "{:+.2f}%",
        "1m Change": "{:+.2f}%"
    }).applymap(
        lambda v: "color: green" if isinstance(v,(int,float)) and v>0
        else "color: red" if isinstance(v,(int,float)) and v<0
        else "",
        subset=["1h Change","1d Change","1w Change","1m Change"]
    ).applymap(decision_style, subset=["Decision (Short)","Decision (Long)","Decision (Income)"]
    ),
    column_config={f"Trend ({timeframe_option})": st.column_config.LineChartColumn()},
    use_container_width=True
)

# --- HEATMAP ---
st.subheader("🔥 Market Heatmap")
heatmap_df = df_display_filtered.melt(
    id_vars="Asset",
    value_vars=["1h Change","1d Change","1w Change","1m Change"],
    var_name="Timeframe", value_name="Change %"
)
fig_heat = px.density_heatmap(
    heatmap_df,x="Timeframe",y="Asset",z="Change %",
    color_continuous_scale=["red","white","green"],text_auto=True
)
fig_heat.update_layout(height=400,template="plotly_dark")
st.plotly_chart(fig_heat,use_container_width=True)

# --- ALERTS PANEL ---
st.subheader("🔔 Alerts")
if alerts:
    for alert in alerts: st.markdown(f"- {alert}")
else:
    st.success("✅ No strong short-term signals detected.")

# --- FLOWCHARTS ---
st.subheader("🧐 Decision Flowcharts (Dynamic)")

def draw_flowchart(signal="HOLD",asset="",strategy="Short"):
    nodes = {
        "Start":(0,1),"BUY":(-0.8,0.3),"SELL":(0.8,0.3),
        "HOLD":(0,0.3),"BULLISH":(-0.6,-0.2),"BEARISH":(0.6,-0.2)
    }
    colors = {k:"rgba(0,0,255,0.1)" for k in nodes}
    if signal=="BUY": colors["BUY"]="rgba(0,255,0,0.5)"
    elif signal=="SELL": colors["SELL"]="rgba(255,0,0,0.5)"
    elif signal=="BULLISH": colors["BULLISH"]="rgba(0,255,0,0.3)"
    elif signal=="BEARISH": colors["BEARISH"]="rgba(255,0,0,0.3)"
    elif signal=="HOLD": colors["HOLD"]="rgba(200,200,200,0.3)"

    fig=go.Figure()
    for text,(x,y) in nodes.items():
        fig.add_shape(type="rect",x0=x-0.35,x1=x+0.35,y0=y-0.1,y1=y+0.1,
                      line=dict(color="white"),fillcolor=colors[text])
        fig.add_annotation(x=x,y=y,text=text,showarrow=False,font=dict(size=12))
    arrows=[("Start","BUY"),("Start","SELL"),("Start","HOLD"),("HOLD","BULLISH"),("HOLD","BEARISH")]
    for a,b in arrows:
        x0,y0=nodes[a]; x1,y1=nodes[b]
        fig.add_annotation(x=x1,y=y1+0.08,ax=x0,ay=y0-0.08,
                           showarrow=True,arrowhead=2,arrowcolor="white")
    fig.update_layout(template="plotly_dark",height=400,
                      title=f"{asset} ({strategy} Strategy): {signal}",
                      xaxis=dict(visible=False),yaxis=dict(visible=False),
                      margin=dict(l=20,r=20,t=40,b=20))
    return fig

if chart_assets:
    cols=st.columns(len(chart_assets))
    for i,symbol in enumerate(chart_assets):
        sig=signal_map[symbol][strategy_choice]
        with cols[i]:
            fig_flow=draw_flowchart(sig,asset=symbol,strategy=strategy_choice)
            st.plotly_chart(fig_flow,use_container_width=True)

# --- CHARTING ---
st.subheader("📈 Detailed Charts")
for symbol in chart_assets:
    df_chart = get_ohlcv(symbol, chart_timeframe, limit=limit)
    if show_rsi: df_chart["rsi"] = compute_rsi(df_chart["close"])
    if show_macd: df_chart["macd"],df_chart["signal"],df_chart["hist"]=compute_macd(df_chart["close"])
    if show_bb: df_chart["bb_mid"],df_chart["bb_upper"],df_chart["bb_lower"]=compute_bollinger(df_chart["close"])

    fig_price=go.Figure()
    fig_price.add_trace(go.Candlestick(x=df_chart["time"],open=df_chart["open"],high=df_chart["high"],
                                       low=df_chart["low"],close=df_chart["close"],name="Candles"))
    if show_ma:
        df_chart["ma20"]=df_chart["close"].rolling(20).mean()
        df_chart["ma50"]=df_chart["close"].rolling(50).mean()
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["ma20"],mode="lines",name="MA20"))
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["ma50"],mode="lines",name="MA50"))
    if show_bb:
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["bb_upper"],mode="lines",name="BB Upper",
                                       line=dict(color="lightblue",dash="dot")))
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["bb_mid"],mode="lines",name="BB Mid",
                                       line=dict(color="blue",dash="dot")))
        fig_price.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["bb_lower"],mode="lines",name="BB Lower",
                                       line=dict(color="lightblue",dash="dot")))
    fig_price.update_layout(height=500,template="plotly_dark",
                            title=f"{symbol} Price",xaxis_rangeslider_visible=False)
    st.plotly_chart(fig_price,use_container_width=True)

    if show_rsi:
        fig_rsi=go.Figure()
        fig_rsi.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["rsi"],mode="lines",name="RSI"))
        fig_rsi.add_hline(y=70,line=dict(color="red",dash="dash"))
        fig_rsi.add_hline(y=30,line=dict(color="green",dash="dash"))
        fig_rsi.update_layout(height=250,template="plotly_dark",title=f"{symbol} RSI (14)",
                              yaxis=dict(range=[0,100]))
        st.plotly_chart(fig_rsi,use_container_width=True)

    if show_macd:
        fig_macd=go.Figure()
        fig_macd.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["macd"],mode="lines",name="MACD"))
        fig_macd.add_trace(go.Scatter(x=df_chart["time"],y=df_chart["signal"],mode="lines",name="Signal"))
        fig_macd.add_trace(go.Bar(x=df_chart["time"],y=df_chart["hist"],name="Histogram"))
        fig_macd.update_layout(height=250,template="plotly_dark",title=f"{symbol} MACD")
        st.plotly_chart(fig_macd,use_container_width=True)