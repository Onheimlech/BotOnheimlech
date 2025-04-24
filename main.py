import os
import time
import json
import logging
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from flask import Flask, request
from threading import Thread
import alpaca_trade_api as tradeapi

# === KONFIGURATION ===
API_KEY = "PK7C24MFH67A20OUM22L"
API_SECRET = "rv7i3NAZzv9Tw8P9swBpaOcKP4omX6IJAKJGbgTY"
BASE_URL = "https://paper-api.alpaca.markets"
TELEGRAM_TOKEN = "7883966444:AAHJfeC0EnX-Tjd1H5NPSM7zCXfntg_W2Bs"
TELEGRAM_CHAT_ID = "344603231"

# === INITIALISIERUNG ===
app = Flask(__name__)
api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL)
positions = {}
weekly_profit = 0.0
last_trade_msg = "Noch keine Trades."
start_of_week = datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())

# === LOGGING ===
logging.basicConfig(filename="bot.log", level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# === HELPER ===
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        logging.error(f"Telegram-Fehler: {e}")

def get_symbols():
    if os.path.exists("tickers.csv"):
        with open("tickers.csv", "r") as f:
            return [line.strip() for line in f if line.strip()]
    return ["TSLA", "NVDA", "AAPL", "AMD", "META", "MSFT", "GOOGL", "AMZN"]

def analyze(symbol):
    try:
        df = yf.download(symbol, period="6mo", interval="1d", auto_adjust=True)
        if df.empty or "Close" not in df.columns:
            print(f"{symbol}: keine gültigen Preisdaten.")
            return None

        close = df["Close"].squeeze()
        rsi = RSIIndicator(close).rsi()
        ma = close.rolling(window=50).mean()

        latest_price = close.iloc[-1]
        latest_rsi = rsi.iloc[-1]
        latest_ma = ma.iloc[-1]

        print(f"{symbol} | RSI: {latest_rsi:.2f}, MA: {latest_ma:.2f}, Preis: {latest_price:.2f}")

        return {
            "rsi": latest_rsi,
            "ma": latest_ma,
            "price": latest_price
        }

    except Exception as e:
        print(f"{symbol} Analysefehler: {e}")
        logging.warning(f"{symbol} Analysefehler: {e}")
        return None

# === TRADING-LOGIK ===
def run_bot():
    global weekly_profit, start_of_week, last_trade_msg
    trades_gemacht = False

    if datetime.utcnow() - start_of_week > timedelta(days=7):
        weekly_profit = 0.0
        start_of_week = datetime.utcnow()
        send_telegram("Neue Woche gestartet. Gewinn zurückgesetzt.")
        logging.info("Neue Woche gestartet.")

    symbols = get_symbols()
    for symbol in symbols:
        data = analyze(symbol)
        if not data or pd.isna(data["rsi"]) or pd.isna(data["ma"]):
            continue

        price = data["price"]
        qty = int(2000 // price)

        # BUY
        if data["rsi"] < 35 and price > data["ma"] and symbol not in positions:
            try:
                api.submit_order(symbol=symbol, qty=qty, side='buy', type='market', time_in_force='gtc')
                positions[symbol] = {"qty": qty, "buy_price": price}
                msg = f"BUY {symbol} ({qty} @ {price:.2f})"
                last_trade_msg = msg
                send_telegram(msg)
                logging.info(msg)
                trades_gemacht = True
            except Exception as e:
                logging.error(f"BUY-Fehler {symbol}: {e}")

        # SELL
        elif symbol in positions:
            buy_price = positions[symbol]["buy_price"]
            if data["rsi"] > 70 or price < buy_price * 0.9:
                try:
                    qty = positions[symbol]["qty"]
                    profit = (price - buy_price) * qty
                    weekly_profit += profit
                    api.submit_order(symbol=symbol, qty=qty, side='sell', type='market', time_in_force='gtc')
                    msg = f"SELL {symbol} | Gewinn: CHF {profit:.2f}"
                    last_trade_msg = msg
                    send_telegram(msg)
                    logging.info(msg)
                    del positions[symbol]
                    trades_gemacht = True
                except Exception as e:
                    logging.error(f"SELL-Fehler {symbol}: {e}")

    if not trades_gemacht:
        send_telegram("Analyse abgeschlossen. Keine passenden Aktien für Kauf oder Verkauf gefunden.")

# === MARKTZEITEN-CHECK ===
def markt_ist_offen():
    jetzt = datetime.utcnow() + timedelta(hours=2)  # CH-Zeit
    return jetzt.weekday() < 5 and 15 <= jetzt.hour < 22  # Mo–Fr, 15:00–22:00

# === TELEGRAM WEBHOOK ===
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    global last_trade_msg
    data = request.get_json()
    if "message" in data and "text" in data["message"]:
        msg = data["message"]["text"].strip().lower()
        if msg == "/status":
            status = f"Bot läuft.\nLetzter Trade:\n{last_trade_msg}"
            send_telegram(status)
    return "", 200

# === TÄGLICHER BERICHT ===
def daily_report_loop():
    while True:
        now = datetime.utcnow() + timedelta(hours=2)  # CH-Zeit
        if now.hour == 22 and now.minute == 0:
            msg = f"Täglicher Bericht\nLetzter Trade:\n{last_trade_msg}\nAktueller Wochengewinn: CHF {weekly_profit:.2f}"
            send_telegram(msg)
            time.sleep(60)
        time.sleep(30)

# === MAIN LOOP ===
def loop():
    while True:
        if markt_ist_offen():
            logging.info("Markt ist offen – starte Analyse...")
            run_bot()
        else:
            logging.info("Markt geschlossen – keine Analyse.")
        time.sleep(900)  # 15 Minuten

# === START ===
if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()
    Thread(target=daily_report_loop).start()
    loop()
