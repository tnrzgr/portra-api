from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import hashlib
import json
import os
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

# ==========================================
# KULLANICI KİMLİK DOĞRULAMA (AUTH) SİSTEMİ
# ==========================================

USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")
USERS_CACHE = {}

def load_users():
    global USERS_CACHE
    if USERS_CACHE:
        return USERS_CACHE
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                USERS_CACHE = json.load(f)
                return USERS_CACHE
        except Exception:
            pass
    return USERS_CACHE

def save_users(users):
    global USERS_CACHE
    USERS_CACHE = users
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # Fallback to in-memory store
        pass

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

def hash_pw(pw: str) -> str:
    return hashlib.sha256(f"portra_{pw}_salt".encode("utf-8")).hexdigest()

@app.post("/auth/register")
def register_user(req: RegisterRequest):
    users = load_users()
    email_clean = req.email.strip().lower()
    if email_clean in users:
        raise HTTPException(status_code=400, detail="Bu e-posta adresiyle kayıtlı bir hesap zaten var.")
    
    user_data = {
        "id": f"u_{int(time.time()*1000)}",
        "name": req.name.strip(),
        "email": email_clean,
        "password_hash": hash_pw(req.password),
        "created_at": int(time.time())
    }
    users[email_clean] = user_data
    save_users(users)
    return {
        "success": True,
        "user": {
            "id": user_data["id"],
            "name": user_data["name"],
            "email": user_data["email"],
            "isGuest": False,
            "joinedAt": user_data["created_at"]
        }
    }

@app.post("/auth/login")
def login_user(req: LoginRequest):
    users = load_users()
    email_clean = req.email.strip().lower()
    user_data = users.get(email_clean)
    if not user_data or user_data.get("password_hash") != hash_pw(req.password):
        # Default demo hesabı desteği
        if email_clean == "demo@portra.app" and req.password == "123456":
            return {
                "success": True,
                "user": {
                    "id": "demo_user",
                    "name": "Taner Özgür",
                    "email": "demo@portra.app",
                    "isGuest": False,
                    "joinedAt": int(time.time())
                }
            }
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı.")
    
    return {
        "success": True,
        "user": {
            "id": user_data["id"],
            "name": user_data["name"],
            "email": user_data["email"],
            "isGuest": False,
            "joinedAt": user_data.get("created_at", int(time.time()))
        }
    }


FEEDBACK_FILE = os.path.join(os.path.dirname(__file__), "feedbacks.json")

class FeedbackRequest(BaseModel):
    id: str = ""
    date: str = ""
    category: str = "suggestion"
    email: str = ""
    subject: str = ""
    message: str

@app.post("/api/feedback")
def receive_feedback(req: FeedbackRequest):
    try:
        data = []
        if os.path.exists(FEEDBACK_FILE):
            try:
                with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = []
        data.append(req.dict())
        with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"status": "ok", "message": "Geri bildirim başarıyla kaydedildi"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/feedbacks")
def get_feedbacks():
    if os.path.exists(FEEDBACK_FILE):
        try:
            with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

COLLECT_API_KEY = "52PbVd3MhiUznRS0L73H4g:6rploIh2fILNVYF4LkIMQK"
TWELVE_DATA_API_KEY = "a5aacbec3f444817a0fed146c92eb641"

# Bellek İçi Önbellek (Render Free Tier Performansı ve Kesintisiz Fiyat Güvencesi)
PRICE_CACHE = {}
LAST_KNOWN_PRICES = {}
PRICE_TTL = 60  # 60 saniye (API limitlerini ve sunucu yükünü %50 azaltır)
HISTORY_CACHE = {}
HISTORY_TTL = 3600  # 1 saat
NEWS_CACHE = {}
NEWS_TTL = 600  # 10 dakika

NEWS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# ==========================================
# VARLIK TANIMLARI
# ==========================================

