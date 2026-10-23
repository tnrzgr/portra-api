from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
import uvicorn

try:
    import tefasmak
except ImportError:
    tefasmak = None

try:
    import borsapy as bp
except ImportError:
    bp = None

app = FastAPI(title="PORtra API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

COLLECT_API_KEY = "52PbVd3MhiUznRS0L73H4g:6rploIh2fILNVYF4LkIMQK"
TWELVE_DATA_API_KEY = "a5aacbec3f444817a0fed146c92eb641"

# Bellek İçi Önbellek (Render Free Tier Performansı İçin)
PRICE_CACHE = {}
PRICE_TTL = 30  # 30 saniye
HISTORY_CACHE = {}
HISTORY_TTL = 3600  # 1 saat
NEWS_CACHE = {}
NEWS_TTL = 600  # 10 dakika

NEWS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# (Burada BIST_LIST ve OTHER_LIST varlık listeleri yer alır)
# ...

# ==========================================
# ENDPOINTS
# ==========================================

@app.get("/")
def root():
    return {"status": "ok", "app": "PORtra API", "version": "1.0"}

@app.get("/varliklar/{market}")
def get_varliklar(market: str):
    m = market.upper().strip()
    if m == "BIST":
        return BIST_LIST
    for k in OTHER_LIST:
        if k.upper() == m:
            return OTHER_LIST[k]
    return []

@app.get("/fonlar")
def get_fonlar():
    if tefasmak:
        try:
            tum = tefasmak.tum_fonlar()
            if hasattr(tum, "to_dict"):
                data = []
                for _, row in tum.iterrows():
                    code = str(row.get("FONKODU", row.get("KOD", ""))).strip()
                    name = str(row.get("FONUNVANI", row.get("UNVAN", ""))).strip()
                    if code:
                        data.append({"code": code, "name": name})
                if data:
                    return data
        except Exception as e:
            print("tefasmak fon listeleme hatası:", e)
    return POPULAR_FONLAR

@app.get("/fon/{symbol}")
def get_fon_price(symbol: str):
    s = symbol.upper().strip()
    key = f"Fon:{s}"
    now = time.time()
    if key in PRICE_CACHE and now - PRICE_CACHE[key][0] < PRICE_TTL:
        return {"symbol": s, "price": PRICE_CACHE[key][1]}

    if tefasmak:
        try:
            res = tefasmak.fon_son_fiyat_ve_getiri(s)
            if res and isinstance(res, dict) and "fiyat" in res:
                val = float(res["fiyat"])
                PRICE_CACHE[key] = (now, val)
                return {"symbol": s, "price": val}
        except Exception:
            pass

    try:
        r = requests.post(
            "https://www.tefas.gov.tr/api/DB/BindHistoryInfo",
            data={"fontip": "YAT", "fonkod": s},
            timeout=5,
            headers=NEWS_HEADERS
        )
        data = r.json()
        if data.get("data") and len(data["data"]) > 0:
            val = float(data["data"][0]["FIYAT"])
            PRICE_CACHE[key] = (now, val)
            return {"symbol": s, "price": val}
    except Exception:
        pass

    return {"symbol": s, "price": 1.25}

@app.get("/fiyat/{market}/{symbol}")
def get_price(market: str, symbol: str):
    m = market.upper().strip()
    s = symbol.upper().strip()
    key = f"{m}:{s}"
    now = time.time()
    if key in PRICE_CACHE and now - PRICE_CACHE[key][0] < PRICE_TTL:
        return {"symbol": s, "price": PRICE_CACHE[key][1]}

    price = None

    # Kripto (Binance API)
    if m in ["KRIPTO", "CRYPTO"]:
        try:
            clean_sym = s.replace("USDT", "").replace("USD", "")
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={clean_sym}USDT", timeout=4)
            if r.status_code == 200:
                price = float(r.json()["price"])
        except Exception:
            pass

    # Döviz (Yahoo Finance)
    elif m in ["DÖVIZ", "DOVIZ", "FOREX"]:
        target = "USDTRY=X" if "USD" in s else "EURTRY=X" if "EUR" in s else f"{s}=X"
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{target}?interval=1d&range=1d",
                headers=NEWS_HEADERS,
                timeout=5
            )
            if r.status_code == 200:
                meta = r.json()["chart"]["result"][0]["meta"]
                price = float(meta.get("regularMarketPrice", 0))
        except Exception:
            pass

    # BIST
    elif m == "BIST":
        if bp:
            try:
                t = bp.Ticker(s)
                p = t.info.get("last_price")
                if p: price = float(p)
            except Exception:
                pass
        if not price:
            try:
                r = requests.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{s}.IS?interval=1d&range=1d",
                    headers=NEWS_HEADERS,
                    timeout=5
                )
                if r.status_code == 200:
                    meta = r.json()["chart"]["result"][0]["meta"]
                    price = float(meta.get("regularMarketPrice", 0))
            except Exception:
                pass
        if not price and COLLECT_API_KEY:
            try:
                r = requests.get(
                    f"https://api.collectapi.com/economy/singleHisse?code={s}",
                    headers={"authorization": f"apikey {COLLECT_API_KEY}", "content-type": "application/json"},
                    timeout=5
                )
                data = r.json()
                if data.get("success") and data.get("result"):
                    price = float(data["result"][0]["price"])
            except Exception:
                pass

    # ABD Hisseleri
    elif m in ["ABD", "US", "STOCK"]:
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d&range=1d",
                headers=NEWS_HEADERS,
                timeout=5
            )
            if r.status_code == 200:
                meta = r.json()["chart"]["result"][0]["meta"]
                price = float(meta.get("regularMarketPrice", 0))
        except Exception:
            pass
        if not price and TWELVE_DATA_API_KEY:
            try:
                r = requests.get(
                    f"https://api.twelvedata.com/price?symbol={s}&apikey={TWELVE_DATA_API_KEY}",
                    timeout=5
                )
                data = r.json()
                if "price" in data:
                    price = float(data["price"])
            except Exception:
                pass

    # Emtia
    elif m in ["EMTIA", "COMMODITY"]:
        emtia_target = "GC=F" if "XAU" in s else "SI=F" if "XAG" in s else "BZ=F" if "BRENT" in s else s
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{emtia_target}?interval=1d&range=1d",
                headers=NEWS_HEADERS,
                timeout=5
            )
            if r.status_code == 200:
                meta = r.json()["chart"]["result"][0]["meta"]
                price = float(meta.get("regularMarketPrice", 0))
        except Exception:
            pass

    if price and price > 0:
        PRICE_CACHE[key] = (now, price)
        return {"symbol": s, "price": price}

    mock_defaults = {"THYAO": 290.0, "GARAN": 145.0, "AAPL": 230.0, "BTC": 67000.0, "USDTRY": 34.50, "EURTRY": 37.20, "XAU": 3050.0}
    return {"symbol": s, "price": mock_defaults.get(s, 100.0)}

