import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import os
import sys

# --- CONFIG ---
TOKEN_TELEGRAM = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- SETTINGAN GAP DINAMIS ---
GAP_STRICT = 0.5  # Buat Top Volume (BTC, ETH, dll) - Lebih aman
GAP_LOOSE  = 0.9  # Buat Top Ticks (Koin Gorengan/Viral) - Lebih longgar

if not TOKEN_TELEGRAM or not CHAT_ID:
    print("Error: Token/Chat ID belum di-set!")
    sys.exit()

exchange = ccxt.binance() 

def kirim_notif(pesan):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage?chat_id={CHAT_ID}&text={pesan}&parse_mode=Markdown"
    requests.get(url)

# 1. AMBIL TOP VOLUME (Aset Besar)
def get_top_volume_pairs():
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
            if '/USDT' in symbol and 'UP/' not in symbol and 'DOWN/' not in symbol:
                pairs.append({'symbol': symbol, 'val': data['quoteVolume']})
        return pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(40)['symbol'].tolist()
    except: return []

# 2. AMBIL TOP TICKS (Aset Viral/Rame)
def get_top_ticks_pairs():
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
            if '/USDT' in symbol and 'UP/' not in symbol and 'DOWN/' not in symbol:
                # Ambil jumlah trade count
                count = data['info']['count'] if 'info' in data and 'count' in data['info'] else 0
                pairs.append({'symbol': symbol, 'val': int(count)})
        return pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(40)['symbol'].tolist()
    except: return []

# --- ANALISA DENGAN PARAMETER GAP ---
def analyze_market(symbol, max_gap, source_label):
    try:
        # Cek Big Trend
        bars_2h = exchange.fetch_ohlcv(symbol, timeframe='2h', limit=50)
        df_2h = pd.DataFrame(bars_2h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        adx_val = ta.adx(df_2h['h'], df_2h['l'], df_2h['c'], length=14)['ADX_14'].iloc[-2]
        
        if adx_val < 25: return None

        # Cek Timeframe Eksekusi
        bars_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df_15m = pd.DataFrame(bars_15m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        df_15m['ema13'] = ta.ema(df_15m['c'], length=13)
        df_15m['ema21'] = ta.ema(df_15m['c'], length=21)
        df_15m['ema100'] = ta.ema(df_15m['c'], length=100)
        stoch = ta.stoch(df_15m['h'], df_15m['l'], df_15m['c'], k=5, d=3, smooth_k=3)
        df_15m['stoch_k'] = stoch['STOCHk_5_3_3']
        
        idx = -1
        price = df_15m['c'].iloc[idx]
        e13, e21, e100 = df_15m['ema13'].iloc[idx], df_15m['ema21'].iloc[idx], df_15m['ema100'].iloc[idx]
        stoch_k = df_15m['stoch_k'].iloc[idx]
        
        e13_prev = df_15m['ema13'].iloc[idx-1]
        e21_prev = df_15m['ema21'].iloc[idx-1]
        stoch_k_prev = df_15m['stoch_k'].iloc[idx-1]
        e13_prev_2 = df_15m['ema13'].iloc[idx-2]
        
        gap = abs(e13 - e21) / e21 * 100
        is_cheap = (stoch_k < 40) or (stoch_k_prev < 40)
        is_expensive = (stoch_k > 60) or (stoch_k_prev > 60)

        # Trigger Logic (Pakai max_gap yang dinamis)
        bullish_cross = (e13 > e21) and (e13_prev <= e21_prev)
        bearish_cross = (e13 < e21) and (e13_prev >= e21_prev)
        
        # Di sini kuncinya: max_gap berubah sesuai jenis koin
        bullish_curve = (e13 > e13_prev) and (e13_prev <= e13_prev_2) and (gap < max_gap)
        bearish_curve = (e13 < e13_prev) and (e13_prev >= e13_prev_2) and (gap < max_gap)

        # Icon beda biar tau ini trigger dari list mana
        icon = "💎" if source_label == "VOLUME" else "⚡"

        if (price > e100 and e13 > e100 and e21 > e100 and is_cheap):
            if bullish_cross:
                return f"{icon} *LONG ({source_label})*\nCoin: {symbol}\nAction: ⚔️ CROSS\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bullish_curve:
                return f"{icon} *LONG ({source_label})*\nCoin: {symbol}\nAction: 🧲 V-SHAPE\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"

        elif (price < e100 and e13 < e100 and e21 < e100 and is_expensive):
            if bearish_cross:
                return f"{icon} *SHORT ({source_label})*\nCoin: {symbol}\nAction: 💀 CROSS\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bearish_curve:
                return f"{icon} *SHORT ({source_label})*\nCoin: {symbol}\nAction: 🧱 A-SHAPE\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
        return None

    except: return None

if __name__ == "__main__":
    print("Mengambil data koin...")
    list_vol = get_top_volume_pairs()
    list_ticks = get_top_ticks_pairs()
    
    # === LOGIKA PENGGABUNGAN PINTAR ===
    # Dictionary untuk menyimpan {Symbol : Max_Gap}
    target_coins = {}

    # 1. Masukkan list Ticks dulu (Kita kasih Gap Longgar)
    for coin in list_ticks:
        target_coins[coin] = {'gap': GAP_LOOSE, 'label': 'TICKS'}

    # 2. Timpa dengan list Volume (Kita kasih Gap Ketat)
    # Kenapa ditimpa? Karena kalau koin ada di dua-duanya (misal BTC), 
    # kita mau pakai aturan yang lebih AMAN (Volume/Ketat) biar gak spam.
    for coin in list_vol:
        target_coins[coin] = {'gap': GAP_STRICT, 'label': 'VOLUME'}

    print(f"Total Koin Unik yg dipantau: {len(target_coins)}")
    
    for coin, config in target_coins.items():
        hasil = analyze_market(coin, config['gap'], config['label'])
        if hasil:
            kirim_notif(hasil)
            print(f"Notif: {coin}")
