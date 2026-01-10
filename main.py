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

# === KRAKEN (USD ONLY) ===
# Kita pakai Kraken karena Legal di US (Anti-Blokir GitHub).
# Kita hanya ambil pair USD (Fiat) untuk data paling mulus.
exchange = ccxt.kraken({
    'enableRateLimit': True,
})

def kirim_notif(pesan):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage?chat_id={CHAT_ID}&text={pesan}&parse_mode=Markdown"
    try:
        requests.get(url)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

# 1. AMBIL TOP VOLUME (Hanya USD)
def get_top_volume_pairs():
    print("Sedang mengambil data Top Volume (Kraken USD)...")
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
            # FILTER KETAT: Hanya yang belakangnya /USD
            if symbol.endswith('/USD'):
                # Buang Pair Forex (Mata uang vs Mata uang)
                if 'EUR/' in symbol or 'GBP/' in symbol or 'AUD/' in symbol or 'USDT/' in symbol or 'USDC/' in symbol:
                    continue
                
                # Buang Stablecoin vs USD (USDT/USD, USDC/USD) - Kita mau cari Volatility
                if symbol.startswith('USDT') or symbol.startswith('USDC') or symbol.startswith('DAI'):
                    continue

                vol = data['quoteVolume'] if data['quoteVolume'] else 0
                pairs.append({'symbol': symbol, 'val': vol})
        
        hasil = pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(50)['symbol'].tolist()
        print(f"✅ Sukses ambil {len(hasil)} koin Top Volume (USD).")
        return hasil
    except Exception as e:
        print(f"❌ ERROR AMBIL VOLUME: {e}") 
        return []

# 2. AMBIL TOP TICKS (Hanya USD)
def get_top_ticks_pairs():
    print("Sedang mengambil data Top Ticks (Kraken USD)...")
    try:
        tickers = exchange.fetch_tickers()
        pairs = []
        for symbol, data in tickers.items():
             if symbol.endswith('/USD'):
                # Filter Forex & Stablecoin sama seperti di atas
                if 'EUR/' in symbol or 'GBP/' in symbol or 'AUD/' in symbol or 'USDT/' in symbol or 'USDC/' in symbol:
                    continue
                if symbol.startswith('USDT') or symbol.startswith('USDC') or symbol.startswith('DAI'):
                    continue

                # Di Kraken, Quote Volume sangat berkorelasi dengan aktivitas ticks
                vol = data['quoteVolume'] if data['quoteVolume'] else 0
                pairs.append({'symbol': symbol, 'val': vol})
        
        hasil = pd.DataFrame(pairs).sort_values(by='val', ascending=False).head(20)['symbol'].tolist()
        print(f"✅ Sukses ambil {len(hasil)} koin Top Activity (USD).")
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
        
        # === MODE ANTI TELAT (Idx -2) ===
        idx = -2  
        
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
        
        # Rapikan nama symbol (Hapus /USD biar ringkas di notif)
        clean_symbol = symbol.replace('/USD', '')

        if (price > e100 and e13 > e100 and e21 > e100 and is_cheap):
            if bullish_cross:
                return f"{icon} *LONG ({source_label})*\nCoin: {clean_symbol}\nAction: ⚔️ CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bullish_curve:
                return f"{icon} *LONG ({source_label})*\nCoin: {clean_symbol}\nAction: 🧲 V-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"

        elif (price < e100 and e13 < e100 and e21 < e100 and is_expensive):
            if bearish_cross:
                return f"{icon} *SHORT ({source_label})*\nCoin: {clean_symbol}\nAction: 💀 CROSS (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
            elif bearish_curve:
                return f"{icon} *SHORT ({source_label})*\nCoin: {clean_symbol}\nAction: 🧱 A-SHAPE (Closed)\nPrice: {price}\nGap: {gap:.2f}% (Limit: {max_gap}%)"
        return None

    except Exception as e:
        # print(f"Error analisa {symbol}: {e}")
        return None

if __name__ == "__main__":
    print("🚀 Mulai Scanning (Kraken USD Only)...")
    
    # 1. AMBIL DATA MENTAH
    list_vol = get_top_volume_pairs()
    list_ticks = get_top_ticks_pairs()
    
    # --- BAGIAN BARU: TAMPILKAN TERPISAH ---
    print("\n" + "="*60)
    print(f"💎 TOP 50 VOLUME (Gap Strict {GAP_STRICT}%):")
    # Tampilkan list bersih tanpa /USD biar enak dibaca
    print(", ".join([x.replace('/USD', '') for x in list_vol]))
    
    print("\n" + "-"*60)
    print(f"⚡ TOP 20 TICKS (Gap Loose {GAP_LOOSE}%):")
    print(", ".join([x.replace('/USD', '') for x in list_ticks]))
    print("="*60 + "\n")
    # ---------------------------------------

    # 2. PROSES PENGGABUNGAN (LOGIKA PRIORITAS)
    target_coins = {}

    # Masukkan Ticks dulu (Gap Longgar)
    for coin in list_ticks:
        target_coins[coin] = {'gap': GAP_LOOSE, 'label': 'TICKS'}

    # Timpa dengan Volume (Gap Ketat) - Prioritas Keamanan
    # Jika koin ada di dua list (misal BTC), dia akan dipaksa ikut aturan Volume.
    for coin in list_vol:
        target_coins[coin] = {'gap': GAP_STRICT, 'label': 'VOLUME'}

    print(f"📊 Total Koin Unik (Gabungan): {len(target_coins)}")
    
    if len(target_coins) == 0:
        print("⚠️ PERINGATAN: Masih 0 koin? Cek log error di atas.")
    
    # 3. EKSEKUSI SCAN
    for coin, config in target_coins.items():
        hasil = analyze_market(coin, config['gap'], config['label'])
        if hasil:
            kirim_notif(hasil)
            print(f"✅ Notif dikirim: {coin}")
            
    print("🏁 Selesai.")
