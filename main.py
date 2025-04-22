import pandas as pd
import ta
import alpaca_trade_api as tradeapi
import requests
import time
import logging
from datetime import datetime, timedelta

# === API-Zugang ===
TELEGRAM_TOKEN = '7883966444:AAHJfeC0EnX-Tjd1H5NPSM7zCXfntg_W2Bs'
TELEGRAM_CHAT_ID = '344603231'
API_KEY = 'PK7C24MFH67A20OUM22L'
API_SECRET = 'rv7i3NAZzv9Tw8P9swBpaOcKP4omX6IJAKJGbgTY'
BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

# === Einstellungen ===
investment_per_week = 10000
position_size = 2000
weekly_profit = 0
weekly_investment = 0
positions = {}
start_of_week = datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())

# === Logging ===
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s | %(message)s')
def log(msg):
    print(msg)
    logging.info(msg)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

# === Top 100 volatilste Aktien (Finviz, manuell eingebaut) ===
tickers = [
    'GME', 'MARA', 'RIOT', 'CVNA', 'NVDA', 'TSLA', 'AMD', 'UPST', 'AI', 'PATH',
    'BIDU', 'BILI', 'RBLX', 'COIN', 'AFRM', 'PLTR', 'XPEV', 'NIO', 'LVS', 'FSLR',
    'LCID', 'NKLA', 'RIVN', 'BABA', 'JD', 'SHOP', 'SQ', 'ROKU', 'NET', 'ZI',
    'CRWD', 'ZS', 'SNOW', 'OKTA', 'DDOG', 'DOCU', 'UBER', 'LYFT', 'TNDM', 'ENPH',
    'RUN', 'SPWR', 'SILK', 'BLNK', 'CHPT', 'BE', 'SPCE', 'ASTR', 'BB', 'BBBY',
    'AMC', 'APE', 'BYND', 'DNUT', 'CVS', 'ROIV', 'CLSK', 'DNA', 'IONQ', 'SOUN',
    'TSM', 'INTC', 'QCOM', 'MU', 'MRNA', 'PFE', 'BNTX', 'VRTX', 'REGN', 'BIIB',
    'WOLF', 'SMCI', 'AVGO', 'AMZN', 'AAPL', 'META', 'GOOGL', 'MSFT', 'CRM',
    'PANW', 'FTNT', 'ETSY', 'EBAY', 'W', 'FVRR', 'TGT', 'HD', 'NKE', 'DIS',
    'WBD', 'PARA', 'SBUX', 'MCD', 'KO', 'PEP', 'T', 'VZ', 'BA', 'LMT', 'GE'
]

# === Sektor-Zuordnung (vereinfacht) ===
sectors = {sym: 'Tech' for sym in tickers}
sectors.update({'MARA': 'Crypto', 'RIOT': 'Crypto', 'COIN': 'Crypto', 'GME': 'Retail', 'AMC': 'Media'})

def analyze(symbol):
    try:
        bars = api.get_bars(symbol, tradeapi.TimeFrame.Day, limit=100).df
        if bars.empty or 'close' not in bars.columns:
            return None
        bars["rsi"] = ta.momentum.RSIIndicator(bars["close"], window=14).rsi()
        bars["ma200"] = bars["close"].rolling(200).mean()
        bars["momentum"] = bars["close"].pct_change(20)
        bars["avg_vol"] = bars["volume"].rolling(10).mean()
        latest = bars.iloc[-1]
        return {
            "rsi": latest["rsi"],
            "ma200": latest["ma200"],
            "momentum": latest["momentum"],
            "price": latest["close"],
            "volume": latest["avg_vol"]
        }
    except Exception as e:
        log(f"[{symbol}] Analyse-Fehler: {e}")
        return None

