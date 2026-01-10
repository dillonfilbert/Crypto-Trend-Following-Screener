import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import os
import sys

# --- CONFIG ---
TOKEN_TELEGRAM = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MAX_GAP_PERCENT = 0.5  # Kita longgarkan dikit buat Altcoin, krn filter kita skrg pakai V-Shape

if not TOKEN_TELEGRAM or not CHAT_ID:
    print("Error: Token/Chat ID belum di-set!")
    sys.exit()

exchange = ccxt.binance() 

def kirim_notif(pesan):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage?chat_id={CHAT_ID}&text={pesan}&parse_mode=Markdown"
    requests.get(url)

def get_top_volume_pairs():
    try:
        tickers = exchange.fetch_tickers()
        usdt_pairs = []
        for symbol, data in tickers.items():
            if '/USDT' in symbol and 'UP/' not in symbol and 'DOWN/' not in symbol:
                usdt_pairs.append({'symbol': symbol, 'volume': data['quoteVolume']})
        return pd.DataFrame(usdt_pairs).sort_values(by='volume', ascending=False).head(50)['symbol'].tolist()
    except:
        return []

def analyze_market(symbol):
    try:
        # 1. CEK BIG TREND (ADX 2H)
        bars_2h = exchange.fetch_ohlcv(symbol, timeframe='2h', limit=50)
        df_2h = pd.DataFrame(bars_2h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        adx_val = ta.adx(df_2h['h'], df_2h['l'], df_2h['c'], length=14)['ADX_14'].iloc[-2]
        
        if adx_val < 25: return None

        # 2. CEK TIMEFRAME EKSEKUSI (15M)
        bars_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df_15m = pd.DataFrame(bars_15m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        df_15m['ema13'] = ta.ema(df_15m['c'], length=13)
        df_15m['ema21'] = ta.ema(df_15m['c'], length=21)
        df_15m['ema100'] = ta.ema(df_15m['c'], length=100)
        stoch = ta.stoch(df_15m['h'], df_15m['l'], df_15m['c'], k=5, d=3, smooth_k=3)
        df_15m['stoch_k'] = stoch['STOCHk_5_3_3']
        
        # --- AMBIL DATA 3 TITIK (NOW, PREV, PREV-2) ---
        idx = -1
        price = df_15m['c'].iloc[idx]
        
        # Data Sekarang (t)
        e13 = df_15m['ema13'].iloc[idx]
        e21 = df_15m['ema21'].iloc[idx]
        e100 = df_15m['ema100'].iloc[idx]
        stoch_k = df_15m['stoch_k'].iloc[idx]
        
        # Data Kemarin (t-1)
        e13_prev = df_15m['ema13'].iloc[idx-1]
        e21_prev = df_15m['ema21'].iloc[idx-1]
        stoch_k_prev = df_15m['stoch_k'].iloc[idx-1]
        
        # Data 2 Candle Lalu (t-2) - PENTING BUAT V-SHAPE
        e13_prev_2 = df_15m['ema13'].iloc[idx-2]
        
        gap = abs(e13 - e21) / e21 * 100

        # Logic Stoch Memory
        is_cheap = (stoch_k < 40) or (stoch_k_prev < 40)
        is_expensive = (stoch_k > 60) or (stoch_k_prev > 60)

        # === TRIGGER LOGIC (STRICT) ===
        
        # 1. Murni Crossing (Silang)
        # Sinyal valid HANYA jika kemarin di bawah, sekarang di atas
        bullish_cross = (e13 > e21) and (e13_prev <= e21_prev)
        bearish_cross = (e13 < e21) and (e13_prev >= e21_prev)
        
        # 2. Murni Curve/Bounce (Lekukan V)
        # Sinyal valid HANYA jika kemarin EMA turun, sekarang EMA naik (Membentuk huruf V)
        # Dan jaraknya wajib dekat (Gap Filter)
        bullish_curve = (e13 > e13_prev) and (e13_prev <= e13_prev_2) and (gap < MAX_GAP_PERCENT)
        bearish_curve = (e13 < e13_prev) and (e13_prev >= e13_prev_2) and (gap < MAX_GAP_PERCENT)

        # === EKSEKUSI SINYAL ===

        # LONG (Trend Bullish + Trigger)
        if (price > e100 and e13 > e100 and e21 > e100 and is_cheap):
            if bullish_cross:
                return f"🟢 *LONG: {symbol}*\nAction: ⚔️ GOLDEN CROSS (Baru Mulai!)\nPrice: {price}\nGap: {gap:.2f}%"
            elif bullish_curve:
                return f"🟢 *LONG: {symbol}*\nAction: 🧲 V-SHAPE BOUNCE (Lekukan)\nPrice: {price}\nGap: {gap:.2f}%"

        # SHORT (Trend Bearish + Trigger)
        elif (price < e100 and e13 < e100 and e21 < e100 and is_expensive):
            if bearish_cross:
                return f"🔴 *SHORT: {symbol}*\nAction: 💀 DEAD CROSS (Baru Mulai!)\nPrice: {price}\nGap: {gap:.2f}%"
            elif bearish_curve:
                return f"🔴 *SHORT: {symbol}*\nAction: 🧱 A-SHAPE REJECT (Lekukan)\nPrice: {price}\nGap: {gap:.2f}%"

        return None

    except:
        return None

if __name__ == "__main__":
    print("Scanning Curve & Cross...")
    coins = get_top_volume_pairs()
    for coin in coins:
        hasil = analyze_market(coin)
        if hasil:
            kirim_notif(hasil)
            print(f"Notif: {coin}")
