import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import os
import sys

# --- AMBIL RAHASIA DARI GITHUB ---
try:
    TOKEN_TELEGRAM = os.environ["TELEGRAM_TOKEN"]
    CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
except KeyError:
    print("Error: Token/Chat ID belum di-set di GitHub Secrets!")
    sys.exit()

exchange = ccxt.binance() # Server GitHub di Luar Negeri, jadi Aman!

def kirim_notif(pesan):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage?chat_id={CHAT_ID}&text={pesan}&parse_mode=Markdown"
    requests.get(url)

def get_top_volume_pairs():
    # ... (Logika sama: Ambil Top 50 Volume) ...
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
    # ... (Logika Sniper Sama Persis) ...
    try:
        # Cek 2H ADX
        bars_2h = exchange.fetch_ohlcv(symbol, timeframe='2h', limit=50)
        df_2h = pd.DataFrame(bars_2h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        adx_val = ta.adx(df_2h['h'], df_2h['l'], df_2h['c'], length=14)['ADX_14'].iloc[-2]
        
        if adx_val < 25: return None

        # Cek 15m Sniper
        bars_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df_15m = pd.DataFrame(bars_15m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        df_15m['ema13'] = ta.ema(df_15m['c'], length=13)
        df_15m['ema21'] = ta.ema(df_15m['c'], length=21)
        df_15m['ema100'] = ta.ema(df_15m['c'], length=100)
        df_15m['stoch_k'] = ta.stoch(df_15m['h'], df_15m['l'], df_15m['c'], k=5, d=3, smooth_k=3)['STOCHk_5_3_3']
        
        idx = -1
        price = df_15m['c'].iloc[idx]
        e13, e21, e100 = df_15m['ema13'].iloc[idx], df_15m['ema21'].iloc[idx], df_15m['ema100'].iloc[idx]
        stoch_k = df_15m['stoch_k'].iloc[idx]
        
        # Kondisi Filter
        if not (price > e100 and e13 > e100 and e21 > e100 and stoch_k < 40):
            return None

        # Kondisi Trigger
        e13_prev, e21_prev = df_15m['ema13'].iloc[idx-1], df_15m['ema21'].iloc[idx-1]
        is_crossing = (e13 > e21) and (e13_prev <= e21_prev)
        is_near_rising = (abs(e13 - e21)/e21*100 < 0.3) and (e13 > e13_prev)

        if is_crossing or is_near_rising:
            action = "⚔️ CROSS" if is_crossing else "🧲 BOUNCE"
            return f"🎯 *{symbol}*\n{action}\nPrice: {price}\nStoch: {stoch_k:.2f}\nADX 2H: {adx_val:.2f}"
            
        return None
    except:
        return None

if __name__ == "__main__":
    print("Mulai Scanning di Cloud...")
    coins = get_top_volume_pairs()
    for coin in coins:
        hasil = analyze_market(coin)
        if hasil:
            kirim_notif(hasil)
            print(f"Notif dikirim: {coin}")

    print("Selesai.")