def run_bot():
    global weekly_profit, weekly_investment, start_of_week

    if datetime.utcnow() - start_of_week > timedelta(days=7):
        weekly_profit = 0
        weekly_investment = 0
        positions.clear()
        start_of_week = datetime.utcnow()
        send_telegram("Neue Woche gestartet. Statistik zurückgesetzt.")
        log("Neue Woche gestartet.")

    sectors_in_portfolio = set([pos['sector'] for pos in positions.values()])
    candidates = []

    for symbol in tickers:
        data = analyze(symbol)
        if not data: continue
        if pd.isna(data['rsi']) or pd.isna(data['ma200']) or pd.isna(data['momentum']): continue
        if data["volume"] < 1_000_000: continue
        if data["price"] < data["ma200"]: continue
        candidates.append({
            "symbol": symbol,
            "rsi": data["rsi"],
            "price": data["price"],
            "momentum": data["momentum"],
            "sector": sectors.get(symbol, "Unknown")
        })

    top_momentum = sorted(candidates, key=lambda x: x["momentum"], reverse=True)[:10]

    for stock in top_momentum:
        symbol = stock["symbol"]
        rsi = stock["rsi"]
        price = stock["price"]
        sector = stock["sector"]
        qty = int(position_size // price)

        if symbol in positions and rsi > 70:
            try:
                qty = positions[symbol]["qty"]
                buy_price = positions[symbol]["buy_price"]
                profit = (price - buy_price) * qty
                weekly_profit += profit
                api.submit_order(symbol=symbol, qty=qty, side='sell', type='market', time_in_force='gtc')
                send_telegram(f"❌ SELL {symbol} ({qty} @ {price:.2f}) | Gewinn: CHF {profit:.2f}")
                log(f"SELL {symbol} | Gewinn: CHF {profit:.2f}")
                with open("trades.csv", "a") as f:
                    f.write(f"{datetime.utcnow()},SELL,{symbol},{qty},{price:.2f},{profit:.2f}\n")
                del positions[symbol]
            except Exception as e:
                log(f"Fehler bei SELL {symbol}: {e}")

        elif rsi < 30 and symbol not in positions and sector not in sectors_in_portfolio:
            total = price * qty
            if weekly_investment + total <= investment_per_week:
                try:
                    api.submit_order(symbol=symbol, qty=qty, side='buy', type='market', time_in_force='gtc')
                    positions[symbol] = {"buy_price": price, "qty": qty, "sector": sector}
                    weekly_investment += total
                    send_telegram(f"✅ BUY {symbol} ({qty} @ {price:.2f}) | Sektor: {sector}")
                    log(f"BUY {symbol} ({qty}) @ {price:.2f}")
                    with open("trades.csv", "a") as f:
                        f.write(f"{datetime.utcnow()},BUY,{symbol},{qty},{price:.2f},,\n")
                except Exception as e:
                    log(f"Fehler bei BUY {symbol}: {e}")

def send_daily_status():
    if not positions:
        msg = f"Täglicher Status (22:00):\nKeine offenen Positionen.\nWochenergebnis: CHF {weekly_profit:.2f}"
    else:
        msg = f"Täglicher Status (22:00):\nOffene Positionen:"
        for sym, pos in positions.items():
            current_price = api.get_last_trade(sym).price
            profit = (current_price - pos["buy_price"]) * pos["qty"]
            msg += f"\n• {sym}: {pos['qty']} Stk @ {pos['buy_price']:.2f} → {current_price:.2f} | Gewinn: CHF {profit:.2f}"
        msg += f"\n\nWochenergebnis: CHF {weekly_profit:.2f}"
    send_telegram(msg)
    log("[Status] Täglicher Bericht gesendet.")

send_telegram("Bot gestartet mit Top-100-Aktien & täglichem Status.")
log("Bot vollständig gestartet.")

last_report_date = None

while True:
    now = datetime.utcnow()
    run_bot()

    if now.hour == 20 and (last_report_date is None or last_report_date.date() != now.date()):
        send_daily_status()
        last_report_date = now

    time.sleep(3600)
