from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from tefasmak import tum_fonlar, fon_anlik_bilgi
import uvicorn

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_fon_cache = None

def get_fonlar():
    global _fon_cache
    if _fon_cache is None:
        try:
            print("TEFAS'tan fon listesi çekiliyor... (Bu işlem biraz sürebilir)")
            _fon_cache = tum_fonlar("YAT")
            print(f"Başarılı: {len(_fon_cache)} fon çekildi.")
        except Exception as e:
            print("TEFAS Fon listesi çekilemedi! Hata:", e)
            _fon_cache = []
    return _fon_cache

@app.get("/fonlar")
def get_fonlar():
    try:
        # TEFAS'ın yeni sitesinden JSON verisini çekiyoruz
        url = "https://www.tefas.gov.tr/api/funds/list"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.tefas.gov.tr/"
        }
        res = requests.get(url, headers=headers, timeout=15)
        data = res.json()
        
        fon_listesi = []
        # TEFAS'tan gelen veri yapısına göre kod ve isimleri ayıklıyoruz
        if isinstance(data, dict) and "data" in data:
            for item in data["data"]:
                fon_listesi.append({
                    "code": item.get("FONKODU", ""),
                    "name": item.get("FONUNVAN", "")
                })
        elif isinstance(data, list):
            for item in data:
                fon_listesi.append({
                    "code": item.get("FONKODU", ""),
                    "name": item.get("FONUNVAN", "")
                })
                
        # Sadece kodu ve ismi dolu olanları döndür
        temiz_liste = [f for f in fon_listesi if f["code"] and f["name"]]
        return temiz_liste
        
    except Exception as e:
        print("Fon listesi çekilemedi:", e)
        return []
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