@app.get("/gecmis/{market}/{symbol}")
def get_history(market: str, symbol: str):
    m = market.upper().strip()
    s = symbol.upper().strip()
    key = f"{m}:{s}"
    now = time.time()
    if key in HISTORY_CACHE and now - HISTORY_CACHE[key][0] < HISTORY_TTL:
        return HISTORY_CACHE[key][1]

    if m == "BIST": target = f"{s}.IS"
    elif m in ["KRIPTO", "CRYPTO"]: target = f"{s}-USD"
    elif m in ["DÖVIZ", "DOVIZ"]: target = f"{s}=X"
    elif m in ["EMTIA"]: target = "GC=F" if "XAU" in s else "SI=F" if "XAG" in s else "BZ=F"
    else: target = s

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{target}?range=1mo&interval=1d"
        r = requests.get(url, headers=NEWS_HEADERS, timeout=6)
        if r.status_code == 200:
            result = r.json()["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            closes = result["indicators"]["quote"][0].get("close", [])
            history = []
            for ts, c in zip(timestamps, closes):
                if c is not None:
                    d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    history.append({"date": d, "price": round(float(c), 2)})
            if history:
                HISTORY_CACHE[key] = (now, history)
                return history
    except Exception as e:
        print("Geçmiş veri hatası:", e)

    base_p = PRICE_CACHE.get(key, (0, 100.0))[1]
    mock_hist = []
    for i in range(29, -1, -1):
        dt = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        mock_hist.append({"date": dt, "price": round(base_p * (0.95 + (i % 7) * 0.015), 2)})
    return mock_hist

# ==========================================
# HABERLER (Google News RSS)
# ==========================================

def fetch_rss_items(url: str, limit: int = 8):
    try:
        r = requests.get(url, timeout=7, headers=NEWS_HEADERS)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print("RSS çekme hatası:", e)
        return []

    items = []
    for it in root.findall(".//item")[:limit]:
        pub = it.findtext("pubDate")
        try:
            dt = parsedate_to_datetime(pub).isoformat()
        except Exception:
            dt = ""

        raw_title = it.findtext("title") or ""
        source_name = it.findtext("source")
        if not source_name and " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            title = parts[0]
            source_name = parts[1]
        else:
            title = raw_title
            source_name = source_name or "Finans Gündemi"

        link = it.findtext("link") or ""

        items.append({
            "title": title.strip(),
            "url": link.strip(),
            "source": source_name.strip(),
            "datetime": dt,
        })
    return items

def build_news_query(market: str, symbol: str):
    m = market.upper().strip()
    s = symbol.upper().strip()
    if m == "BIST":
        return f"{s} hisse", "tr", "TR", "tr"
    if m == "FON":
        return f"{s} fon TEFAS", "tr", "TR", "tr"
    if m in ["KRIPTO", "CRYPTO"]:
        crypto_names = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "AVAX": "Avalanche"}
        q = crypto_names.get(s, s)
        return f"{q} crypto", "en-US", "US", "en"
    if m in ["ABD", "US"]:
        return f"{s} stock", "en-US", "US", "en"
    if m in ["EMTIA", "COMMODITY"]:
        emtia_map = {"XAU": "altın gram ons", "XAG": "gümüş fiyat", "BRENT": "brent petrol"}
        return emtia_map.get(s, f"{s} emtia"), "tr", "TR", "tr"
    if m in ["DÖVIZ", "DOVIZ"]:
        if "USD" in s: return "dolar kuru TCMB", "tr", "TR", "tr"
        if "EUR" in s: return "euro kuru", "tr", "TR", "tr"
        return f"{s} kuru", "tr", "TR", "tr"
    return f"{s} ekonomi", "tr", "TR", "tr"

@app.get("/haberler/genel")
def get_general_news():
    key = "GENEL_PIYASA"
    cached = NEWS_CACHE.get(key)
    if cached and time.time() - cached[0] < NEWS_TTL:
        return cached[1]

    url = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=tr&gl=TR&ceid=TR:tr"
    items = fetch_rss_items(url, limit=15)
    NEWS_CACHE[key] = (time.time(), items)
    return items

@app.get("/haber/{market}/{symbol}")
def get_news(market: str, symbol: str):
    q = build_news_query(market, symbol)
    if not q:
        return []
    query, hl, gl, lang = q

    key = f"{market}:{symbol}"
    cached = NEWS_CACHE.get(key)
    if cached and time.time() - cached[0] < NEWS_TTL:
        return cached[1]

    url = f"https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
    items = fetch_rss_items(url, limit=6)
    NEWS_CACHE[key] = (time.time(), items)
    return items

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
