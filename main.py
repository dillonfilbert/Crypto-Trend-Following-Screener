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
GAP_STRICT = 0.5  # Gap untuk Top Volume (Aman)
GAP_LOOSE  = 0.9  # Gap untuk Top Ticks (Agresif)

if not TOKEN_TELEGRAM or not CHAT_ID:
    print("Error: Token/Chat ID belum di-set!")
    sys.exit()

# === BAGIAN PENTING: GANTI EXCHANGE ===
# Kita pakai BINANCE US supaya tidak diblokir oleh Server GitHub (yang lokasi di USA)
# Datanya 99% sama dengan Global, jadi sinyal tetap VALID.
exchange = ccxt.binanceus({
    'enableRateLimit': True,
    # Kita tidak pakai 'future' karena Binance US cuma ada Spot. 
    # Tapi tenang, harga Spot & Future itu mirroring/kembar.
})

def kirim_notif(pesan):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage?chat_id={CHAT_ID}&text={pesan}&parse_mode=Markdown"
    try:
        requests.get(url)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

# 1. AMBIL TOP VOLUME 
def get_top_volume_pairs():
    print("Sedang mengambil data Top Volume (Binance US)...")
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
            # Filter USDT
            if '/USDT' in symbol:
                vol = data['quoteVolume'] if data['quoteVolume'] else 0
                pairs.append({'symbol': symbol, 'val': vol})
        
        # Kita ambil Top 50 dari market US
        hasil = pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(50)['symbol'].tolist()
        print(f"✅ Sukses ambil {len(hasil)} koin Top Volume.")
        return hasil
    except Exception as e:
        print(f"❌ ERROR AMBIL VOLUME: {e}") 
        return []

# 2. AMBIL TOP TICKS
def get_top_ticks_pairs():
    print("Sedang mengambil data Top Ticks (Binance US)...")
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
            if '/USDT' in symbol:
                # Binance US juga punya data 'count' (jumlah trade)
                count = data['info']['count'] if 'info' in data and 'count' in data['info'] else 0
                pairs.append({'symbol': symbol, 'val': int(count)})
        
        hasil = pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(20)['symbol'].tolist()
        print(f"✅ Sukses ambil {len(hasil)} koin Top Ticks.")
        return hasil
    except Exception as e:
        print(f"❌ ERROR AMBIL TICKS: {e}")
        return []

# --- ANALISA UTAMA ---
def analyze_market(symbol, max_gap, source_label):
    try:
        # Cek Big Trend (ADX 2H)
        bars_2h = exchange.fetch_ohlcv(symbol, timeframe='2h', limit=50)
        df_2h = pd.DataFrame(bars_2h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        adx_val = ta.adx(df_2h['h'], df_2h['l'], df_2h['c'], length=14)['ADX_14'].iloc[-2]
        
        if adx_val < 25: return None

        # Cek Eksekusi (15m)
        bars_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df_15m = pd.DataFrame(bars_15m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        df_15m['ema13'] = ta.ema(df_15m['c'], length=13)
        df_15m['ema21'] = ta.ema(df_15m['c'], length=21)
        df_15m['ema100'] = ta.ema(df_15m['c'], length=100)
        stoch = ta.stoch(df_15m['h'], df_15m['l'], df_15m['c'], k=5, d=3, smooth_k=3)
        df_15m['stoch_k'] = stoch['STOCHk_5_3_3']
        
        # === MODE ANTI TELAT ===
        idx = -2  # Ambil Candle Close
        
        price = df_15m['c'].iloc[idx]
        e13, e21, e100 = df_15m['ema13'].iloc[idx], df_15m['ema21'].iloc[idx], df_15m['ema100'].iloc[idx]
        stoch_k = df_15m['stoch_k'].iloc[idx]
        
        # History Data
        e13_prev = df_15m['ema13'].iloc[idx-1]
        e21_prev = df_15m['ema21'].iloc[idx-1]
        stoch_k_prev = df_15m['stoch_k'].iloc[idx-1]
        e13_prev_2 = df_15m['ema13'].iloc[idx-2]
        
        gap = abs(e13 - e21) / e21 * 100
        is_cheap = (stoch_k < 40) or (stoch_k_prev < 40)
        is_expensive = (stoch_k > 60) or (stoch_k_prev > 60)

        # Trigger Logic
        bullish_cross = (e13 > e21) and (e13_prev <= e21_prev)
        bearish_cross = (e13 < e21) and (e13_prev >= e21_prev)
        bullish_curve = (e13 > e13_prev) and (e13_prev <= e13_prev_2) and (gap < max_gap)
        bearish_curve = (e13 < e13_prev) and (e13_prev >= e13_prev_2) and (gap < max_gap)

        icon = "💎" if source_label == "VOLUME" else "⚡"

        if (price > e100 and e13 > e100 and e21 > e100 and is_cheap):
            if bullish_cross:
                return f"{icon} *LONG ({source_label})*\nCoin: {symbol}\nAction: ⚔️ CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bullish_curve:
                return f"{icon} *LONG ({source_label})*\nCoin: {symbol}\nAction: 🧲 V-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"

        elif (price < e100 and e13 < e100 and e21 < e100 and is_expensive):
            if bearish_cross:
                return f"{icon} *SHORT ({source_label})*\nCoin: {symbol}\nAction: 💀 CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bearish_curve:
                return f"{icon} *SHORT ({source_label})*\nCoin: {symbol}\nAction: 🧱 A-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
        return None

    except Exception as e:
        # Debugging: Uncomment baris bawah kalau mau lihat error per koin
        # print(f"Error analisa {symbol}: {e}")
        return None

if __name__ == "__main__":
    print("🚀 Mulai Scanning (Binance US)...")
    
    # Ambil Data
    list_vol = get_top_volume_pairs()
    list_ticks = get_top_ticks_pairs()
    
    target_coins = {}

    # 1. Ticks
    for coin in list_ticks:
        target_coins[coin] = {'gap': GAP_LOOSE, 'label': 'TICKS'}

    # 2. Volume
    for coin in list_vol:
        target_coins[coin] = {'gap': GAP_STRICT, 'label': 'VOLUME'}

    print(f"📊 Total Koin Unik: {len(target_coins)}")
    
    if len(target_coins) == 0:
        print("⚠️ PERINGATAN: Masih 0 koin? Cek log error di atas.")
    
    for coin, config in target_coins.items():
        hasil = analyze_market(coin, config['gap'], config['label'])
        if hasil:
            kirim_notif(hasil)
            print(f"✅ Notif dikirim: {coin}")
            
    print("🏁 Selesai.")