BIST_LIST = [
  {
    "code": "A1CAP",
    "name": "A1 CAPITAL YATIRIM MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "ACSEL",
    "name": "ACISELSAN ACIPAYAM SELÜLOZ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ADEL",
    "name": "ADEL KALEMCİLİK TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "ADESE",
    "name": "ADESE GAYRİMENKUL YATIRIM A.Ş."
  },
  {
    "code": "ADGYO",
    "name": "ADRA GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "AEFES",
    "name": "ANADOLU EFES BİRACILIK VE MALT SANAYİİ A.Ş."
  },
  {
    "code": "AFYON",
    "name": "AFYON ÇİMENTO SANAYİ T.A.Ş."
  },
  {
    "code": "AGESA",
    "name": "AGESA HAYAT VE EMEKLİLİK A.Ş."
  },
  {
    "code": "AGHOL",
    "name": "AG ANADOLU GRUBU HOLDİNG A.Ş."
  },
  {
    "code": "AGYO",
    "name": "ATAKULE GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "AHGAZ",
    "name": "AHLATCI DOĞAL GAZ DAĞITIM ENERJİ VE YATIRIM A.Ş."
  },
  {
    "code": "AKBNK",
    "name": "AKBANK T.A.Ş."
  },
  {
    "code": "AKCNS",
    "name": "AKÇANSA ÇİMENTO SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "AKENR",
    "name": "AKENERJİ ELEKTRİK ÜRETİM A.Ş."
  },
  {
    "code": "AKFGY",
    "name": "AKFEN GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "AKFYE",
    "name": "AKFEN YENİLENEBİLİR ENERJİ A.Ş."
  },
  {
    "code": "AKGRT",
    "name": "AKSİGORTA A.Ş."
  },
  {
    "code": "AKMGY",
    "name": "AKMERKEZ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "AKSA",
    "name": "AKSA AKRİLİK KİMYA SANAYİİ A.Ş."
  },
  {
    "code": "AKSEN",
    "name": "AKSA ENERJİ ÜRETİM A.Ş."
  },
  {
    "code": "AKSGY",
    "name": "AKİŞ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "AKSUE",
    "name": "AKSU ENERJİ VE TİCARET A.Ş."
  },
  {
    "code": "AKYHO",
    "name": "AKDENİZ YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "ALARK",
    "name": "ALARKO HOLDİNG A.Ş."
  },
  {
    "code": "ALBRK",
    "name": "ALBARAKA TÜRK KATILIM BANKASI A.Ş."
  },
  {
    "code": "ALCAR",
    "name": "ALARKO CARRIER SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ALCTL",
    "name": "ALCATEL LUCENT TELETAŞ TELEKOMÜNİKASYON A.Ş."
  },
  {
    "code": "ALFAS",
    "name": "ALFA SOLAR ENERJİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ALGYO",
    "name": "ALARKO GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "ALKA",
    "name": "ALKİM KAĞIT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ALKIM",
    "name": "ALKİM ALKALİ KİMYA A.Ş."
  },
  {
    "code": "ALMAD",
    "name": "ALTINYAĞ MADENCİLİK VE ENERJİ YATIRIMLARI SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ANELE",
    "name": "ANEL ELEKTRİK PROJE TAAHHÜT VE TİCARET A.Ş."
  },
  {
    "code": "ANGEN",
    "name": "ANATOLİA TANI VE BİYOTEKNOLOJİ ÜRÜNLERİ ARAŞTIRMA GELİŞTİRME SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ANHYT",
    "name": "ANADOLU HAYAT EMEKLİLİK A.Ş."
  },
  {
    "code": "ANSGR",
    "name": "ANADOLU ANONİM TÜRK SİGORTA ŞİRKETİ"
  },
  {
    "code": "ARASE",
    "name": "DOĞU ARAS ENERJİ YATIRIMLARI A.Ş."
  },
  {
    "code": "ARCLK",
    "name": "ARÇELİK A.Ş."
  },
  {
    "code": "ARDYZ",
    "name": "ARD GRUP BİLİŞİM TEKNOLOJİLERİ A.Ş."
  },
  {
    "code": "ARENA",
    "name": "ARENA BİLGİSAYAR SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ARSAN",
    "name": "ARSAN TEKSTİL TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "ARZUM",
    "name": "ARZUM ELEKTRİKLİ EV ALETLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ASELS",
    "name": "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ASGYO",
    "name": "ASCE GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "ASTOR",
    "name": "ASTOR ENERJİ A.Ş."
  },
  {
    "code": "ASUZU",
    "name": "ANADOLU ISUZU OTOMOTİV SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ATAGY",
    "name": "ATA GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "ATAKP",
    "name": "ATAKEY PATATES GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ATATP",
    "name": "ATP YAZILIM VE TEKNOLOJİ A.Ş."
  },
  {
    "code": "ATEKS",
    "name": "AKIN TEKSTİL A.Ş."
  },
  {
    "code": "ATLAS",
    "name": "ATLAS MENKUL KIYMETLER YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "ATSYH",
    "name": "ATLANTİS YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "AVGYO",
    "name": "AVRASYA GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "AVHOL",
    "name": "AVRUPA YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "AVOD",
    "name": "A.V.O.D. KURUTULMUŞ GIDA VE TARIM ÜRÜNLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "AVTUR",
    "name": "AVRASYA PETROL VE TURİSTİK TESİSLER YATIRIMLAR A.Ş."
  },
  {
    "code": "AYCES",
    "name": "ALTIN YUNUS ÇEŞME TURİSTİK TESİSLER A.Ş."
  },
  {
    "code": "AYDEM",
    "name": "AYDEM YENİLENEBİLİR ENERJİ A.Ş."
  },
  {
    "code": "AYEN",
    "name": "AYEN ENERJİ A.Ş."
  },
  {
    "code": "AYES",
    "name": "AYES ÇELİK HASIR VE ÇİT SANAYİ A.Ş."
  },
  {
    "code": "AYGAZ",
    "name": "AYGAZ A.Ş."
  },
  {
    "code": "AZTEK",
    "name": "AZTEK TEKNOLOJİ ÜRÜNLERİ TİCARET A.Ş."
  },
  {
    "code": "BAGFS",
    "name": "BAGFAŞ BANDIRMA GÜBRE FABRİKALARI A.Ş."
  },
  {
    "code": "BAKAB",
    "name": "BAK AMBALAJ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BALAT",
    "name": "BALATACILAR BALATACILIK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BANVT",
    "name": "BANVİT BANDIRMA VİTAMİNLİ YEM SANAYİİ A.Ş."
  },
  {
    "code": "BARMA",
    "name": "BAREM AMBALAJ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BASCM",
    "name": "BAŞTAŞ BAŞKENT ÇİMENTO SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BASGZ",
    "name": "BAŞKENT DOĞALGAZ DAĞITIM GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "BAYRK",
    "name": "BAYRAK EBT TABAN SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BERA",
    "name": "BERA HOLDİNG A.Ş."
  },
  {
    "code": "BEYAZ",
    "name": "BEYAZ FİLO OTO KİRALAMA A.Ş."
  },
  {
    "code": "BFREN",
    "name": "BOSCH FREN SİSTEMLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BIENY",
    "name": "BİEN YAPI ÜRÜNLERİ SANAYİ TURİZM VE TİCARET A.Ş."
  },
  {
    "code": "BIGCH",
    "name": "BÜYÜK ŞEFLER GIDA TURİZM TEKSTİL DANIŞMANLIK ORGANİZASYON EĞİTİM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BIMAS",
    "name": "BİM BİRLEŞİK MAĞAZALAR A.Ş."
  },
  {
    "code": "BIOEN",
    "name": "BİOTREND ÇEVRE VE ENERJİ YATIRIMLARI A.Ş."
  },
  {
    "code": "BIZIM",
    "name": "BİZİM TOPTAN SATIŞ MAĞAZALARI A.Ş."
  },
  {
    "code": "BLCYT",
    "name": "BİLİCİ YATIRIM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BMSCH",
    "name": "BMS ÇELİK HASIR SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BMSTL",
    "name": "BMS BİRLEŞİK METAL SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BNTAS",
    "name": "BANTAŞ BANDIRMA AMBALAJ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "BOBET",
    "name": "BOĞAZİÇİ BETON SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BOSSA",
    "name": "BOSSA TİCARET VE SANAYİ İŞLETMELERİ T.A.Ş."
  },
  {
    "code": "BRISA",
    "name": "BRİSA BRIDGESTONE SABANCI LASTİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BRKO",
    "name": "BİRKO BİRLEŞİK KOYUNLULULAR MENSUCAT TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "BRKSN",
    "name": "BERKOSAN YALITIM VE TECRİT MADDELERİ ÜRETİM VE TİCARET A.Ş."
  },
  {
    "code": "BRKVY",
    "name": "BİRİKİM VARLIK YÖNETİM A.Ş."
  },
  {
    "code": "BRLSM",
    "name": "BİRLEŞİM MÜHENDİSLİK ISITMA SOĞUTMA HAVALANDIRMA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BRMEN",
    "name": "BİRLİK MENSUCAT TİCARET VE SANAYİ İŞLETMESİ A.Ş."
  },
  {
    "code": "BRSAN",
    "name": "BORUSAN MANNESMANN BORU SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BRYAT",
    "name": "BORUSAN YATIRIM VE PAZARLAMA A.Ş."
  },
  {
    "code": "BSOKE",
    "name": "BATISÖKE SÖKE ÇİMENTO SANAYİİ T.A.Ş."
  },
  {
    "code": "BTCIM",
    "name": "BATIÇİM BATI ANADOLU ÇİMENTO SANAYİİ A.Ş."
  },
  {
    "code": "BUCIM",
    "name": "BURSA ÇİMENTO FABRİKASI A.Ş."
  },
  {
    "code": "BURCE",
    "name": "BURÇELİK BURSA ÇELİK DÖKÜM SANAYİİ A.Ş."
  },
  {
    "code": "BURVA",
    "name": "BURÇELİK VANA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BVSAN",
    "name": "BÜLBÜLOĞLU VİNÇ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "BYDNR",
    "name": "BAYDÖNER RESTORANLARI A.Ş."
  },
  {
    "code": "CANTE",
    "name": "ÇAN2 TERMİK A.Ş."
  },
  {
    "code": "CASA",
    "name": "CASA EMTİA PETROL KİMYEVİ VE TÜREVLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "CCOLA",
    "name": "COCA-COLA İÇECEK A.Ş."
  },
  {
    "code": "CELHA",
    "name": "ÇELİK HALAT VE TEL SANAYİİ A.Ş."
  },
  {
    "code": "CEMAS",
    "name": "ÇEMAŞ DÖKÜM SANAYİ A.Ş."
  },
  {
    "code": "CEMTS",
    "name": "ÇEMTAŞ ÇELİK MAKİNA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "CEOEM",
    "name": "CEO EVENT MEDYA A.Ş."
  },
  {
    "code": "CIMSA",
    "name": "ÇİMSA ÇİMENTO SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "CLEBI",
    "name": "ÇELEBİ HAVA SERVİSİ A.Ş."
  },
  {
    "code": "CMBTN",
    "name": "ÇİMBETON HAZIRBETON VE PREFABRİK YAPI ELEMANLARI SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "CMENT",
    "name": "ÇİMENTAŞ İZMİR ÇİMENTO FABRİKASI T.A.Ş."
  },
  {
    "code": "CONSE",
    "name": "CONSUS ENERJİ İŞLETMECİLİĞİ VE HİZMETLERİ A.Ş."
  },
  {
    "code": "COSMO",
    "name": "COSMOS YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "CRDFA",
    "name": "CREDITWEST FAKTORİNG A.Ş."
  },
  {
    "code": "CRFSA",
    "name": "CARREFOURSA CARREFOUR SABANCI TİCARET MERKEZİ A.Ş."
  },
  {
    "code": "CUSAN",
    "name": "ÇUHADAROĞLU METAL SANAYİ VE PAZARLAMA A.Ş."
  },
  {
    "code": "CVKMD",
    "name": "CVK MADEN İŞLETMELERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "CWENE",
    "name": "CW ENERJİ MÜHENDİSLİK TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "DAGHL",
    "name": "DAGİ YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "DAGI",
    "name": "DAGİ GİYİM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "DAPGM",
    "name": "DAP GAYRİMENKUL GELİŞTİRME A.Ş."
  },
  {
    "code": "DARDL",
    "name": "DARDANEL ÖNENTAŞ GIDA SANAYİ A.Ş."
  },
  {
    "code": "DENGE",
    "name": "DENGE YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "DERHL",
    "name": "DERLÜKS YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "DERIM",
    "name": "DERİMOD KONFEKSİYON AYAKKABI DERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "DESA",
    "name": "DESA DERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "DESPC",
    "name": "DESPEC BİLGİSAYAR PAZARLAMA VE TİCARET A.Ş."
  },
  {
    "code": "DEVA",
    "name": "DEVA HOLDİNG A.Ş."
  },
  {
    "code": "DGATE",
    "name": "DATAGATE BİLGİSAYAR MALZEMELERİ TİCARET A.Ş."
  },
  {
    "code": "DGGYO",
    "name": "DOĞUŞ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "DGNMO",
    "name": "DOĞANLAR MOBİLYA GRUBU İMALAT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "DIRIT",
    "name": "DİRİTEKS DİRİLİŞ TEKSTİL SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "DITAS",
    "name": "DİTAŞ DOĞAN YEDEK PARÇA İMALAT VE TEKNİK A.Ş."
  },
  {
    "code": "DMRGD",
    "name": "DMR UNLU MAMULLER ÜRETİM GIDA TOPTAN PERAKENDE İHRACAT A.Ş."
  },
  {
    "code": "DMSAS",
    "name": "DEMİSAŞ DÖKÜM EMAYE MAMÜLLERİ SANAYİ A.Ş."
  },
  {
    "code": "DNISI",
    "name": "DİNAMİK ISI MAKİNA YALITIM MALZEMELERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "DOAS",
    "name": "DOĞUŞ OTOMOTİV SERVİS VE TİCARET A.Ş."
  },
  {
    "code": "DOBUR",
    "name": "DOĞAN BURDA DERGİ YAYINCILIK VE PAZARLAMA A.Ş."
  },
  {
    "code": "DOGUB",
    "name": "DOĞUSAN BORU SANAYİİ VE TİCARET A.Ş."
  },
  {
    "code": "DOHOL",
    "name": "DOĞAN ŞİRKETLER GRUBU HOLDİNG A.Ş."
  },
  {
    "code": "DOKTA",
    "name": "DÖKTAŞ DÖKÜMCÜLÜK TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "DURDO",
    "name": "DURAN DOĞAN BASIM VE AMBALAJ SANAYİ A.Ş."
  },
  {
    "code": "DYOBY",
    "name": "DYO BOYA FABRİKALARI SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "DZGYO",
    "name": "DENİZ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "EBEBK",
    "name": "EBEBEK MAĞAZACILIK A.Ş."
  },
  {
    "code": "ECILC",
    "name": "EİS ECZACIBAŞI İLAÇ SINAİ VE FİNANSAL YATIRIMLAR SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ECZYT",
    "name": "ECZACIBAŞI YATIRIM HOLDİNG ORTAKLIĞI A.Ş."
  },
  {
    "code": "EDATA",
    "name": "E-DATA TEKNOLOJİ PAZARLAMA A.Ş."
  },
  {
    "code": "EDIP",
    "name": "EDİP GAYRİMENKUL YATIRIM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "EGEEN",
    "name": "EGE ENDÜSTRİ VE TİCARET A.Ş."
  },
  {
    "code": "EGEPO",
    "name": "NASMED ÖZEL SAĞLIK HİZMETLERİ TİCARET A.Ş."
  },
  {
    "code": "EGGUB",
    "name": "EGE GÜBRE SANAYİİ A.Ş."
  },
  {
    "code": "EGPRO",
    "name": "EGE PROFİL TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "EGSER",
    "name": "EGE SERAMİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "EKGYO",
    "name": "EMLAK KONUT GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "EKIZ",
    "name": "EKİZ KİMYA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "EKSUN",
    "name": "EKSUN GIDA TARIM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ELITE",
    "name": "ELİTE NATUREL ORGANİK GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "EMKEL",
    "name": "EMEK ELEKTRİK ENDÜSTRİSİ A.Ş."
  },
  {
    "code": "EMNIS",
    "name": "EMİNİŞ AMBALAJ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ENERY",
    "name": "ENERYA ENERJİ A.Ş."
  },
  {
    "code": "ENJSA",
    "name": "ENERJİSA ENERJİ A.Ş."
  },
  {
    "code": "ENKAI",
    "name": "ENKA İNŞAAT VE SANAYİ A.Ş."
  },
  {
    "code": "ENSRI",
    "name": "ENSARİ DERİ GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "EPLAS",
    "name": "EGEPLAST EGE PLASTİK TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "ERBOS",
    "name": "ERBOSAN ERCİYAS BORU SANAYİİ VE TİCARET A.Ş."
  },
  {
    "code": "ERCB",
    "name": "ERCİYAS ÇELİK BORU SANAYİ A.Ş."
  },
  {
    "code": "EREGL",
    "name": "EREĞLİ DEMİR VE ÇELİK FABRİKALARI T.A.Ş."
  },
  {
    "code": "ERSU",
    "name": "ERSU MEYVE VE GIDA SANAYİ A.Ş."
  },
  {
    "code": "ESCAR",
    "name": "ESCAR FİLO KİRALAMA HİZMETLERİ A.Ş."
  },
  {
    "code": "ESCOM",
    "name": "ESCORT TEKNOLOJİ YATIRIM A.Ş."
  },
  {
    "code": "ESEN",
    "name": "ESENBOĞA ELEKTRİK ÜRETİM A.Ş."
  },
  {
    "code": "ETILR",
    "name": "ETİLER GIDA VE TİCARİ YATIRIMLAR SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ETYAT",
    "name": "EURO TREND YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "EUHOL",
    "name": "EURO YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "EUKYO",
    "name": "EURO KAPİTAL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "EUPWR",
    "name": "EUROPOWER ENERJİ VE OTOMASYON TEKNOLOJİLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "EUREN",
    "name": "EUROPEN ENDÜSTRİ İNŞAAT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "EUYO",
    "name": "EURO MENKUL KIYMET YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "EYGYO",
    "name": "EYG GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "FADE",
    "name": "FADE GIDA YATIRIM SANAYİ TİCARET A.Ş."
  },
  {
    "code": "FLAP",
    "name": "FLAP KONGRE TOPLANTI HİZMETLERİ OTOMOTİV VE TURİZM A.Ş."
  },
  {
    "code": "FMIZP",
    "name": "FEDERAL-MOGUL İZMİT PİSTON VE PİM ÜRETİM TESİSLERİ A.Ş."
  },
  {
    "code": "FONET",
    "name": "FONET BİLGİ TEKNOLOJİLERİ A.Ş."
  },
  {
    "code": "FORMT",
    "name": "FORMET METAL VE CAM SANAYİ A.Ş."
  },
  {
    "code": "FORTE",
    "name": "FORTE BİLGİ İLETİŞİM TEKNOLOJİLERİ VE SAVUNMA SANAYİ A.Ş."
  },
  {
    "code": "FRIGO",
    "name": "FRİGO-PAK GIDA MADDELERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "FROTO",
    "name": "FORD OTOMOTİV SANAYİ A.Ş."
  },
  {
    "code": "FZLGY",
    "name": "FUZUL GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "GARAN",
    "name": "TÜRKİYE GARANTİ BANKASI A.Ş."
  },
  {
    "code": "GARFA",
    "name": "GARANTİ FAKTORİNG A.Ş."
  },
  {
    "code": "GEDIK",
    "name": "GEDİK YATIRIM MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "GEDZA",
    "name": "GEDİZ AMBALAJ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "GENIL",
    "name": "GEN İLAÇ VE SAĞLIK ÜRÜNLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "GENTS",
    "name": "GENTAŞ DEKORATİF YÜZEYLER SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "GEREL",
    "name": "GERSAN ELEKTRİK TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "GESAN",
    "name": "GİRİŞİM ELEKTRİK SANAYİ TAAHHÜT VE TİCARET A.Ş."
  },
  {
    "code": "GIPTA",
    "name": "GIPTA OFİS KIRTASİYE VE PROMOSYON ÜRÜNLERİ İMALAT SANAYİ A.Ş."
  },
  {
    "code": "GLBMD",
    "name": "GLOBAL MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "GLCVY",
    "name": "GELECEK VARLIK YÖNETİMİ A.Ş."
  },
  {
    "code": "GLRYH",
    "name": "GÜLER YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "GLYHO",
    "name": "GLOBAL YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "GMTAS",
    "name": "GİMAT MAĞAZACILIK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "GOKNR",
    "name": "GÖKNUR GIDA MADDELERİ ENERJİ İMALAT İTHALAT İHRACAT TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "GOLTS",
    "name": "GÖLTAŞ GÖLLER BÖLGESİ ÇİMENTO SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "GOODY",
    "name": "GOODYEAR LASTİKLERİ T.A.Ş."
  },
  {
    "code": "GOZDE",
    "name": "GÖZDE GİRİŞİM SERMAYESİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "GRNYO",
    "name": "GARANTİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "GRSEL",
    "name": "GÜR-SEL TURİZM TAŞIMACILIK VE SERVİS TİCARET A.Ş."
  },
  {
    "code": "GRTRK",
    "name": "GRAINTURK TARIM A.Ş."
  },
  {
    "code": "GSDDE",
    "name": "GSD DENİZCİLİK GAYRİMENKUL İNŞAAT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "GSDHO",
    "name": "GSD HOLDİNG A.Ş."
  },
  {
    "code": "GUBRF",
    "name": "GÜBRE FABRİKALARI T.A.Ş."
  },
  {
    "code": "GWIND",
    "name": "GALATA WIND ENERJİ A.Ş."
  },
  {
    "code": "GZNMI",
    "name": "GEZİNOMİ SEYAHAT TURİZM TİCARET A.Ş."
  },
  {
    "code": "HALKB",
    "name": "TÜRKİYE HALK BANKASI A.Ş."
  },
  {
    "code": "HATEK",
    "name": "HATEKS HATAY TEKSTİL İŞLETMELERİ A.Ş."
  },
  {
    "code": "HATSN",
    "name": "HAT-SAN GEMİ İNŞAA BAKIM ONARIM DENİZ NAKLİYAT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "HDFGS",
    "name": "HEDEF GİRİŞİM SERMAYESİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "HEDEF",
    "name": "HEDEF HOLDİNG A.Ş."
  },
  {
    "code": "HEKTS",
    "name": "HEKTAŞ TİCARET T.A.Ş."
  },
  {
    "code": "HKTM",
    "name": "HİDROPAR HAREKET KONTROL TEKNOLOJİLERİ MERKEZİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "HLGYO",
    "name": "HALK GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "HTTBT",
    "name": "HİTİT BİLGİSAYAR HİZMETLERİ A.Ş."
  },
  {
    "code": "HUBVC",
    "name": "HUB GİRİŞİM SERMAYESİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "HUNER",
    "name": "HUN YENİLENEBİLİR ENERJİ ÜRETİM A.Ş."
  },
  {
    "code": "HURGZ",
    "name": "HÜRRİYET GAZETECİLİK VE MATBAACILIK A.Ş."
  },
  {
    "code": "ICBCT",
    "name": "ICBC TURKEY BANK A.Ş."
  },
  {
    "code": "ICUGS",
    "name": "ICU GİRİŞİM SERMAYESİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "IDEAS",
    "name": "İDEAL FİNANSAL TEKNOLOJİLER VE DANIŞMANLIK A.Ş."
  },
  {
    "code": "IDGYO",
    "name": "İDEALİST GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "IEYHO",
    "name": "IŞIKLAR ENERJİ VE YAPI HOLDİNG A.Ş."
  },
  {
    "code": "IHAAS",
    "name": "İHLAS HABER AJANSI A.Ş."
  },
  {
    "code": "IHEVA",
    "name": "İHLAS EV ALETLERİ İMALAT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "IHGZT",
    "name": "İHLAS GAZETECİLİK A.Ş."
  },
  {
    "code": "IHLAS",
    "name": "İHLAS HOLDİNG A.Ş."
  },
  {
    "code": "IHLGM",
    "name": "İHLAS GAYRİMENKUL PROJE GELİŞTİRME VE TİCARET A.Ş."
  },
  {
    "code": "IHYAY",
    "name": "İHLAS YAYIN HOLDİNG A.Ş."
  },
  {
    "code": "IMASM",
    "name": "İMAŞ MAKİNA SANAYİ A.Ş."
  },
  {
    "code": "INDES",
    "name": "İNDEKS BİLGİSAYAR SİSTEMLERİ MÜHENDİSLİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "INFO",
    "name": "İNFO YATIRIM MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "INGRM",
    "name": "INGRAM MİCRO BİLİŞİM SİSTEMLERİ A.Ş."
  },
  {
    "code": "INTEM",
    "name": "İNTEMA İNŞAAT VE TESİSAT MALZEMELERİ YATIRIM VE PAZARLAMA A.Ş."
  },
  {
    "code": "INVEO",
    "name": "INVEO YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "INVES",
    "name": "INVESTCO HOLDİNG A.Ş."
  },
  {
    "code": "IPEKE",
    "name": "İPEK DOĞAL ENERJİ KAYNAKLARI ARAŞTIRMA VE ÜRETİM A.Ş."
  },
  {
    "code": "ISATR",
    "name": "TÜRKİYE İŞ BANKASI A.Ş."
  },
  {
    "code": "ISBIR",
    "name": "İŞBİR HOLDİNG A.Ş."
  },
  {
    "code": "ISBTR",
    "name": "TÜRKİYE İŞ BANKASI A.Ş."
  },
  {
    "code": "ISCTR",
    "name": "TÜRKİYE İŞ BANKASI A.Ş."
  },
  {
    "code": "ISDMR",
    "name": "İSKENDERUN DEMİR VE ÇELİK A.Ş."
  },
  {
    "code": "ISFIN",
    "name": "İŞ FİNANSAL KİRALAMA A.Ş."
  },
  {
    "code": "ISGSY",
    "name": "İŞ GİRİŞİM SERMAYESİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "ISGYO",
    "name": "İŞ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "ISKPL",
    "name": "IŞIK PLASTİK SANAYİ VE DIŞ TİCARET PAZARLAMA A.Ş."
  },
  {
    "code": "ISKUR",
    "name": "TÜRKİYE İŞ BANKASI A.Ş."
  },
  {
    "code": "ISMEN",
    "name": "İŞ YATIRIM MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "ISSEN",
    "name": "İŞBİR SENTETİK DOKUMA SANAYİ A.Ş."
  },
  {
    "code": "ISYAT",
    "name": "İŞ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "ITTFH",
    "name": "İTTİFAK HOLDİNG A.Ş."
  },
  {
    "code": "IZENR",
    "name": "İZDEMİR ENERJİ ELEKTRİK ÜRETİM A.Ş."
  },
  {
    "code": "IZFAS",
    "name": "İZMİR FIRÇA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "IZINV",
    "name": "İZ YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "IZMDC",
    "name": "İZMİR DEMİR ÇELİK SANAYİ A.Ş."
  },
  {
    "code": "JANTS",
    "name": "JANTSA JANT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KAPLM",
    "name": "KAPLAMİN AMBALAJ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KAREL",
    "name": "KAREL ELEKTRONİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KARSN",
    "name": "KARSAN OTOMOTİV SANAYİİ VE TİCARET A.Ş."
  },
  {
    "code": "KARTN",
    "name": "KARTONSAN KARTON SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KARYE",
    "name": "KARTAL YENİLENEBİLİR ENERJİ ÜRETİM A.Ş."
  },
  {
    "code": "KATMR",
    "name": "KATMERCİLER ARAÇ ÜSTÜ EKİPMAN SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KCAER",
    "name": "KOCAER ÇELİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KCHOL",
    "name": "KOÇ HOLDİNG A.Ş."
  },
  {
    "code": "KENT",
    "name": "KENT GIDA MADDELERİ SANAYİİ VE TİCARET A.Ş."
  },
  {
    "code": "KERVN",
    "name": "KERVANSARAY YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "KERVT",
    "name": "KEREVİTAŞ GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KFEIN",
    "name": "KAFEİN YAZILIM HİZMETLERİ TİCARET A.Ş."
  },
  {
    "code": "KGYO",
    "name": "KORAY GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "KIMMR",
    "name": "ERSAN ALIŞVERİŞ HİZMETLERİ VE GIDA SANAYİ TİCARET A.Ş."
  },
  {
    "code": "KLGYO",
    "name": "KİLER GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "KLKIM",
    "name": "KALEKİM KİMYEVİ MADDELER SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KLMSN",
    "name": "KLİMASAN KLİMA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KLNMA",
    "name": "TÜRKİYE KALKINMA VE YATIRIM BANKASI A.Ş."
  },
  {
    "code": "KLRHO",
    "name": "KİLER HOLDİNG A.Ş."
  },
  {
    "code": "KLSER",
    "name": "KALESERAMİK ÇANAKKALE KALEBODUR SERAMİK SANAYİ A.Ş."
  },
  {
    "code": "KLSYN",
    "name": "KOLEKSİYON MOBİLYA SANAYİ A.Ş."
  },
  {
    "code": "KMPUR",
    "name": "KİMTEKS POLİÜRETAN SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KNFRT",
    "name": "KONFRUT GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KONKA",
    "name": "KONYA KAĞIT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KONTR",
    "name": "KONTROLMATİK TEKNOLOJİ ENERJİ VE MÜHENDİSLİK A.Ş."
  },
  {
    "code": "KONYA",
    "name": "KONYA ÇİMENTO SANAYİİ A.Ş."
  },
  {
    "code": "KOPOL",
    "name": "KOZA POLYESTER SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KORDS",
    "name": "KORDSA TEKNİK TEKSTİL A.Ş."
  },
  {
    "code": "KOZAA",
    "name": "KOZA ANADOLU METAL MADENCİLİK İŞLETMELERİ A.Ş."
  },
  {
    "code": "KOZAL",
    "name": "KOZA ALTIN İŞLETMELERİ A.Ş."
  },
  {
    "code": "KRDMA",
    "name": "KARDEMİR KARABÜK DEMİR ÇELİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KRDMB",
    "name": "KARDEMİR KARABÜK DEMİR ÇELİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KRDMD",
    "name": "KARDEMİR KARABÜK DEMİR ÇELİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KRGYO",
    "name": "KÖRFEZ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "KRONT",
    "name": "KRON TEKNOLOJİ A.Ş."
  },
  {
    "code": "KRPLS",
    "name": "KOROPLAST TEMİZLİK AMBALAJ ÜRÜNLERİ SANAYİ VE DIŞ TİCARET A.Ş."
  },
  {
    "code": "KRSTL",
    "name": "KRİSTAL KOLA VE MEŞRUBAT SANAYİ TİCARET A.Ş."
  },
  {
    "code": "KRTEK",
    "name": "KARSU TEKSTİL SANAYİİ VE TİCARET A.Ş."
  },
  {
    "code": "KRVGD",
    "name": "KERVAN GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "KSTUR",
    "name": "KUŞTUR KUŞADASI TURİZM ENDÜSTRİSİ A.Ş."
  },
  {
    "code": "KTLEV",
    "name": "KATILIMEVİM TASARRUF FİNANSMAN A.Ş."
  },
  {
    "code": "KTSKR",
    "name": "KÜTAHYA ŞEKER FABRİKASI A.Ş."
  },
  {
    "code": "KUTPO",
    "name": "KÜTAHYA PORSELEN SANAYİ A.Ş."
  },
  {
    "code": "KUVVA",
    "name": "KUVVA GIDA TİCARET VE SANAYİ YATIRIMLARI A.Ş."
  },
  {
    "code": "KUYAS",
    "name": "KUYAŞ YATIRIM A.Ş."
  },
  {
    "code": "KZBGY",
    "name": "KIZILBÜK GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "KZGYO",
    "name": "KUZUGRUP GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "LIDER",
    "name": "LDR TURİZM A.Ş."
  },
  {
    "code": "LIDFA",
    "name": "LİDER FAKTORİNG A.Ş."
  },
  {
    "code": "LINK",
    "name": "LİNK BİLGİSAYAR SİSTEMLERİ YAZILIMI VE DONANIMI SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "LKMNH",
    "name": "LOKMAN HEKİM ENGÜRÜSAĞ SAĞLIK TURİZM EĞİTİM HİZMETLERİ VE İNŞAAT TAAHHÜT A.Ş."
  },
  {
    "code": "LOGO",
    "name": "LOGO YAZILIM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "LUKSK",
    "name": "LÜKS KADİFE TİCARET VE SANAYİİ A.Ş."
  },
  {
    "code": "MAALT",
    "name": "MARMARİS ALTINYUNUS TURİSTİK TESİSLER A.Ş."
  },
  {
    "code": "MACKO",
    "name": "MACKOLİK İNTERNET HİZMETLERİ TİCARET A.Ş."
  },
  {
    "code": "MAGEN",
    "name": "MARGÜN ENERJİ ÜRETİM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MAKIM",
    "name": "MAKİM MAKİNA TEKNOLOJİLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MAKTK",
    "name": "MAKİNA TAKIM ENDÜSTRİSİ A.Ş."
  },
  {
    "code": "MANAS",
    "name": "MANAS ENERJİ YÖNETİMİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MARKA",
    "name": "MARKA YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "MAVI",
    "name": "MAVİ GİYİM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MEDTR",
    "name": "MEDİTERA TIBBİ MALZEME SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MEGAP",
    "name": "MEGA POLİETİLEN KÖPÜK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MEPET",
    "name": "MEPET METRO PETROL VE TESİSLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "MERCN",
    "name": "MERCAN KİMYA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MERIT",
    "name": "MERİT TURİZM YATIRIM VE İŞLETME A.Ş."
  },
  {
    "code": "METRO",
    "name": "METRO TİCARİ VE MALİ YATIRIMLAR HOLDİNG A.Ş."
  },
  {
    "code": "METUR",
    "name": "METEMTUR YATIRIM ENERJİ TURİZM VE İNŞAAT A.Ş."
  },
  {
    "code": "MGROS",
    "name": "MİGROS TİCARET A.Ş."
  },
  {
    "code": "MIATK",
    "name": "MİA TEKNOLOJİ A.Ş."
  },
  {
    "code": "MIPAZ",
    "name": "MİLPA TİCARİ VE SINAİ ÜRÜNLER PAZARLAMA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MMCAS",
    "name": "MMC SANAYİ VE TİCARİ YATIRIMLAR A.Ş."
  },
  {
    "code": "MNDRS",
    "name": "MENDERES TEKSTİL SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MNDTR",
    "name": "MONDİ TURKEY OLUKLU MUKAVVA KAĞIT VE AMBALAJ SANAYİ A.Ş."
  },
  {
    "code": "MOBTL",
    "name": "MOBİLTEL İLETİŞİM HİZMETLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "MPARK",
    "name": "MLP SAĞLIK HİZMETLERİ A.Ş."
  },
  {
    "code": "MRSHL",
    "name": "MARSHALL BOYA VE VERNİK SANAYİİ A.Ş."
  },
  {
    "code": "MSGYO",
    "name": "MİSTRAL GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "MTRKS",
    "name": "MATRİKS BİLGİ DAĞITIM HİZMETLERİ A.Ş."
  },
  {
    "code": "MTRYO",
    "name": "METRO YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "MZHLD",
    "name": "MAZHAR ZORLU HOLDİNG A.Ş."
  },
  {
    "code": "NATEN",
    "name": "NATUREL YENİLENEBİLİR ENERJİ TİCARET A.Ş."
  },
  {
    "code": "NETAS",
    "name": "NETAŞ TELEKOMÜNİKASYON A.Ş."
  },
  {
    "code": "NIBAS",
    "name": "NİĞBAŞ NİĞDE BETON SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "NTGAZ",
    "name": "NATURELGAZ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "NTHOL",
    "name": "NET HOLDİNG A.Ş."
  },
  {
    "code": "NUGYO",
    "name": "NUROL GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "NUHCM",
    "name": "NUH ÇİMENTO SANAYİ A.Ş."
  },
  {
    "code": "OBASE",
    "name": "OBASE BİLGİSAYAR VE DANIŞMANLIK HİZMETLERİ TİCARET A.Ş."
  },
  {
    "code": "ODAS",
    "name": "ODAŞ ELEKTRİK ÜRETİM SANAYİ TİCARET A.Ş."
  },
  {
    "code": "OFSYM",
    "name": "OFİS YEM GIDA SANAYİ TİCARET A.Ş."
  },
  {
    "code": "ONCSM",
    "name": "ONCOSEM ONKOLOJİK SİSTEMLER SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ORCAY",
    "name": "ORÇAY ORTAKÖY ÇAY SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ORGE",
    "name": "ORGE ENERJİ ELEKTRİK TAAHHÜT A.Ş."
  },
  {
    "code": "ORMA",
    "name": "ORMA ORMAN MAHSULLERİ İNTEGRE SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "OSMEN",
    "name": "OSMANLI YATIRIM MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "OSTIM",
    "name": "OSTİM ENDÜSTRİYEL YATIRIMLAR VE İŞLETME A.Ş."
  },
  {
    "code": "OTKAR",
    "name": "OTOKAR OTOMOTİV VE SAVUNMA SANAYİ A.Ş."
  },
  {
    "code": "OTTO",
    "name": "OTTO HOLDİNG A.Ş."
  },
  {
    "code": "OYAKC",
    "name": "OYAK ÇİMENTO FABRİKALARI A.Ş."
  },
  {
    "code": "OYAYO",
    "name": "OYAK YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "OYLUM",
    "name": "OYLUM SINAİ YATIRIMLAR A.Ş."
  },
  {
    "code": "OYYAT",
    "name": "OYAK YATIRIM MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "OZGYO",
    "name": "ÖZDERİCİ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "OZKGY",
    "name": "ÖZAK GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "OZRDN",
    "name": "ÖZERDEN AMBALAJ SANAYİ A.Ş."
  },
  {
    "code": "OZSUB",
    "name": "ÖZSU BALIK ÜRETİM A.Ş."
  },
  {
    "code": "PAGYO",
    "name": "PANORA GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "PAMEL",
    "name": "PAMEL YENİLENEBİLİR ELEKTRİK ÜRETİM A.Ş."
  },
  {
    "code": "PAPIL",
    "name": "PAPİLON SAVUNMA TEKNOLOJİ VE TİCARET A.Ş."
  },
  {
    "code": "PARSN",
    "name": "PARSAN MAKİNA PARÇALARI SANAYİİ A.Ş."
  },
  {
    "code": "PASEU",
    "name": "PASİFİK EURASİA LOJİSTİK DIŞ TİCARET A.Ş."
  },
  {
    "code": "PCILT",
    "name": "PC İLETİŞİM VE MEDYA HİZMETLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "PEGYO",
    "name": "PERA GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "PEKGY",
    "name": "PEKER GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "PENGD",
    "name": "PENGUEN GIDA SANAYİ A.Ş."
  },
  {
    "code": "PENTA",
    "name": "PENTA TEKNOLOJİ ÜRÜNLERİ DAĞITIM TİCARET A.Ş."
  },
  {
    "code": "PETKM",
    "name": "PETKİM PETROKİMYA HOLDİNG A.Ş."
  },
  {
    "code": "PETUN",
    "name": "PINAR ENTEGRE ET VE UN SANAYİİ A.Ş."
  },
  {
    "code": "PGSUS",
    "name": "PEGASUS HAVA TAŞIMACILIĞI A.Ş."
  },
  {
    "code": "PINSU",
    "name": "PINAR SU VE İÇECEK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "PKART",
    "name": "PLASTİKKART AKILLI KART İLETİŞİM SİSTEMLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "PKENT",
    "name": "PETROKENT TURİZM A.Ş."
  },
  {
    "code": "PLTUR",
    "name": "PLATFORM TURİZM TAŞIMACILIK GIDA İNŞAAT TEMİZLİK HİZMETLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "PNLSN",
    "name": "PANELSAN ÇATI CEPHE SİSTEMLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "PNSUT",
    "name": "PINAR SÜT MAMULLERİ SANAYİİ A.Ş."
  },
  {
    "code": "POLHO",
    "name": "POLİSAN HOLDİNG A.Ş."
  },
  {
    "code": "POLTK",
    "name": "POLİTEKNİK METAL SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "PRDGS",
    "name": "PARDUS GİRİŞİM SERMAYESİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "PRKAB",
    "name": "TÜRK PRYSMİAN KABLO VE SİSTEMLERİ A.Ş."
  },
  {
    "code": "PRKME",
    "name": "PARK ELEKTRİK ÜRETİM MADENCİLİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "PRZMA",
    "name": "PRİZMA PRES MATBAACILIK YAYINCILIK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "PSDTC",
    "name": "PERGAMON STATUS DIŞ TİCARET A.Ş."
  },
  {
    "code": "PSGYO",
    "name": "PASİFİK GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "QNBFB",
    "name": "QNB FİNANSBANK A.Ş."
  },
  {
    "code": "QNBFL",
    "name": "QNB FİNANS FİNANSAL KİRALAMA A.Ş."
  },
  {
    "code": "QUAGR",
    "name": "QUA GRANITE HAYAL YAPI VE ÜRÜNLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "RALYH",
    "name": "RAL YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "RAYSG",
    "name": "RAY SİGORTA A.Ş."
  },
  {
    "code": "REEDR",
    "name": "REEDER TEKNOLOJİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "RNPOL",
    "name": "RAİNBOW POLİKARBONAT SANAYİ TİCARET A.Ş."
  },
  {
    "code": "RODRG",
    "name": "RODRİGO TEKSTİL SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "RTALB",
    "name": "RTA LABORATUVARLARI BİYOLOJİK ÜRÜNLER İLAÇ VE MAKİNE SANAYİ TİCARET A.Ş."
  },
  {
    "code": "RUBNS",
    "name": "RUBENİS TEKSTİL SANAYİ TİCARET A.Ş."
  },
  {
    "code": "RYGYO",
    "name": "REYSAŞ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "RYSAS",
    "name": "REYSAŞ TAŞIMACILIK VE LOJİSTİK TİCARET A.Ş."
  },
  {
    "code": "SAFKR",
    "name": "SAFKAR EGE SOĞUTMACILIK KLİMA SOĞUK HAVA TESİSLERİ İHRACAT İTHALAT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SAHOL",
    "name": "HACI ÖMER SABANCI HOLDİNG A.Ş."
  },
  {
    "code": "SAMAT",
    "name": "SARAY MATBAACILIK KAĞITÇILIK KIRTASİYECİLİK TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "SANEL",
    "name": "SAN-EL MÜHENDİSLİK ELEKTRİK TAAHHÜT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SANFM",
    "name": "SANİFOAM ENDÜSTRİ VE TÜKETİM ÜRÜNLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "SANKO",
    "name": "SANKO PAZARLAMA İTHALAT İHRACAT A.Ş."
  },
  {
    "code": "SARKY",
    "name": "SARKUYSAN ELEKTROLİTİK BAKIR SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SASA",
    "name": "SASA POLYESTER SANAYİ A.Ş."
  },
  {
    "code": "SAYAS",
    "name": "SAY YENİLENEBİLİR ENERJİ EKİPMANLARI SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SDTTR",
    "name": "SDT UZAY VE SAVUNMA TEKNOLOJİLERİ A.Ş."
  },
  {
    "code": "SEGYO",
    "name": "ŞEKER GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "SEKFK",
    "name": "ŞEKER FİNANSAL KİRALAMA A.Ş."
  },
  {
    "code": "SEKUR",
    "name": "SEKURO PLASTİK AMBALAJ SANAYİ A.Ş."
  },
  {
    "code": "SELEC",
    "name": "SELÇUK ECZA DEPOSU TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "SELGD",
    "name": "SELÇUK GIDA ENDÜSTRİ İHRACAT İTHALAT A.Ş."
  },
  {
    "code": "SELVA",
    "name": "SELVA GIDA SANAYİ A.Ş."
  },
  {
    "code": "SEYKM",
    "name": "SEYİTLER KİMYA SANAYİ A.Ş."
  },
  {
    "code": "SILVR",
    "name": "SİLVERLİNE ENDÜSTRİ VE TİCARET A.Ş."
  },
  {
    "code": "SISE",
    "name": "TÜRKİYE ŞİŞE VE CAM FABRİKALARI A.Ş."
  },
  {
    "code": "SKBNK",
    "name": "ŞEKERBANK T.A.Ş."
  },
  {
    "code": "SKTAS",
    "name": "SÖKTAŞ TEKSTİL SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SMART",
    "name": "SMARTİKS YAZILIM A.Ş."
  },
  {
    "code": "SMRTG",
    "name": "SMART GÜNEŞ ENERJİSİ TEKNOLOJİLERİ ARAŞTIRMA GELİŞTİRME ÜRETİM SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SNGYO",
    "name": "SİNPAŞ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "SNICA",
    "name": "SANİCA ISI SANAYİ A.Ş."
  },
  {
    "code": "SNKRN",
    "name": "SENKRON SİBER GÜVENLİK YAZILIM VE BİLİŞİM ÇÖZÜMLERİ A.Ş."
  },
  {
    "code": "SNPAM",
    "name": "SÖNMEZ PAMUKLU SANAYİİ A.Ş."
  },
  {
    "code": "SODSN",
    "name": "SODAŞ SODYUM SANAYİİ A.Ş."
  },
  {
    "code": "SOKE",
    "name": "SÖKE DEĞİRMENCİLİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SOKM",
    "name": "ŞOK MARKETLER TİCARET A.Ş."
  },
  {
    "code": "SONME",
    "name": "SÖNMEZ FİLAMENT SENTETİK İPLİK VE ELYAF SANAYİ A.Ş."
  },
  {
    "code": "SRVGY",
    "name": "SERVET GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "SUMAS",
    "name": "SUMAŞ SUNİ TAHTA VE MOBİLYA SANAYİ A.Ş."
  },
  {
    "code": "SUNTK",
    "name": "SUN TEKSTİL SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "SUWEN",
    "name": "SUWEN TEKSTİL SANAYİ PAZARLAMA A.Ş."
  },
  {
    "code": "TARKM",
    "name": "TARKİM BİTKİ KORUMA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "TATEN",
    "name": "TATLIPINAR ENERJİ ÜRETİM A.Ş."
  },
  {
    "code": "TATGD",
    "name": "TAT GIDA SANAYİ A.Ş."
  },
  {
    "code": "TAVHL",
    "name": "TAV HAVALİMANLARI HOLDİNG A.Ş."
  },
  {
    "code": "TBORG",
    "name": "TÜRK TUBORG BİRA VE MALT SANAYİİ A.Ş."
  },
  {
    "code": "TCELL",
    "name": "TURKCELL İLETİŞİM HİZMETLERİ A.Ş."
  },
  {
    "code": "TDGYO",
    "name": "TREND GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "TEKTU",
    "name": "TEK-ART İNŞAAT TİCARET TURİZM SANAYİ VE YATIRIMLAR A.Ş."
  },
  {
    "code": "TERA",
    "name": "TERA YATIRIM MENKUL DEĞERLER A.Ş."
  },
  {
    "code": "TETMT",
    "name": "TETAMAT GIDA YATIRIMLARI A.Ş."
  },
  {
    "code": "TEZOL",
    "name": "EUROPAP TEZOL KAĞIT SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "TGSAS",
    "name": "TGS DIŞ TİCARET A.Ş."
  },
  {
    "code": "THYAO",
    "name": "TÜRK HAVA YOLLARI A.O."
  },
  {
    "code": "TKFEN",
    "name": "TEKFEN HOLDİNG A.Ş."
  },
  {
    "code": "TKNSA",
    "name": "TEKNOSA İÇ VE DIŞ TİCARET A.Ş."
  },
  {
    "code": "TLMAN",
    "name": "TRABZON LİMAN İŞLETMECİLİĞİ A.Ş."
  },
  {
    "code": "TMPOL",
    "name": "TEMAPOL POLİMER PLASTİK VE İNŞAAT SANAYİ TİCARET A.Ş."
  },
  {
    "code": "TMSN",
    "name": "TÜMOSAN MOTOR VE TRAKTÖR SANAYİ A.Ş."
  },
  {
    "code": "TNZTP",
    "name": "TAPDİ OKSİJEN ÖZEL SAĞLIK VE EĞİTİM HİZMETLERİ SANAYİ TİCARET A.Ş."
  },
  {
    "code": "TOASO",
    "name": "TOFAŞ TÜRK OTOMOBİL FABRİKASI A.Ş."
  },
  {
    "code": "TRCAS",
    "name": "TURCAS PETROL A.Ş."
  },
  {
    "code": "TRGYO",
    "name": "TORUNLAR GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "TRILC",
    "name": "TURK İLAÇ VE SERUM SANAYİ A.Ş."
  },
  {
    "code": "TSGYO",
    "name": "TSKB GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "TSKB",
    "name": "TÜRKİYE SINAİ KALKINMA BANKASI A.Ş."
  },
  {
    "code": "TTKOM",
    "name": "TÜRK TELEKOMÜNİKASYON A.Ş."
  },
  {
    "code": "TTRAK",
    "name": "TÜRK TRAKTÖR VE ZİRAAT MAKİNELERİ A.Ş."
  },
  {
    "code": "TUCLK",
    "name": "TUĞÇELİK ALÜMİNYUM VE METAL MAMÜLLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "TUKAS",
    "name": "TUKAŞ GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "TUPRS",
    "name": "TÜPRAŞ-TÜRKİYE PETROL RAFİNERİLERİ A.Ş."
  },
  {
    "code": "TUREX",
    "name": "TUREKS TURİZM TAŞIMACILIK A.Ş."
  },
  {
    "code": "TURGG",
    "name": "TÜRKER PROJE GAYRİMENKUL VE YATIRIM GELİŞTİRME A.Ş."
  },
  {
    "code": "TURSG",
    "name": "TÜRKİYE SİGORTA A.Ş."
  },
  {
    "code": "UFUK",
    "name": "UFUK YATIRIM YÖNETİM VE GAYRİMENKUL A.Ş."
  },
  {
    "code": "ULAS",
    "name": "ULAŞLAR TURİZM ENERJİ TARIM GIDA VE İNŞAAT YATIRIMLARI A.Ş."
  },
  {
    "code": "ULKER",
    "name": "ÜLKER BİSKÜVİ SANAYİ A.Ş."
  },
  {
    "code": "ULUFA",
    "name": "ULUSAL FAKTORİNG A.Ş."
  },
  {
    "code": "ULUSE",
    "name": "ULUSOY ELEKTRİK İMALAT TAAHHÜT VE TİCARET A.Ş."
  },
  {
    "code": "ULUUN",
    "name": "ULUSOY UN SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "UMPAS",
    "name": "UMPAŞ HOLDİNG A.Ş."
  },
  {
    "code": "UNLU",
    "name": "ÜNLÜ YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "USAK",
    "name": "UŞAK SERAMİK SANAYİ A.Ş."
  },
  {
    "code": "UZERB",
    "name": "UZERTAŞ BOYA SANAYİ TİCARET VE YATIRIM A.Ş."
  },
  {
    "code": "VAKBN",
    "name": "TÜRKİYE VAKIFLAR BANKASI T.A.O."
  },
  {
    "code": "VAKFN",
    "name": "VAKIF FİNANSAL KİRALAMA A.Ş."
  },
  {
    "code": "VAKKO",
    "name": "VAKKO TEKSTİL VE HAZIR GİYİM SANAYİ İŞLETMELERİ A.Ş."
  },
  {
    "code": "VANGD",
    "name": "VANET GIDA SANAYİ İÇ VE DIŞ TİCARET A.Ş."
  },
  {
    "code": "VBTYZ",
    "name": "VBT YAZILIM A.Ş."
  },
  {
    "code": "VERTU",
    "name": "VERUSATURK GİRİŞİM SERMAYESİ YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "VERUS",
    "name": "VERUSA HOLDİNG A.Ş."
  },
  {
    "code": "VESBE",
    "name": "VESTEL BEYAZ EŞYA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "VESTL",
    "name": "VESTEL ELEKTRONİK SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "VKFYO",
    "name": "VAKIF MENKUL KIYMET YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "VKGYO",
    "name": "VAKIF GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "VKING",
    "name": "VİKİNG KAĞIT VE SELÜLOZ A.Ş."
  },
  {
    "code": "YAPRK",
    "name": "YAPRAK SÜT VE BESİ ÇİFTLİKLERİ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "YATAS",
    "name": "YATAŞ YATAK VE YORGAN SANAYİ TİCARET A.Ş."
  },
  {
    "code": "YAYLA",
    "name": "YAYLA ENERJİ ÜRETİM TURİZM VE İNŞAAT TİCARET A.Ş."
  },
  {
    "code": "YBTAS",
    "name": "YİBİTAŞ YOZGAT İŞÇİ BİRLİĞİ İNŞAAT MALZEMELERİ TİCARET VE SANAYİ A.Ş."
  },
  {
    "code": "YEOTK",
    "name": "YEO TEKNOLOJİ ENERJİ VE ENDÜSTRİ A.Ş."
  },
  {
    "code": "YESIL",
    "name": "YEŞİL YATIRIM HOLDİNG A.Ş."
  },
  {
    "code": "YGGYO",
    "name": "YENİ GİMAT GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "YGYO",
    "name": "YEŞİL GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "YKBNK",
    "name": "YAPI VE KREDİ BANKASI A.Ş."
  },
  {
    "code": "YKSLN",
    "name": "YÜKSELEN ÇELİK A.Ş."
  },
  {
    "code": "YONGA",
    "name": "YONGA MOBİLYA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "YUNSA",
    "name": "YÜNSA YÜNLÜ SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "YYAPI",
    "name": "YEŞİL YAPI ENDÜSTRİSİ A.Ş."
  },
  {
    "code": "YYLGD",
    "name": "YAYLA AGRO GIDA SANAYİ VE TİCARET A.Ş."
  },
  {
    "code": "ZEDUR",
    "name": "ZEDUR ENERJİ ELEKTRİK ÜRETİM A.Ş."
  },
  {
    "code": "ZOREN",
    "name": "ZORLU ENERJİ ELEKTRİK ÜRETİM A.Ş."
  },
  {
    "code": "ZRGYO",
    "name": "ZİRAAT GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş."
  },
  {
    "code": "APX30",
    "name": "Ak Portföy Bıst 30 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "APBDL",
    "name": "Ak Portföy Bıst Banka Dışı Likit 10 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "APLIB",
    "name": "Ak Portföy Bıst Likit Banka Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "OPX30",
    "name": "Osmanlı Portföy Bıst 30 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "GLDTR",
    "name": "QNB Finans Portföy Altın Katılım Borsa Yatırım Fonu"
  },
  {
    "code": "USDTR",
    "name": "QNB Finans Portföy Amerikan Doları Yabancı Borsa Yatırım Fonu"
  },
  {
    "code": "DJIST",
    "name": "QNB Finans Portföy Dow Jones İstanbul 20 Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "GMSTR",
    "name": "QNB Finans Portföy Gümüş Katılım Borsa Yatırım Fonu"
  },
  {
    "code": "ZGOLD",
    "name": "Ziraat Portföy Altın Katılım Borsa Yatırım Fonu"
  },
  {
    "code": "ZPX30",
    "name": "Ziraat Portföy Bıst 30 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "Z30EA",
    "name": "Ziraat Portföy Bıst 30 Eşit Ağırlıklı Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "ZELOT",
    "name": "Ziraat Portföy Bıst 50-30 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "ZPBDL",
    "name": "Ziraat Portföy Bıst Banka Dışı Likit 10 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "ZPLIB",
    "name": "Ziraat Portföy Bıst Likit Banka Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "ZSR25",
    "name": "Ziraat Portföy Bıst Sürdürülebilirlik 25 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "Z30KP",
    "name": "Ziraat Portföy Katılım 30 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "Z30KE",
    "name": "Ziraat Portföy Katılım 30 Eşit Ağırlıklı Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "ZRE20",
    "name": "Ziraat Portföy Risk Eşit Banka Dışı 20 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "ZTM15",
    "name": "Ziraat Portföy Yıldız Pazar Likit Temettü Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  },
  {
    "code": "ZPT10",
    "name": "Ziraat Portföy Yıldız Pazar Teknoloji Ve İletişim 10 Endeksi Hisse Senedi Yoğun Borsa Yatırım Fonu"
  }
]



POPULAR_ETFLER = [
  {"code": "SPY", "name": "SPDR S&P 500 ETF Trust"},
  {"code": "QQQ", "name": "Invesco QQQ Trust (Nasdaq 100)"},
  {"code": "VOO", "name": "Vanguard S&P 500 ETF"},
  {"code": "VTI", "name": "Vanguard Total Stock Market ETF"},
  {"code": "IVV", "name": "iShares Core S&P 500 ETF"},
  {"code": "DIA", "name": "SPDR Dow Jones Industrial Average ETF"},
  {"code": "IWM", "name": "iShares Russell 2000 ETF"},
  {"code": "SMH", "name": "VanEck Semiconductor ETF"},
  {"code": "SOXX", "name": "iShares Semiconductor ETF"},
  {"code": "ARKK", "name": "ARK Innovation ETF"},
  {"code": "SCHD", "name": "Schwab U.S. Dividend Equity ETF"},
  {"code": "VYM", "name": "Vanguard High Dividend Yield ETF"},
  {"code": "XLK", "name": "Technology Select Sector SPDR Fund"},
  {"code": "XLF", "name": "Financial Select Sector SPDR Fund"},
  {"code": "XLE", "name": "Energy Select Sector SPDR Fund"},
  {"code": "XLV", "name": "Health Care Select Sector SPDR Fund"},
  {"code": "XLI", "name": "Industrial Select Sector SPDR Fund"},
  {"code": "XLY", "name": "Consumer Discretionary Select SPDR"},
  {"code": "XLP", "name": "Consumer Staples Select SPDR"},
  {"code": "XLU", "name": "Utilities Select Sector SPDR Fund"},
  {"code": "XLB", "name": "Materials Select Sector SPDR Fund"},
  {"code": "VNQ", "name": "Vanguard Real Estate ETF"},
  {"code": "GLD", "name": "SPDR Gold Shares ETF"},
  {"code": "IAU", "name": "iShares Gold Trust ETF"},
  {"code": "SLV", "name": "iShares Silver Trust ETF"},
  {"code": "TLT", "name": "iShares 20+ Year Treasury Bond ETF"},
  {"code": "BND", "name": "Vanguard Total Bond Market ETF"},
  {"code": "AGG", "name": "iShares Core U.S. Aggregate Bond ETF"},
  {"code": "JEPI", "name": "JPMorgan Equity Premium Income ETF"},
  {"code": "JEPQ", "name": "JPMorgan Nasdaq Equity Premium Income ETF"},
  {"code": "TQQQ", "name": "ProShares UltraPro QQQ (3x)"},
  {"code": "SQQQ", "name": "ProShares UltraPro Short QQQ (-3x)"},
  {"code": "SOXL", "name": "Direxion Daily Semiconductor Bull 3X"},
  {"code": "VGT", "name": "Vanguard Information Technology ETF"},
  {"code": "VWO", "name": "Vanguard FTSE Emerging Markets ETF"},
  {"code": "VEA", "name": "Vanguard FTSE Developed Markets ETF"},
  {"code": "VT", "name": "Vanguard Total World Stock ETF"},
  {"code": "VXUS", "name": "Vanguard Total International Stock ETF"},
  {"code": "IBIT", "name": "iShares Bitcoin Trust ETF"},
  {"code": "FBTC", "name": "Fidelity Wise Origin Bitcoin Fund"},
  {"code": "ETHA", "name": "iShares Ethereum Trust ETF"},
  {"code": "URA", "name": "Global X Uranium ETF"},
  {"code": "LIT", "name": "Global X Lithium & Battery Tech ETF"},
  {"code": "TAN", "name": "Invesco Solar ETF"},
  {"code": "ICLN", "name": "iShares Global Clean Energy ETF"},
  {"code": "XBI", "name": "SPDR S&P Biotech ETF"}
]

POPULAR_FONLAR = [
  {
    "code": "TI3",
    "name": "İş Portföy BIST Teknoloji Ağırlıklı Sınırlamalı Hisse Fonu"
  },
  {
    "code": "TCD",
    "name": "Tacirler Portföy Değişken Fon"
  },
  {
    "code": "MAC",
    "name": "Marmara Capital Portföy Hisse Senedi Fonu"
  },
  {
    "code": "IIH",
    "name": "İstanbul Portföy Üçüncü Hisse Senedi Fonu"
  },
  {
    "code": "AFT",
    "name": "Ak Portföy Yeni Teknolojiler Yabancı Hisse Senedi Fonu"
  },
  {
    "code": "YAY",
    "name": "Yapı Kredi Portföy Koç Holding İştirak Fonu"
  },
  {
    "code": "TUA",
    "name": "Tacirler Portföy Altın Fonu"
  },
  {
    "code": "KZL",
    "name": "Kuveyt Türk Portföy Altın Katılım Fonu"
  },
  {
    "code": "ZP6",
    "name": "Ziraat Portföy Altın Katılım Fonu"
  },
  {
    "code": "IDH",
    "name": "İş Portföy BIST 100 Dışı Şirketler Hisse Fonu"
  },
  {
    "code": "BIO",
    "name": "QNB Finans Portföy Teknoloji Sektörü Fonu"
  },
  {
    "code": "OJT",
    "name": "QNB Finans Portföy Sağlık Sektörü Fonu"
  },
  {
    "code": "IPB",
    "name": "İstanbul Portföy Birinci Değişken Fon"
  },
  {
    "code": "GMR",
    "name": "Gedik Portföy İkinci Hisse Senedi Fonu"
  },
  {
    "code": "BUY",
    "name": "Bursa Portföy Birinci Hisse Senedi Fonu"
  },
  {
    "code": "KLU",
    "name": "Kalyon Portföy Para Piyasası Fonu"
  },
  {
    "code": "NVB",
    "name": "Neo Portföy Birinci Değişken Fon"
  },
  {
    "code": "NRC",
    "name": "Neo Portföy İkinci Hisse Senedi Fonu"
  },
  {
    "code": "ZPE",
    "name": "Ziraat Portföy Katılım Endeksi Fonu"
  },
  {
    "code": "MPS",
    "name": "Mükafat Portföy Katılım Fonu"
  },
  {
    "code": "CPU",
    "name": "Ak Portföy Fintek ve Blokzincir Fonu"
  },
  {
    "code": "IVY",
    "name": "İstanbul Portföy Blockchain Teknolojileri Fonu"
  },
  {
    "code": "AFA",
    "name": "Ak Portföy Amerika Yabancı Hisse Senedi Fonu"
  },
  {
    "code": "AFV",
    "name": "Ak Portföy Avrupa Yabancı Hisse Senedi Fonu"
  },
  {
    "code": "GBG",
    "name": "Garanti Portföy Birinci Değişken Fon"
  },
  {
    "code": "GTA",
    "name": "Garanti Portföy Altın Fonu"
  },
  {
    "code": "GGK",
    "name": "Garanti Portföy Kısa Vadeli Borçlanma Araçları Fonu"
  },
  {
    "code": "PPZ",
    "name": "Azimut Portföy Para Piyasası Fonu"
  },
  {
    "code": "PAL",
    "name": "Perform Portföy Birinci Değişken Fon"
  },
  {
    "code": "TAU",
    "name": "İş Portföy Bankacılık Endeksi Hisse Fonu"
  },
  {
    "code": "TTE",
    "name": "İş Portföy BIST Teknoloji Endeksi Fonu"
  },
  {
    "code": "IKP",
    "name": "İş Portföy Kıymetli Madenler Fonu"
  },
  {
    "code": "TTA",
    "name": "İş Portföy Altın Fonu"
  },
  {
    "code": "YKT",
    "name": "Yapı Kredi Portföy BIST 30 Fonu"
  },
  {
    "code": "YTD",
    "name": "Yapı Kredi Portföy Eurobond Borçlanma Fonu"
  },
  {
    "code": "TLH",
    "name": "TEB Portföy BIST 30 Dışı Fon"
  },
  {
    "code": "TGE",
    "name": "İş Portföy Emtia Yabancı BYF Fon Sepeti Fonu"
  }
]


OTHER_LIST = {
    "ETF": POPULAR_ETFLER,
    "Fon": POPULAR_FONLAR,
    "ABD": [
    {
        "code": "TSM",
        "name": "Taiwan Semiconductor Manufacturing (TSMC)"
    },
    {
        "code": "MMM",
        "name": "3M"
    },
    {
        "code": "AOS",
        "name": "A. O. Smith"
    },
    {
        "code": "ABT",
        "name": "Abbott Laboratories"
    },
    {
        "code": "ABBV",
        "name": "AbbVie"
    },
    {
        "code": "ACN",
        "name": "Accenture"
    },
    {
        "code": "ADBE",
        "name": "Adobe Inc."
    },
    {
        "code": "AMD",
        "name": "Advanced Micro Devices"
    },
    {
        "code": "AES",
        "name": "AES Corporation"
    },
    {
        "code": "AFL",
        "name": "Aflac"
    },
    {
        "code": "A",
        "name": "Agilent Technologies"
    },
    {
        "code": "APD",
        "name": "Air Products"
    },
    {
        "code": "ABNB",
        "name": "Airbnb"
    },
    {
        "code": "AKAM",
        "name": "Akamai Technologies"
    },
    {
        "code": "ALB",
        "name": "Albemarle Corporation"
    },
    {
        "code": "ARE",
        "name": "Alexandria Real Estate Equities"
    },
    {
        "code": "ALGN",
        "name": "Align Technology"
    },
    {
        "code": "ALLE",
        "name": "Allegion"
    },
    {
        "code": "LNT",
        "name": "Alliant Energy"
    },
    {
        "code": "ALL",
        "name": "Allstate"
    },
    {
        "code": "GOOGL",
        "name": "Alphabet Inc. (Class A)"
    },
    {
        "code": "GOOG",
        "name": "Alphabet Inc. (Class C)"
    },
    {
        "code": "MO",
        "name": "Altria"
    },
    {
        "code": "AMZN",
        "name": "Amazon.com"
    },
    {
        "code": "AMCR",
        "name": "Amcor"
    },
    {
        "code": "AEE",
        "name": "Ameren"
    },
    {
        "code": "AAL",
        "name": "American Airlines"
    },
    {
        "code": "AEP",
        "name": "American Electric Power"
    },
    {
        "code": "AXP",
        "name": "American Express"
    },
    {
        "code": "AIG",
        "name": "American International Group"
    },
    {
        "code": "AMT",
        "name": "American Tower"
    },
    {
        "code": "AWK",
        "name": "American Water Works"
    },
    {
        "code": "AMP",
        "name": "Ameriprise Financial"
    },
    {
        "code": "AME",
        "name": "AMETEK"
    },
    {
        "code": "AMGN",
        "name": "Amgen"
    },
    {
        "code": "APH",
        "name": "Amphenol"
    },
    {
        "code": "ADI",
        "name": "Analog Devices"
    },
    {
        "code": "ANSS",
        "name": "Ansys"
    },
    {
        "code": "AON",
        "name": "Aon"
    },
    {
        "code": "APA",
        "name": "APA Corporation"
    },
    {
        "code": "AAPL",
        "name": "Apple Inc."
    },
    {
        "code": "AMAT",
        "name": "Applied Materials"
    },
    {
        "code": "APTV",
        "name": "Aptiv"
    },
    {
        "code": "ACGL",
        "name": "Arch Capital Group"
    },
    {
        "code": "ADM",
        "name": "Archer-Daniels-Midland"
    },
    {
        "code": "ANET",
        "name": "Arista Networks"
    },
    {
        "code": "AJG",
        "name": "Arthur J. Gallagher & Co."
    },
    {
        "code": "AIZ",
        "name": "Assurant"
    },
    {
        "code": "T",
        "name": "AT&T"
    },
    {
        "code": "ATO",
        "name": "Atmos Energy"
    },
    {
        "code": "ADSK",
        "name": "Autodesk"
    },
    {
        "code": "ADP",
        "name": "Automatic Data Processing"
    },
    {
        "code": "AZO",
        "name": "AutoZone"
    },
    {
        "code": "AVB",
        "name": "AvalonBay Communities"
    },
    {
        "code": "AVY",
        "name": "Avery Dennison"
    },
    {
        "code": "AXON",
        "name": "Axon Enterprise"
    },
    {
        "code": "BKR",
        "name": "Baker Hughes"
    },
    {
        "code": "BALL",
        "name": "Ball Corporation"
    },
    {
        "code": "BAC",
        "name": "Bank of America"
    },
    {
        "code": "BK",
        "name": "Bank of New York Mellon"
    },
    {
        "code": "BBY",
        "name": "Best Buy"
    },
    {
        "code": "BIIB",
        "name": "Biogen"
    },
    {
        "code": "BLK",
        "name": "BlackRock"
    },
    {
        "code": "BX",
        "name": "Blackstone Inc."
    },
    {
        "code": "BA",
        "name": "Boeing"
    },
    {
        "code": "BKNG",
        "name": "Booking Holdings"
    },
    {
        "code": "BWA",
        "name": "BorgWarner"
    },
    {
        "code": "BSX",
        "name": "Boston Scientific"
    },
    {
        "code": "BMY",
        "name": "Bristol Myers Squibb"
    },
    {
        "code": "AVGO",
        "name": "Broadcom"
    },
    {
        "code": "BR",
        "name": "Broadridge Financial Solutions"
    },
    {
        "code": "BRO",
        "name": "Brown & Brown"
    },
    {
        "code": "BF.B",
        "name": "Brown-Forman"
    },
    {
        "code": "BLDR",
        "name": "Builders FirstSource"
    },
    {
        "code": "BG",
        "name": "Bunge Global"
    },
    {
        "code": "BXP",
        "name": "BXP, Inc."
    },
    {
        "code": "CHRW",
        "name": "C.H. Robinson"
    },
    {
        "code": "CDNS",
        "name": "Cadence Design Systems"
    },
    {
        "code": "CPT",
        "name": "Camden Property Trust"
    },
    {
        "code": "CPB",
        "name": "Campbell's"
    },
    {
        "code": "COF",
        "name": "Capital One"
    },
    {
        "code": "CAH",
        "name": "Cardinal Health"
    },
    {
        "code": "CCL",
        "name": "Carnival"
    },
    {
        "code": "CARR",
        "name": "Carrier Global"
    },
    {
        "code": "CAT",
        "name": "Caterpillar Inc."
    },
    {
        "code": "CBOE",
        "name": "Cboe Global Markets"
    },
    {
        "code": "CBRE",
        "name": "CBRE Group"
    },
    {
        "code": "CDW",
        "name": "CDW Corporation"
    },
    {
        "code": "CE",
        "name": "Celanese"
    },
    {
        "code": "COR",
        "name": "Cencora"
    },
    {
        "code": "CNC",
        "name": "Centene Corporation"
    },
    {
        "code": "CNX",
        "name": "CNX Resources"
    },
    {
        "code": "CDAY",
        "name": "Ceridian HCM Holding"
    },
    {
        "code": "CF",
        "name": "CF Industries"
    },
    {
        "code": "CRL",
        "name": "Charles River Laboratories"
    },
    {
        "code": "SCHW",
        "name": "Charles Schwab Corporation"
    },
    {
        "code": "CHTR",
        "name": "Charter Communications"
    },
    {
        "code": "CVX",
        "name": "Chevron"
    },
    {
        "code": "CMG",
        "name": "Chipotle Mexican Grill"
    },
    {
        "code": "CB",
        "name": "Chubb"
    },
    {
        "code": "CHD",
        "name": "Church & Dwight"
    },
    {
        "code": "CI",
        "name": "Cigna"
    },
    {
        "code": "CINF",
        "name": "Cincinnati Financial"
    },
    {
        "code": "CTAS",
        "name": "Cintas"
    },
    {
        "code": "CSCO",
        "name": "Cisco Systems"
    },
    {
        "code": "C",
        "name": "Citigroup"
    },
    {
        "code": "CFG",
        "name": "Citizens Financial Group"
    },
    {
        "code": "CLX",
        "name": "Clorox"
    },
    {
        "code": "CME",
        "name": "CME Group"
    },
    {
        "code": "CMS",
        "name": "CMS Energy"
    },
    {
        "code": "KO",
        "name": "Coca-Cola"
    },
    {
        "code": "CTSH",
        "name": "Cognizant"
    },
    {
        "code": "CL",
        "name": "Colgate-Palmolive"
    },
    {
        "code": "CMCSA",
        "name": "Comcast"
    },
    {
        "code": "CAG",
        "name": "Conagra Brands"
    },
    {
        "code": "COP",
        "name": "ConocoPhillips"
    },
    {
        "code": "ED",
        "name": "Consolidated Edison"
    },
    {
        "code": "STZ",
        "name": "Constellation Brands"
    },
    {
        "code": "CEG",
        "name": "Constellation Energy"
    },
    {
        "code": "COO",
        "name": "Cooper Companies"
    },
    {
        "code": "CPRT",
        "name": "Copart"
    },
    {
        "code": "GLW",
        "name": "Corning"
    },
    {
        "code": "COST",
        "name": "Costco"
    },
    {
        "code": "CTVA",
        "name": "Corteva"
    },
    {
        "code": "CSGP",
        "name": "CoStar Group"
    },
    {
        "code": "COWZ",
        "name": "Pacer US Cash Cows 100 ETF"
    },
    {
        "code": "CRWD",
        "name": "CrowdStrike"
    },
    {
        "code": "CCI",
        "name": "Crown Castle"
    },
    {
        "code": "CSX",
        "name": "CSX Corporation"
    },
    {
        "code": "CMI",
        "name": "Cummins"
    },
    {
        "code": "CVS",
        "name": "CVS Health"
    },
    {
        "code": "DHR",
        "name": "Danaher Corporation"
    },
    {
        "code": "DRI",
        "name": "Darden Restaurants"
    },
    {
        "code": "DVA",
        "name": "DaVita"
    },
    {
        "code": "DAY",
        "name": "Dayforce"
    },
    {
        "code": "DECK",
        "name": "Deckers Brands"
    },
    {
        "code": "DE",
        "name": "Deere & Company"
    },
    {
        "code": "DELL",
        "name": "Dell Technologies"
    },
    {
        "code": "DAL",
        "name": "Delta Air Lines"
    },
    {
        "code": "DVN",
        "name": "Devon Energy"
    },
    {
        "code": "DXCM",
        "name": "Dexcom"
    },
    {
        "code": "FANG",
        "name": "Diamondback Energy"
    },
    {
        "code": "DLR",
        "name": "Digital Realty"
    },
    {
        "code": "DFS",
        "name": "Discover Financial"
    },
    {
        "code": "DG",
        "name": "Dollar General"
    },
    {
        "code": "DLTR",
        "name": "Dollar Tree"
    },
    {
        "code": "D",
        "name": "Dominion Energy"
    },
    {
        "code": "DPZ",
        "name": "Domino's"
    },
    {
        "code": "DOV",
        "name": "Dover Corporation"
    },
    {
        "code": "DOW",
        "name": "Dow Inc."
    },
    {
        "code": "DHI",
        "name": "D.R. Horton"
    },
    {
        "code": "DTE",
        "name": "DTE Energy"
    },
    {
        "code": "DUK",
        "name": "Duke Energy"
    },
    {
        "code": "DD",
        "name": "DuPont"
    },
    {
        "code": "EMN",
        "name": "Eastman Chemical"
    },
    {
        "code": "ETN",
        "name": "Eaton Corporation"
    },
    {
        "code": "EBAY",
        "name": "eBay Inc."
    },
    {
        "code": "ECL",
        "name": "Ecolab"
    },
    {
        "code": "EIX",
        "name": "Edison International"
    },
    {
        "code": "EW",
        "name": "Edwards Lifesciences"
    },
    {
        "code": "EA",
        "name": "Electronic Arts"
    },
    {
        "code": "ELV",
        "name": "Elevance Health"
    },
    {
        "code": "EME",
        "name": "Emcor"
    },
    {
        "code": "EMR",
        "name": "Emerson Electric"
    },
    {
        "code": "ENPH",
        "name": "Enphase Energy"
    },
    {
        "code": "ETR",
        "name": "Entergy"
    },
    {
        "code": "EOG",
        "name": "EOG Resources"
    },
    {
        "code": "EPAM",
        "name": "EPAM Systems"
    },
    {
        "code": "EQT",
        "name": "EQT Corporation"
    },
    {
        "code": "EFX",
        "name": "Equifax"
    },
    {
        "code": "EQIX",
        "name": "Equinix"
    },
    {
        "code": "EQR",
        "name": "Equity Residential"
    },
    {
        "code": "ERIE",
        "name": "Erie Indemnity"
    },
    {
        "code": "ESS",
        "name": "Essex Property Trust"
    },
    {
        "code": "EL",
        "name": "Estée Lauder Companies"
    },
    {
        "code": "ETSY",
        "name": "Etsy"
    },
    {
        "code": "EG",
        "name": "Everest Group"
    },
    {
        "code": "EVRG",
        "name": "Evergy"
    },
    {
        "code": "ES",
        "name": "Eversource Energy"
    },
    {
        "code": "EXC",
        "name": "Exelon"
    },
    {
        "code": "EXPE",
        "name": "Expedia Group"
    },
    {
        "code": "EXPD",
        "name": "Expeditors International"
    },
    {
        "code": "EXR",
        "name": "Extra Space Storage"
    },
    {
        "code": "XOM",
        "name": "Exxon Mobil"
    },
    {
        "code": "FFIV",
        "name": "F5, Inc."
    },
    {
        "code": "FDS",
        "name": "FactSet"
    },
    {
        "code": "FICO",
        "name": "Fair Isaac"
    },
    {
        "code": "FAST",
        "name": "Fastenal"
    },
    {
        "code": "FRT",
        "name": "Federal Realty Investment Trust"
    },
    {
        "code": "FDX",
        "name": "FedEx"
    },
    {
        "code": "FIS",
        "name": "Fidelity National Information Services"
    },
    {
        "code": "FITB",
        "name": "Fifth Third Bank"
    },
    {
        "code": "FSLR",
        "name": "First Solar"
    },
    {
        "code": "FE",
        "name": "FirstEnergy"
    },
    {
        "code": "FI",
        "name": "Fiserv"
    },
    {
        "code": "FMC",
        "name": "FMC Corporation"
    },
    {
        "code": "F",
        "name": "Ford Motor"
    },
    {
        "code": "FTNT",
        "name": "Fortinet"
    },
    {
        "code": "FTV",
        "name": "Fortive"
    },
    {
        "code": "FOXA",
        "name": "Fox Corporation (Class A)"
    },
    {
        "code": "FOX",
        "name": "Fox Corporation (Class B)"
    },
    {
        "code": "BEN",
        "name": "Franklin Resources"
    },
    {
        "code": "FCX",
        "name": "Freeport-McMoRan"
    },
    {
        "code": "GRMN",
        "name": "Garmin"
    },
    {
        "code": "IT",
        "name": "Gartner"
    },
    {
        "code": "GE",
        "name": "GE Aerospace"
    },
    {
        "code": "GEHC",
        "name": "GE HealthCare"
    },
    {
        "code": "GEV",
        "name": "GE Vernova"
    },
    {
        "code": "GEN",
        "name": "Gen Digital"
    },
    {
        "code": "GNRC",
        "name": "Generac"
    },
    {
        "code": "GD",
        "name": "General Dynamics"
    },
    {
        "code": "GIS",
        "name": "General Mills"
    },
    {
        "code": "GM",
        "name": "General Motors"
    },
    {
        "code": "GPC",
        "name": "Genuine Parts Company"
    },
    {
        "code": "GILD",
        "name": "Gilead Sciences"
    },
    {
        "code": "GPN",
        "name": "Global Payments"
    },
    {
        "code": "GL",
        "name": "Globe Life"
    },
    {
        "code": "GDDY",
        "name": "GoDaddy"
    },
    {
        "code": "GS",
        "name": "Goldman Sachs"
    },
    {
        "code": "HAL",
        "name": "Halliburton"
    },
    {
        "code": "HIG",
        "name": "Hartford"
    },
    {
        "code": "HAS",
        "name": "Hasbro"
    },
    {
        "code": "HCA",
        "name": "HCA Healthcare"
    },
    {
        "code": "DOC",
        "name": "Healthpeak Properties"
    },
    {
        "code": "HSIC",
        "name": "Henry Schein"
    },
    {
        "code": "HSY",
        "name": "Hershey Company"
    },
    {
        "code": "HES",
        "name": "Hess Corporation"
    },
    {
        "code": "HPE",
        "name": "Hewlett Packard Enterprise"
    },
    {
        "code": "HLT",
        "name": "Hilton Worldwide"
    },
    {
        "code": "HOLX",
        "name": "Hologic"
    },
    {
        "code": "HD",
        "name": "Home Depot"
    },
    {
        "code": "HON",
        "name": "Honeywell"
    },
    {
        "code": "HRL",
        "name": "Hormel Foods"
    },
    {
        "code": "HST",
        "name": "Host Hotels & Resorts"
    },
    {
        "code": "HWM",
        "name": "Howmet Aerospace"
    },
    {
        "code": "HPQ",
        "name": "HP Inc."
    },
    {
        "code": "HUBB",
        "name": "Hubbell"
    },
    {
        "code": "HUM",
        "name": "Humana"
    },
    {
        "code": "HBAN",
        "name": "Huntington Bancshares"
    },
    {
        "code": "HII",
        "name": "Huntington Ingalls Industries"
    },
    {
        "code": "IBM",
        "name": "IBM"
    },
    {
        "code": "IEX",
        "name": "IDEX Corporation"
    },
    {
        "code": "IDXX",
        "name": "Idexx Laboratories"
    },
    {
        "code": "ITW",
        "name": "Illinois Tool Works"
    },
    {
        "code": "INCY",
        "name": "Incyte"
    },
    {
        "code": "IR",
        "name": "Ingersoll Rand"
    },
    {
        "code": "PODD",
        "name": "Insulet Corporation"
    },
    {
        "code": "INTC",
        "name": "Intel"
    },
    {
        "code": "ICE",
        "name": "Intercontinental Exchange"
    },
    {
        "code": "IFF",
        "name": "International Flavors & Fragrances"
    },
    {
        "code": "IP",
        "name": "International Paper"
    },
    {
        "code": "INTU",
        "name": "Intuit"
    },
    {
        "code": "ISRG",
        "name": "Intuitive Surgical"
    },
    {
        "code": "IVZ",
        "name": "Invesco"
    },
    {
        "code": "INVH",
        "name": "Invitation Homes"
    },
    {
        "code": "IQVIA",
        "name": "IQVIA"
    },
    {
        "code": "IRM",
        "name": "Iron Mountain"
    },
    {
        "code": "JBHT",
        "name": "J.B. Hunt"
    },
    {
        "code": "JBL",
        "name": "Jabil"
    },
    {
        "code": "JKHY",
        "name": "Jack Henry & Associates"
    },
    {
        "code": "J",
        "name": "Jacobs Solutions"
    },
    {
        "code": "JNJ",
        "name": "Johnson & Johnson"
    },
    {
        "code": "JCI",
        "name": "Johnson Controls"
    },
    {
        "code": "JPM",
        "name": "JPMorgan Chase"
    },
    {
        "code": "JNPR",
        "name": "Juniper Networks"
    },
    {
        "code": "K",
        "name": "Kellanova"
    },
    {
        "code": "KVUE",
        "name": "Kenvue"
    },
    {
        "code": "KDP",
        "name": "Keurig Dr Pepper"
    },
    {
        "code": "KEY",
        "name": "KeyCorp"
    },
    {
        "code": "KEYS",
        "name": "Keysight Technologies"
    },
    {
        "code": "KMB",
        "name": "Kimberly-Clark"
    },
    {
        "code": "KIM",
        "name": "Kimco Realty"
    },
    {
        "code": "KMI",
        "name": "Kinder Morgan"
    },
    {
        "code": "KLAC",
        "name": "KLA Corporation"
    },
    {
        "code": "KHC",
        "name": "Kraft Heinz"
    },
    {
        "code": "KR",
        "name": "Kroger"
    },
    {
        "code": "LHX",
        "name": "L3Harris Technologies"
    },
    {
        "code": "LH",
        "name": "Labcorp"
    },
    {
        "code": "LRCX",
        "name": "Lam Research"
    },
    {
        "code": "LW",
        "name": "Lamb Weston"
    },
    {
        "code": "LVS",
        "name": "Las Vegas Sands"
    },
    {
        "code": "LDOS",
        "name": "Leidos"
    },
    {
        "code": "LEN",
        "name": "Lennar"
    },
    {
        "code": "LLY",
        "name": "Eli Lilly and Company"
    },
    {
        "code": "LIN",
        "name": "Linde plc"
    },
    {
        "code": "LYV",
        "name": "Live Nation Entertainment"
    },
    {
        "code": "LKQ",
        "name": "LKQ Corporation"
    },
    {
        "code": "LMT",
        "name": "Lockheed Martin"
    },
    {
        "code": "L",
        "name": "Loews Corporation"
    },
    {
        "code": "LOW",
        "name": "Lowe's"
    },
    {
        "code": "LULU",
        "name": "Lululemon Athletica"
    },
    {
        "code": "LYB",
        "name": "LyondellBasell"
    },
    {
        "code": "MTB",
        "name": "M&T Bank"
    },
    {
        "code": "MPC",
        "name": "Marathon Petroleum"
    },
    {
        "code": "MKTX",
        "name": "MarketAxess"
    },
    {
        "code": "MAR",
        "name": "Marriott International"
    },
    {
        "code": "MMC",
        "name": "Marsh McLennan"
    },
    {
        "code": "MLM",
        "name": "Martin Marietta Materials"
    },
    {
        "code": "MAS",
        "name": "Masco"
    },
    {
        "code": "MA",
        "name": "Mastercard"
    },
    {
        "code": "MTCH",
        "name": "Match Group"
    },
    {
        "code": "MKC",
        "name": "McCormick & Company"
    },
    {
        "code": "MCD",
        "name": "McDonald's"
    },
    {
        "code": "MCK",
        "name": "McKesson Corporation"
    },
    {
        "code": "MDT",
        "name": "Medtronic"
    },
    {
        "code": "MRK",
        "name": "Merck & Co."
    },
    {
        "code": "META",
        "name": "Meta Platforms"
    },
    {
        "code": "MET",
        "name": "MetLife"
    },
    {
        "code": "MTD",
        "name": "Mettler-Toledo"
    },
    {
        "code": "MGM",
        "name": "MGM Resorts"
    },
    {
        "code": "MCHP",
        "name": "Microchip Technology"
    },
    {
        "code": "MU",
        "name": "Micron Technology"
    },
    {
        "code": "MSFT",
        "name": "Microsoft Corporation"
    },
    {
        "code": "MAA",
        "name": "Mid-America Apartment Communities"
    },
    {
        "code": "MRNA",
        "name": "Moderna"
    },
    {
        "code": "MHK",
        "name": "Mohawk Industries"
    },
    {
        "code": "MOH",
        "name": "Molina Healthcare"
    },
    {
        "code": "TAP",
        "name": "Molson Coors Beverage Company"
    },
    {
        "code": "MDLZ",
        "name": "Mondelez International"
    },
    {
        "code": "MPWR",
        "name": "Monolithic Power Systems"
    },
    {
        "code": "MNST",
        "name": "Monster Beverage"
    },
    {
        "code": "NVDA",
        "name": "NVIDIA Corporation"
    },
    {
        "code": "TSLA",
        "name": "Tesla Inc."
    },
    {
        "code": "BRK.B",
        "name": "Berkshire Hathaway Inc."
    },
    {
        "code": "V",
        "name": "Visa Inc."
    },
    {
        "code": "UNH",
        "name": "UnitedHealth Group Inc."
    },
    {
        "code": "WMT",
        "name": "Walmart Inc."
    },
    {
        "code": "PG",
        "name": "Procter & Gamble Co."
    },
    {
        "code": "ORCL",
        "name": "Oracle Corporation"
    },
    {
        "code": "CRM",
        "name": "Salesforce Inc."
    },
    {
        "code": "NFLX",
        "name": "Netflix Inc."
    },
    {
        "code": "PEP",
        "name": "PepsiCo Inc."
    },
    {
        "code": "TMO",
        "name": "Thermo Fisher Scientific Inc."
    },
    {
        "code": "QCOM",
        "name": "Qualcomm Inc."
    },
    {
        "code": "TXN",
        "name": "Texas Instruments Inc."
    },
    {
        "code": "DIS",
        "name": "The Walt Disney Company"
    },
    {
        "code": "NKE",
        "name": "NIKE Inc."
    },
    {
        "code": "SBUX",
        "name": "Starbucks Corporation"
    },
    {
        "code": "UBER",
        "name": "Uber Technologies Inc."
    },
    {
        "code": "PLTR",
        "name": "Palantir Technologies Inc."
    },
    {
        "code": "COIN",
        "name": "Coinbase Global Inc."
    },
    {
        "code": "SNOW",
        "name": "Snowflake Inc."
    },
    {
        "code": "BABA",
        "name": "Alibaba Group Holding Ltd."
    },
    {
        "code": "NIO",
        "name": "NIO Inc."
    },
    {
        "code": "PYPL",
        "name": "PayPal Holdings Inc."
    },
    {
        "code": "SQ",
        "name": "Block Inc. (Square)"
    },
    {
        "code": "SHOP",
        "name": "Shopify Inc."
    },
    {
        "code": "SPOT",
        "name": "Spotify Technology S.A."
    },
    {
        "code": "PANW",
        "name": "Palo Alto Networks Inc."
    },
    {
        "code": "NOW",
        "name": "ServiceNow Inc."
    },
    {
        "code": "MS",
        "name": "Morgan Stanley"
    },
    {
        "code": "RTX",
        "name": "RTX Corporation (Raytheon)"
    },
    {
        "code": "PFE",
        "name": "Pfizer Inc."
    },
    {
        "code": "PM",
        "name": "Philip Morris International Inc."
    },
    {
        "code": "UNP",
        "name": "Union Pacific Corporation"
    },
    {
        "code": "UPS",
        "name": "United Parcel Service Inc."
    },
    {
        "code": "VZ",
        "name": "Verizon Communications Inc."
    }
],
    "Kripto": [
    {
        "code": "BTC",
        "name": "Bitcoin"
    },
    {
        "code": "ETH",
        "name": "Ethereum"
    },
    {
        "code": "SOL",
        "name": "Solana"
    },
    {
        "code": "BNB",
        "name": "BNB (Binance Coin)"
    },
    {
        "code": "XRP",
        "name": "XRP (Ripple)"
    },
    {
        "code": "DOGE",
        "name": "Dogecoin"
    },
    {
        "code": "ADA",
        "name": "Cardano"
    },
    {
        "code": "AVAX",
        "name": "Avalanche"
    },
    {
        "code": "SHIB",
        "name": "Shiba Inu"
    },
    {
        "code": "DOT",
        "name": "Polkadot"
    },
    {
        "code": "LINK",
        "name": "Chainlink"
    },
    {
        "code": "SUI",
        "name": "Sui"
    },
    {
        "code": "NEAR",
        "name": "NEAR Protocol"
    },
    {
        "code": "TRX",
        "name": "TRON"
    },
    {
        "code": "APT",
        "name": "Aptos"
    },
    {
        "code": "PEPE",
        "name": "Pepe"
    },
    {
        "code": "LTC",
        "name": "Litecoin"
    },
    {
        "code": "BCH",
        "name": "Bitcoin Cash"
    },
    {
        "code": "MATIC",
        "name": "Polygon (POL)"
    },
    {
        "code": "UNI",
        "name": "Uniswap"
    },
    {
        "code": "ATOM",
        "name": "Cosmos"
    },
    {
        "code": "XLM",
        "name": "Stellar"
    },
    {
        "code": "ICP",
        "name": "Internet Computer"
    },
    {
        "code": "RENDER",
        "name": "Render Token"
    },
    {
        "code": "FET",
        "name": "Artificial Superintelligence Alliance"
    },
    {
        "code": "FIL",
        "name": "Filecoin"
    },
    {
        "code": "HBAR",
        "name": "Hedera"
    },
    {
        "code": "TAO",
        "name": "Bittensor"
    },
    {
        "code": "KAS",
        "name": "Kaspa"
    },
    {
        "code": "INJ",
        "name": "Injective"
    },
    {
        "code": "ARB",
        "name": "Arbitrum"
    },
    {
        "code": "OP",
        "name": "Optimism"
    },
    {
        "code": "RUNE",
        "name": "THORChain"
    },
    {
        "code": "AAVE",
        "name": "Aave"
    },
    {
        "code": "FTM",
        "name": "Fantom (Sonic)"
    },
    {
        "code": "WIF",
        "name": "dogwifhat"
    },
    {
        "code": "FLOKI",
        "name": "Floki"
    },
    {
        "code": "BONK",
        "name": "Bonk"
    },
    {
        "code": "TIA",
        "name": "Celestia"
    },
    {
        "code": "SEI",
        "name": "Sei"
    }
],
    "Emtia": [
        {"code": "SPOT_ALTIN", "name": "Spot Altın (Gram ₺)"},
        {"code": "SPOT_ONS", "name": "Spot Ons Altın ($ / Ounce)"},
        {"code": "GRAM_ALTIN", "name": "Gram Altın (24 Ayar ₺)"},
        {"code": "22_AYAR", "name": "22 Ayar Bilezik / Altın (Gram ₺)"},
        {"code": "CEYREK", "name": "Çeyrek Altın (₺)"},
        {"code": "YARIM", "name": "Yarım Altın (₺)"},
        {"code": "TAM", "name": "Tam Altın (Ziynet ₺)"},
        {"code": "CUMHURIYET", "name": "Cumhuriyet Altını (Ata ₺)"},
        {"code": "ATA", "name": "Ata Altın (₺)"},
        {"code": "RESAT", "name": "Reşat Altın (₺)"},
        {"code": "GREMSE", "name": "Gremse Altın (2.5'luk ₺)"},
        {"code": "14_AYAR", "name": "14 Ayar Altın (Gram ₺)"},
        {"code": "18_AYAR", "name": "18 Ayar Altın (Gram ₺)"},
        {"code": "GRAM_GUMUS", "name": "Gram Gümüş (₺)"},
        {"code": "XAU", "name": "Ons Altın ($ / Ounce)"},
        {"code": "XAG", "name": "Ons Gümüş ($ / Ounce)"},
        {"code": "BRENT", "name": "Brent Petrol ($ / Varil)"},
        {"code": "CRUDE", "name": "Ham Petrol (WTI $)"},
        {"code": "PLAT", "name": "Platin ($ / Ons)"},
        {"code": "PAL", "name": "Paladyum ($ / Ons)"},
        {"code": "COPPER", "name": "Bakır (Copper $)"},
        {"code": "NG", "name": "Doğalgaz (Natural Gas $)"}
    ],
    "Döviz": [
    {
        "code": "USDTRY",
        "name": "Amerikan Doları (USD/TRY)"
    },
    {
        "code": "EURTRY",
        "name": "Euro (EUR/TRY)"
    },
    {
        "code": "GBPTRY",
        "name": "İngiliz Sterlini (GBP/TRY)"
    },
    {
        "code": "CHFTRY",
        "name": "İsviçre Frangı (CHF/TRY)"
    },
    {
        "code": "JPYTRY",
        "name": "Japon Yeni (100 JPY/TRY)"
    },
    {
        "code": "CADTRY",
        "name": "Kanada Doları (CAD/TRY)"
    },
    {
        "code": "AUDTRY",
        "name": "Avustralya Doları (AUD/TRY)"
    },
    {
        "code": "SARTRY",
        "name": "Suudi Arabistan Riyali (SAR/TRY)"
    },
    {
        "code": "RUBTRY",
        "name": "Rus Rublesi (RUB/TRY)"
    },
    {
        "code": "QARTRY",
        "name": "Katar Riyali (QAR/TRY)"
    },
    {
        "code": "CNYTRY",
        "name": "Çin Yuanı (CNY/TRY)"
    },
    {
        "code": "AEDTRY",
        "name": "BAE Dirhemi (AED/TRY)"
    },
    {
        "code": "NOKTRY",
        "name": "Norveç Kronu (NOK/TRY)"
    },
    {
        "code": "SEKTRY",
        "name": "İsveç Kronu (SEK/TRY)"
    },
    {
        "code": "DKKTRY",
        "name": "Danimarka Kronu (DKK/TRY)"
    },
    {
        "code": "EURUSD",
        "name": "Euro / Dolar Paritesi (EUR/USD)"
    },
    {
        "code": "GBPUSD",
        "name": "Sterlin / Dolar Paritesi (GBP/USD)"
    }
],
}






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
    if m in ["KRIPTO", "CRYPTO"]:
        return OTHER_LIST.get("Kripto", [])
    if m in ["EMTIA", "COMMODITY"]:
        return OTHER_LIST.get("Emtia", [])
    if m in ["DÖVIZ", "DOVIZ", "FOREX"]:
        return OTHER_LIST.get("Döviz", [])
    if m in ["ABD", "US", "STOCK"]:
        return OTHER_LIST.get("ABD", [])
    if m in ["ETF", "US ETF", "ABD ETF"]:
        return OTHER_LIST.get("ETF", POPULAR_ETFLER)
    if m in ["FON", "TEFAS", "TR FON"]:
        return get_fonlar()
    for k in OTHER_LIST:
        if k.upper() == m:
            return OTHER_LIST[k]
    return []

FONLAR_CACHE = {"ts": 0, "data": []}

@app.get("/fonlar")
def get_fonlar():
    now = time.time()
    if FONLAR_CACHE["data"] and now - FONLAR_CACHE["ts"] < 3600:
        return FONLAR_CACHE["data"]
    try:
        r = requests.get("https://fonfiyat.com.tr/v1/funds.json", timeout=8, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if r.status_code == 200:
            items = r.json()
            if isinstance(items, list) and len(items) > 0:
                data = [{"code": it.get("kod", ""), "name": it.get("ad", "")} for it in items if it.get("kod")]
                if data:
                    FONLAR_CACHE["ts"] = now
                    FONLAR_CACHE["data"] = data
                    return data
    except Exception as e:
        print("fonfiyat tum fonlar hatasi:", e)

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
        except Exception:
            pass
    return POPULAR_FONLAR

@app.get("/fon/{symbol}")
def get_fon_price(symbol: str):
    s = symbol.upper().strip()
    key = f"Fon:{s}"
    now = time.time()
    if key in PRICE_CACHE and now - PRICE_CACHE[key][0] < PRICE_TTL:
        return {"symbol": s, "price": PRICE_CACHE[key][1]}

    # 1. fonfiyat.com.tr gercek TEFAS API (hizli, guncel ve bot filtresiz)
    try:
        r = requests.get(f"https://fonfiyat.com.tr/v1/funds/{s}.json", timeout=5, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "fiyat" in data and data["fiyat"]:
                val = float(data["fiyat"])
                PRICE_CACHE[key] = (now, val)
                LAST_KNOWN_PRICES[key] = val
                LAST_KNOWN_PRICES[s] = val
                return {"symbol": s, "price": val}
    except Exception:
        pass

    if tefasmak:
        try:
            res = tefasmak.fon_son_fiyat_ve_getiri(s)
            if res and isinstance(res, dict) and "fiyat" in res:
                val = float(res["fiyat"])
                PRICE_CACHE[key] = (now, val)
                LAST_KNOWN_PRICES[key] = val
                return {"symbol": s, "price": val}
        except Exception:
            pass

    # Stale cache guvencesi: Dis servis gecikirse son gercek fiyati koru
    if key in PRICE_CACHE and PRICE_CACHE[key][1] and PRICE_CACHE[key][1] > 0:
        cached_val = PRICE_CACHE[key][1]
        PRICE_CACHE[key] = (now, cached_val)
        return {"symbol": s, "price": cached_val, "stale": True}

    if key in LAST_KNOWN_PRICES and LAST_KNOWN_PRICES[key] > 0:
        return {"symbol": s, "price": LAST_KNOWN_PRICES[key], "stale": True}

    fon_defaults = {"TTE": 42.50, "MAC": 18.20, "AFT": 0.94, "IPB": 14.60, "TI3": 1.25, "AES": 0.23}
    return {"symbol": s, "price": fon_defaults.get(s, 1.25)}

@app.get("/fiyat/{market}/{symbol}")
def get_price(market: str, symbol: str):
    m = market.upper().strip()
    s = symbol.upper().strip()
    key = f"{m}:{s}"
    now = time.time()
    if key in PRICE_CACHE and now - PRICE_CACHE[key][0] < PRICE_TTL:
        return {"symbol": s, "price": PRICE_CACHE[key][1]}

    price = None

    # Türkiye Yatırım Fonları (TEFAS)
    if m in ["FON", "TEFAS", "TR FON"]:
        return get_fon_price(s)

    # Kripto (Binance API)
    elif m in ["KRIPTO", "CRYPTO"]:
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
    elif m in ["ABD", "US", "STOCK", "ETF", "US ETF", "ABD ETF"]:
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
        is_tr_gold = s in [
            "GRAM_ALTIN", "ALTIN", "24_AYAR", "22_AYAR", "CEYREK",
            "YARIM", "TAM", "CUMHURIYET", "ATA", "RESAT", "GREMSE",
            "14_AYAR", "18_AYAR", "GRAM_GUMUS", "GUMUS", "SPOT_ALTIN"
        ]
        if is_tr_gold:
            try:
                ons_usd = 2735.0
                usd_try = 34.50
                r_gold = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=1d", headers=NEWS_HEADERS, timeout=4)
                if r_gold.status_code == 200:
                    ons_usd = float(r_gold.json()["chart"]["result"][0]["meta"].get("regularMarketPrice", ons_usd))
                r_fx = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/USDTRY=X?interval=1d&range=1d", headers=NEWS_HEADERS, timeout=4)
                if r_fx.status_code == 200:
                    usd_try = float(r_fx.json()["chart"]["result"][0]["meta"].get("regularMarketPrice", usd_try))
                
                gram_24k_tl = (ons_usd / 31.1034768) * usd_try
                
                if s in ["GRAM_ALTIN", "ALTIN", "24_AYAR", "SPOT_ALTIN"]:
                    price = round(gram_24k_tl, 2)
                elif s == "22_AYAR":
                    price = round(gram_24k_tl * 0.916, 2)
                elif s == "CEYREK":
                    price = round(gram_24k_tl * 1.635, 2)
                elif s == "YARIM":
                    price = round(gram_24k_tl * 3.27, 2)
                elif s == "TAM":
                    price = round(gram_24k_tl * 6.54, 2)
                elif s in ["CUMHURIYET", "ATA"]:
                    price = round(gram_24k_tl * 6.75, 2)
                elif s == "RESAT":
                    price = round(gram_24k_tl * 6.78, 2)
                elif s == "GREMSE":
                    price = round(gram_24k_tl * 16.35, 2)
                elif s == "14_AYAR":
                    price = round(gram_24k_tl * 0.585, 2)
                elif s == "18_AYAR":
                    price = round(gram_24k_tl * 0.750, 2)
                elif s in ["GRAM_GUMUS", "GUMUS"]:
                    ons_silver = 33.50
                    r_silv = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/SI=F?interval=1d&range=1d", headers=NEWS_HEADERS, timeout=4)
                    if r_silv.status_code == 200:
                        ons_silver = float(r_silv.json()["chart"]["result"][0]["meta"].get("regularMarketPrice", ons_silver))
                    price = round((ons_silver / 31.1034768) * usd_try, 2)
            except Exception:
                pass
            
            if not price:
                tr_gold_defaults = {
                    "GRAM_ALTIN": 3030.0, "ALTIN": 3030.0, "24_AYAR": 3030.0,
                    "22_AYAR": 2775.0, "CEYREK": 4960.0, "YARIM": 9920.0,
                    "TAM": 19840.0, "CUMHURIYET": 20480.0, "ATA": 20550.0,
                    "RESAT": 20580.0, "GREMSE": 49600.0, "14_AYAR": 1775.0,
                    "18_AYAR": 2275.0, "GRAM_GUMUS": 37.20, "GUMUS": 37.20
                }
                price = tr_gold_defaults.get(s, 3030.0)
        else:
            emtia_target = "GC=F" if ("XAU" in s or "SPOT_ONS" in s) else "SI=F" if "XAG" in s else "BZ=F" if "BRENT" in s else "CL=F" if "CRUDE" in s else s
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
        LAST_KNOWN_PRICES[key] = price
        LAST_KNOWN_PRICES[s] = price
        return {"symbol": s, "price": price}

    # Stale cache güvencesi: Dış API (Yahoo/Borsa) gecikirse son gerçek fiyatı koru
    if key in PRICE_CACHE and PRICE_CACHE[key][1] and PRICE_CACHE[key][1] > 0:
        last_p = PRICE_CACHE[key][1]
        PRICE_CACHE[key] = (now, last_p)
        return {"symbol": s, "price": last_p, "stale": True}

    if key in LAST_KNOWN_PRICES and LAST_KNOWN_PRICES[key] > 0:
        return {"symbol": s, "price": LAST_KNOWN_PRICES[key], "stale": True}

    if s in LAST_KNOWN_PRICES and LAST_KNOWN_PRICES[s] > 0:
        return {"symbol": s, "price": LAST_KNOWN_PRICES[s], "stale": True}

    mock_defaults = {"THYAO": 290.0, "GARAN": 145.0, "AAPL": 230.0, "BTC": 67000.0, "USDTRY": 34.50, "EURTRY": 37.20, "XAU": 2735.0, "XAG": 33.50, "BRENT": 74.50, "GRAM_ALTIN": 3030.0, "ALTIN": 3030.0, "24_AYAR": 3030.0, "22_AYAR": 2775.0, "CEYREK": 4960.0, "YARIM": 9920.0, "TAM": 19840.0, "CUMHURIYET": 20480.0, "ATA": 20550.0, "RESAT": 20580.0, "GREMSE": 49600.0, "14_AYAR": 1775.0, "18_AYAR": 2275.0, "GRAM_GUMUS": 37.20, "GUMUS": 37.20}
    return {"symbol": s, "price": mock_defaults.get(s, 100.0)}

@app.get("/gecmis/{market}/{symbol}")
def get_history(market: str, symbol: str, range: str = "1mo"):
    m = market.upper().strip()
    s = symbol.upper().strip()
    rng = range.lower().strip()
    
    # Range & interval mapping
    interval = "1d"
    yahoo_range = "1mo"
    days_count = 30

    if rng in ["7d", "1w", "1h", "7"]:
        yahoo_range = "7d"
        interval = "1d"
        days_count = 7
    elif rng in ["1mo", "1m", "1a", "30"]:
        yahoo_range = "1mo"
        interval = "1d"
        days_count = 30
    elif rng in ["3mo", "3m", "3a", "90"]:
        yahoo_range = "3mo"
        interval = "1d"
        days_count = 90
    elif rng in ["1y", "12m", "365"]:
        yahoo_range = "1y"
        interval = "1wk"
        days_count = 365
    elif rng in ["all", "tumu", "max", "5y"]:
        yahoo_range = "5y"
        interval = "1mo"
        days_count = 365 * 5

    key = f"{m}:{s}:{yahoo_range}"
    now = time.time()
    if key in HISTORY_CACHE and now - HISTORY_CACHE[key][0] < HISTORY_TTL:
        return HISTORY_CACHE[key][1]

    if m == "BIST": target = f"{s}.IS"
    elif m in ["KRIPTO", "CRYPTO"]: target = f"{s}-USD"
    elif m in ["DÖVIZ", "DOVIZ"]: target = f"{s}=X"
    elif m in ["EMTIA"]: target = "GC=F" if "XAU" in s else "SI=F" if "XAG" in s else "BZ=F"
    else: target = s

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{target}?range={yahoo_range}&interval={interval}"
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

    base_p = PRICE_CACHE.get(f"{m}:{s}", (0, 100.0))[1]
    mock_hist = []
    step_days = max(1, days_count // 30)
    for i in range(days_count, -1, -step_days):
        dt = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        variation = 1 + (((i * 7) % 19) - 9) * 0.012
        mock_hist.append({"date": dt, "price": round(base_p * variation, 2)})
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

def build_dividend_query(market: str, symbol: str):
    m = market.upper().strip()
    s = symbol.upper().strip()
    if m == "BIST":
        return f"{s} temettü OR kar payı", "tr", "TR", "tr"
    if m in ["ABD", "US"]:
        return f"{s} dividend", "en-US", "US", "en"
    if m == "FON":
        return f"{s} fon getiri dağıtım", "tr", "TR", "tr"
    return None

@app.get("/haberler/temettu")
def get_general_dividend_news():
    key = "TEMETTU_GENEL"
    cached = NEWS_CACHE.get(key)
    if cached and time.time() - cached[0] < NEWS_TTL:
        return cached[1]

    url = f"https://news.google.com/rss/search?q={quote('Borsa temettü dağıtımı OR temettü kararı OR temettü takvimi')}&hl=tr&gl=TR&ceid=TR:tr"
    items = fetch_rss_items(url, limit=12)
    NEWS_CACHE[key] = (time.time(), items)
    return items

@app.get("/haber/temettu/{market}/{symbol}")
def get_dividend_news(market: str, symbol: str):
    q = build_dividend_query(market, symbol)
    if not q:
        return []
    query, hl, gl, lang = q

    key = f"TEMETTU:{market}:{symbol}"
    cached = NEWS_CACHE.get(key)
    if cached and time.time() - cached[0] < NEWS_TTL:
        return cached[1]

    url = f"https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
    items = fetch_rss_items(url, limit=6)
    NEWS_CACHE[key] = (time.time(), items)
    return items


@app.get("/privacy", response_class=HTMLResponse)
@app.get("/gizlilik", response_class=HTMLResponse)
def privacy_policy():
    return """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PORtra - Gizlilik Politikası (Privacy Policy)</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #222; background: #fafafa; }
            h1 { color: #0d47a1; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }
            h2 { color: #1565c0; margin-top: 25px; }
            .badge { display: inline-block; background: #e3f2fd; color: #0d47a1; padding: 4px 10px; border-radius: 6px; font-size: 13px; font-weight: 600; margin-bottom: 15px; }
            .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
            footer { margin-top: 40px; text-align: center; font-size: 13px; color: #777; border-top: 1px solid #e0e0e0; padding-top: 15px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>PORtra — Gizlilik Politikası</h1>
            <div class="badge">Son Güncelleme: 24 Ekim 2026</div>

            <p><strong>PORtra</strong> ("biz", "uygulama"), kullanıcılarımızın gizliliğine ve kişisel verilerinin korunmasına en üst düzeyde önem vermektedir. İşbu Gizlilik Politikası, uygulamamızı kullandığınızda verilerinizin nasıl işlendiğini, saklandığını ve korunduğunu açıklar.</p>

            <h2>1. Toplanan Veriler ve Saklama Yöntemi</h2>
            <p><strong>Yerel Depolama (AsyncStorage):</strong> Portföyünüze eklediğiniz hisse, kripto, fon, emtia alım-satım işlemleri, maliyetler, lot adetleri ve kâr/zarar hesaplamaları tamamen cihazınızın kendi yerel belleğinde saklanır. Sunucularımıza hiçbir kişisel finansal portföy tutarınız aktarılmaz veya saklanmaz.</p>
            <p><strong>Kullanıcı Hesabı & İletişim:</strong> Uygulama içi kimlik doğrulama veya destek/geri bildirim talebinde bulunduğunuzda ad, e-posta adresi gibi yalnızca talebinizi karşılamak için gerekli olan temel bilgiler toplanır.</p>

            <h2>2. Üçüncü Taraf Servisler ve Piyasa Verileri</h2>
            <p>Uygulama, canlı piyasa fiyatları (BIST, ABD Borsaları, Kripto, TEFAS Fonları, Altın) ve finansal haberler için piyasa veri sağlayıcılarına yalnızca anonim hisse sembolü sorguları gönderir. Bu sorgularda hiçbir kullanıcı kimliği veya cüzdan bilgisi paylaşılmaz.</p>

            <h2>3. Finansal İşlemler ve Aracı Kurum Ayrımı</h2>
            <p>PORtra bir yatırım danışmanlığı şirketi, banka veya aracı kurum değildir. Uygulama üzerinden hiçbir doğrudan para transferi, hisse alım-satım emri veya takas işlemi gerçekleştirilmez. Tüm hesaplama ve araçlar yalnızca kişisel takip ve bilgilendirme amaçlıdır.</p>

            <h2>4. Veri Güvenliği</h2>
            <p>Verilerinizin güvenliğini sağlamak için endüstri standardı güvenlik önlemleri uygulanmaktadır. Biyometrik giriş (Face ID / Parmak İzi) verileriniz doğrudan işletim sisteminizin güvenli donanımı (Secure Enclave / Keystore) tarafından işlenir; uygulama tarafından asla okunamaz veya kopyalanamaz.</p>

            <h2>5. İletişim ve Veri Silme Hakları</h2>
            <p>Hesabınızın veya destek geçmişinizin silinmesini talep etmek, soru ve önerilerinizi iletmek için bizimle doğrudan iletişime geçebilirsiniz:</p>
            <p><strong>E-posta:</strong> <a href="mailto:tnrzgr@gmail.com">tnrzgr@gmail.com</a></p>

            <footer>
                &copy; 2026 PORtra. Tüm Hakları Saklıdır.
            </footer>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
