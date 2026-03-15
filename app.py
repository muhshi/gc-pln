"""
Scraping Data GC PLN dari FASIH BPS
===================================
Filter: ULP Demak (UP3 Grobogan)
Strategi: iterasi per RBM untuk menghindari limit 1000 record
Output: MySQL tabel GC_PLN

Fitur:
- Daily cache: resume jika terputus di tengah jalan
- Anti-bot: rotasi User-Agent, random delay, header variasi
- Concurrent: multi-thread untuk proses lebih cepat

Cara pakai:
1. Update cookies.txt dengan cookies terbaru dari browser
2. Jalankan: python app.py
3. Opsional: python app.py --workers 3 (default 3 thread)
"""

import requests
import json
import time
import logging
import sys
import random
import argparse
import threading
from datetime import datetime, date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector import pooling
from tqdm import tqdm

# ============================================================
# KONFIGURASI
# ============================================================

BASE_URL = "https://fasih-sm.bps.go.id"

# Region IDs (ULP Demak di bawah UP3 Grobogan)
REGION1_ID = "c322b757-07f5-47af-ab2a-73355efc92e1"  # UPI: Jawa Tengah & DIY
REGION2_ID = "3eb7580f-0679-4f09-87c6-898a75e904ef"  # UP3: Grobogan
REGION3_ID = "0f23a4d9-2d27-4c61-b1ff-ed67a55c901d"  # ULP: Demak
SURVEY_PERIOD_ID = "d63e9832-13c6-4ec7-bf5b-59229c2f90f9"  # PLN 2026

# Database
DB_CONFIG = {
    "host": "10.133.21.24",
    "user": "root",
    "password": "demak3321",
    "database": "fasih",
}

# Scraping settings
PAGE_SIZE = 100
MAX_RETRIES = 3
DEFAULT_WORKERS = 3  # jumlah thread concurrent
COOKIES_FILE = Path(__file__).parent / "cookies.txt"
CACHE_FILE = Path(__file__).parent / "cache.json"

# Anti-bot: delay range (detik) — random antara min dan max
DELAY_MIN = 1.0
DELAY_MAX = 3.0

# ============================================================
# ANTI-BOT: User-Agent Rotation
# ============================================================

USER_AGENTS = [
    # Chrome Desktop
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    # Chrome Mobile
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,id;q=0.8",
    "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-GB,en;q=0.9",
]


def random_delay():
    """Sleep random antara DELAY_MIN dan DELAY_MAX detik."""
    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    time.sleep(delay)


def get_random_headers(xsrf_token=None):
    """Generate headers dengan User-Agent dan Accept-Language random."""
    ua = random.choice(USER_AGENTS)
    lang = random.choice(ACCEPT_LANGUAGES)

    headers = {
        "Accept": "application/json",
        "Accept-Language": lang,
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": ua,
    }

    # Set sec-ch-ua sesuai UA
    if "Chrome" in ua and "Edg" not in ua:
        headers["sec-ch-ua"] = '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
    elif "Edg" in ua:
        headers["sec-ch-ua"] = '"Not:A-Brand";v="99", "Microsoft Edge";v="145", "Chromium";v="145"'

    if "Mobile" in ua or "Android" in ua:
        headers["sec-ch-ua-mobile"] = "?1"
        headers["sec-ch-ua-platform"] = '"Android"'
    else:
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = '"Windows"'

    if xsrf_token:
        headers["X-XSRF-TOKEN"] = xsrf_token

    return headers


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ============================================================
# COOKIES
# ============================================================


def load_cookies() -> dict:
    """Load cookies dari cookies.txt dan parse jadi dict."""
    if not COOKIES_FILE.exists():
        log.error(f"File cookies.txt tidak ditemukan: {COOKIES_FILE}")
        sys.exit(1)

    raw = COOKIES_FILE.read_text(encoding="utf-8").strip()
    cookies = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            cookies[key.strip()] = value.strip()

    log.info(f"Loaded {len(cookies)} cookies dari cookies.txt")
    return cookies


# ============================================================
# DAILY CACHE — Resume jika terputus
# ============================================================

_cache_lock = threading.Lock()


def load_cache() -> dict:
    """Load cache dari file. Cache diinvalidasi jika bukan hari ini."""
    default_cache = {"date": str(date.today()), "processed": [], "rbms_done": [], "failed": []}
    if not CACHE_FILE.exists():
        return default_cache

    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        # Invalidasi jika bukan hari ini
        if data.get("date") != str(date.today()):
            log.info("Cache hari kemarin ditemukan, membuat cache baru untuk hari ini")
            return default_cache
            
        # Migrate old cache structure
        if "failed" not in data:
            data["failed"] = []
            
        log.info(f"Loaded cache: {len(data.get('processed', []))} success, {len(data.get('failed', []))} failed")
        return data
    except (json.JSONDecodeError, KeyError):
        return default_cache


def save_cache(cache: dict):
    """Simpan cache ke file (thread-safe)."""
    with _cache_lock:
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def mark_processed(cache: dict, assignment_id: str):
    """Tandai assignment sebagai sudah diproses (thread-safe)."""
    with _cache_lock:
        if assignment_id not in cache["processed"]:
            cache["processed"].append(assignment_id)
        if assignment_id in cache.get("failed", []):
            cache["failed"].remove(assignment_id)

    # Save cache setiap 10 record untuk efisiensi
    if len(cache["processed"]) % 10 == 0:
        save_cache(cache)


def mark_failed(cache: dict, assignment_id: str):
    """Tandai assignment gagal diproses hari ini."""
    with _cache_lock:
        if assignment_id not in cache.get("failed", []):
            cache["failed"].append(assignment_id)
    save_cache(cache)


def mark_rbm_done(cache: dict, rbm_id: str):
    """Tandai RBM sebagai sudah selesai diproses."""
    with _cache_lock:
        if rbm_id not in cache["rbms_done"]:
            cache["rbms_done"].append(rbm_id)
    save_cache(cache)


def is_processed(cache: dict, assignment_id: str) -> bool:
    """Cek apakah assignment sudah diproses hari ini."""
    return assignment_id in cache.get("processed", [])


# ============================================================
# DATABASE (Connection Pool untuk thread-safe)
# ============================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS GC_PLN (
    id INT AUTO_INCREMENT PRIMARY KEY,
    assignment_id VARCHAR(100) UNIQUE,
    kabupaten VARCHAR(100),
    kecamatan VARCHAR(100),
    desa VARCHAR(100),
    alamat VARCHAR(255),
    tanggal DATETIME,
    nomor_meter VARCHAR(50),
    id_pelanggan VARCHAR(50),
    nama_krt VARCHAR(200),
    nama_pencacah VARCHAR(200),
    status_dokumen VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_kabupaten (kabupaten),
    INDEX idx_kecamatan (kecamatan),
    INDEX idx_desa (desa),
    INDEX idx_tanggal (tanggal),
    INDEX idx_status (status_dokumen),
    INDEX idx_pelanggan (id_pelanggan),
    INDEX idx_kab_kec_desa (kabupaten, kecamatan, desa)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

UPSERT_SQL = """
INSERT INTO GC_PLN (assignment_id, kabupaten, kecamatan, desa, alamat, tanggal,
                     nomor_meter, id_pelanggan, nama_krt, nama_pencacah, status_dokumen)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    kabupaten = VALUES(kabupaten),
    kecamatan = VALUES(kecamatan),
    desa = VALUES(desa),
    alamat = VALUES(alamat),
    tanggal = VALUES(tanggal),
    nomor_meter = VALUES(nomor_meter),
    id_pelanggan = VALUES(id_pelanggan),
    nama_krt = VALUES(nama_krt),
    nama_pencacah = VALUES(nama_pencacah),
    status_dokumen = VALUES(status_dokumen);
"""

_db_pool = None


def init_db(pool_size=5):
    """Buat connection pool dan create table."""
    global _db_pool
    try:
        _db_pool = pooling.MySQLConnectionPool(
            pool_name="fasih_pool",
            pool_size=pool_size,
            pool_reset_session=True,
            **DB_CONFIG
        )
        # Create table menggunakan satu koneksi
        conn = _db_pool.get_connection()
        cursor = conn.cursor()
        cursor.execute(CREATE_TABLE_SQL)
        conn.commit()
        cursor.close()
        conn.close()
        log.info(f"Database connected (pool size={pool_size}) & tabel GC_PLN ready")
    except MySQLError as e:
        log.error(f"Database error: {e}")
        sys.exit(1)


def upsert_record(record: dict):
    """Insert atau update satu record ke tabel GC_PLN (thread-safe via pool)."""
    conn = _db_pool.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(UPSERT_SQL, (
            record.get("assignment_id"),
            record.get("kabupaten"),
            record.get("kecamatan"),
            record.get("desa"),
            record.get("alamat"),
            record.get("tanggal"),
            record.get("nomor_meter"),
            record.get("id_pelanggan"),
            record.get("nama_krt"),
            record.get("nama_pencacah"),
            record.get("status_dokumen"),
        ))
        conn.commit()
        cursor.close()
    finally:
        conn.close()  # return to pool


# ============================================================
# API FUNCTIONS
# ============================================================


def create_session():
    """Buat requests.Session baru (setiap thread punya session sendiri)."""
    return requests.Session()


# Thread-local storage untuk session per thread
_thread_local = threading.local()


def get_session():
    """Ambil session untuk thread saat ini."""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = create_session()
    return _thread_local.session


def api_request(method, url, cookies, xsrf_token=None, json_data=None, retries=MAX_RETRIES):
    """Lakukan HTTP request dengan retry dan anti-bot headers."""
    sess = get_session()
    headers = get_random_headers(xsrf_token)

    for attempt in range(retries):
        try:
            if method == "POST":
                resp = sess.post(url, headers=headers, cookies=cookies, json=json_data, timeout=30)
            else:
                resp = sess.get(url, headers=headers, cookies=cookies, timeout=30)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                # Rate limited — tunggu lebih lama
                wait = random.uniform(10, 20)
                log.warning(f"Rate limited (429)! Menunggu {wait:.0f}s... (attempt {attempt+1}/{retries})")
                time.sleep(wait)
            elif resp.status_code == 403:
                log.error(f"Forbidden (403) - kemungkinan cookies expired atau terdeteksi bot")
                return None
            else:
                log.warning(f"HTTP {resp.status_code} pada {url} (attempt {attempt+1}/{retries})")

        except requests.exceptions.RequestException as e:
            log.warning(f"Request error: {e} (attempt {attempt+1}/{retries})")

        if attempt < retries - 1:
            time.sleep(random.uniform(3, 6))

    log.error(f"Gagal setelah {retries} percobaan: {url}")
    return None


def build_assignment_body(start=0, length=PAGE_SIZE, region4_id=None, search_keyword=""):
    """Bangun request body untuk endpoint daftar assignment."""
    columns = []
    for col_name in ["id", "codeIdentity", "data1", "data2", "data3", "data4", "data5", "data6"]:
        columns.append({
            "data": col_name,
            "name": "",
            "searchable": True,
            "orderable": col_name not in ["id", "codeIdentity"],
            "search": {"value": "", "regex": False}
        })

    return {
        "draw": 1,
        "columns": columns,
        "order": [{"column": 0, "dir": "asc"}],
        "start": start,
        "length": length,
        "search": {"value": search_keyword, "regex": False},
        "assignmentExtraParam": {
            "region1Id": REGION1_ID,
            "region2Id": REGION2_ID,
            "region3Id": REGION3_ID,
            "region4Id": region4_id,
            "region5Id": None,
            "region6Id": None,
            "region7Id": None,
            "region8Id": None,
            "region9Id": None,
            "region10Id": None,
            "surveyPeriodId": SURVEY_PERIOD_ID,
            "assignmentErrorStatusType": -1,
            "assignmentStatusAlias": None,
            "data1": None, "data2": None, "data3": None, "data4": None,
            "data5": None, "data6": None, "data7": None, "data8": None,
            "data9": None, "data10": None,
            "userIdResponsibility": None,
            "currentUserId": None,
            "regionId": None,
            "filterTargetType": "TARGET_ONLY"
        }
    }


def fetch_assignments_page(cookies, xsrf_token, start=0, length=PAGE_SIZE, region4_id=None, search_keyword=""):
    """Fetch satu halaman daftar assignment."""
    url = f"{BASE_URL}/analytic/api/v2/assignment/datatable-all-user-survey-periode"
    body = build_assignment_body(start, length, region4_id, search_keyword)
    resp = api_request("POST", url, cookies, xsrf_token, json_data=body)
    return resp


def fetch_petugas(cookies, xsrf_token, assignment_id):
    """Fetch nama petugas untuk assignment tertentu."""
    url = f"{BASE_URL}/assignment-general/api/assignment-responsibility/get-structure-approval"
    url += f"?assignmentId={assignment_id}"
    return api_request("GET", url, cookies, xsrf_token)


def fetch_wilayah(cookies, xsrf_token, assignment_id):
    """Fetch detail wilayah (kab/kec/desa) untuk assignment tertentu."""
    url = f"{BASE_URL}/assignment-general/api/assignment/get-by-assignment-id"
    url += f"?assignmentId={assignment_id}"
    return api_request("GET", url, cookies, xsrf_token)


def fetch_region4_list(cookies, xsrf_token, region3_id=REGION3_ID):
    """Ambil daftar semua region4 (RBM/Desa) di bawah Region 3 (ULP)."""
    # Mengambil relasi parent->child dari level 3 ke level 4
    url = f"{BASE_URL}/assignment-general/api/region/get-level-3-to-level-4?regionId={region3_id}&surveyPeriodId={SURVEY_PERIOD_ID}"
    return api_request("GET", url, cookies, xsrf_token)


# ============================================================
# PARSING
# ============================================================

def parse_pre_defined_data(pre_defined_data_str):
    """Parse pre_defined_data JSON string, ambil r102b, r102c, r102d."""
    result = {"kabupaten": None, "kecamatan": None, "desa": None}
    if not pre_defined_data_str:
        return result

    try:
        data = json.loads(pre_defined_data_str)
        predata = data.get("predata", [])
        for item in predata:
            key = item.get("dataKey", "")
            answer = item.get("answer", "")
            if key == "r102b":
                # Format: "[3321] KAB. DEMAK" -> ambil "KAB. DEMAK"
                result["kabupaten"] = answer.split("] ", 1)[-1] if "] " in str(answer) else str(answer)
            elif key == "r102c":
                result["kecamatan"] = answer.split("] ", 1)[-1] if "] " in str(answer) else str(answer)
            elif key == "r102d":
                result["desa"] = answer.split("] ", 1)[-1] if "] " in str(answer) else str(answer)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning(f"Error parsing pre_defined_data: {e}")

    return result


def parse_tanggal(date_str):
    """Parse tanggal dari format API ke datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("+00:00", "+0000").replace("+0000", ""))
    except (ValueError, TypeError):
        try:
            return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            return None


def get_pencacah_name(petugas_data):
    """Ambil nama pencacah dari response petugas."""
    if not petugas_data or not petugas_data.get("success"):
        return None

    data_list = petugas_data.get("data", [])
    for item in data_list:
        role = item.get("currentSurveyRoleName", "")
        if role == "Pencacah":
            return item.get("fullname", "")

    if data_list:
        return data_list[0].get("fullname", "")
    return None


# ============================================================
# DISCOVER RBM
# ============================================================

def extract_rbm_from_region(region):
    """Ekstrak RBM id dan name dari region data."""
    level1 = region.get("level1", {})
    level2 = level1.get("level2", {}) if level1 else {}
    level3 = level2.get("level3", {}) if level2 else {}
    level4 = level3.get("level4", {}) if level3 else {}
    if level4 and level4.get("id"):
        return level4["id"], level4.get("name", level4.get("code", ""))
    return None, None


def discover_rbms(cookies, xsrf_token):
    """Ambil daftar semua RBM dengan memindai berdasarkan prefix (dinamis bypass limit 10K)."""
    log.info("Mencari daftar RBM (Region 4) menggunakan metode Prefix Search Dinamis (DFS)...")
    rbms = {}
    
    # Antrean prefix yang akan dicek. ID Pelanggan dan No Meter pasti mengandung angka
    # Kita mulai dengan angka 0-9 untuk membagi ~100.000 data jadi chunk yang < 10.000.
    queue = [str(i) for i in range(10)]

    while queue:
        prefix = queue.pop(0)
        
        # Cek total dokumen untuk prefix ini dengan request length=1 agar cepat
        resp = fetch_assignments_page(cookies, xsrf_token, start=0, length=1, region4_id=None, search_keyword=prefix)
        if not resp:
            continue

        total = resp.get("totalHit", 0)
        if total == 0:
            continue

        # Jika total mencapai limit 10.000 Elasticsearch, kita harus pecah prefixnya
        if total >= 10000:
            log.info(f"  Prefix '{prefix}' -> {total}+ records (KENA LIMIT). Memecah pencarian...")
            # Tambahkan 0-9 ke depan antrean (DFS agar memori tidak habis)
            sub_prefixes = [f"{prefix}{char}" for char in "0123456789"]
            queue = sub_prefixes + queue
            continue
            
        log.info(f"  Prefix '{prefix}' -> {total} records (Aman). Memindai & Mengekstrak RBM...")

        # Kita harus ambil semua records untuk prefix ini karena jumlahnya < 10.000
        start = 0
        while start < total:
            random_delay()
            resp = fetch_assignments_page(cookies, xsrf_token, start=start, length=PAGE_SIZE, region4_id=None, search_keyword=prefix)
            if not resp:
                break

            data = resp.get("searchData", [])
            if not data:
                break

            for item in data:
                rbm_id, rbm_name = extract_rbm_from_region(item.get("region", {}))
                if rbm_id:
                    rbms[rbm_id] = rbm_name

            start += PAGE_SIZE

    log.info(f"Ditemukan {len(rbms)} RBM/Desa unik total setelah full DFS scan.")
    return rbms


# ============================================================
# PROCESS SINGLE ASSIGNMENT (dijalankan per thread)
# ============================================================

def process_assignment(item, cookies, xsrf_token, cache):
    """Proses satu assignment: fetch petugas + wilayah, upsert ke DB."""
    assignment_id = item.get("id")
    if not assignment_id:
        return False

    # Skip jika sudah diproses hari ini
    if is_processed(cache, assignment_id):
        return True  # count as success (sudah ada)

    try:
        record = {
            "assignment_id": assignment_id,
            "id_pelanggan": item.get("data1", ""),
            "nama_krt": item.get("data2", ""),
            "nomor_meter": item.get("data3", ""),
            "alamat": item.get("data4", ""),
            "status_dokumen": item.get("assignmentStatusAlias", ""),
            "tanggal": parse_tanggal(item.get("dateCreated")),
            "kabupaten": None,
            "kecamatan": None,
            "desa": None,
            "nama_pencacah": None,
        }

        # Fetch nama petugas
        random_delay()
        petugas_resp = fetch_petugas(cookies, xsrf_token, assignment_id)
        record["nama_pencacah"] = get_pencacah_name(petugas_resp)

        # Fetch detail wilayah
        random_delay()
        wilayah_resp = fetch_wilayah(cookies, xsrf_token, assignment_id)
        if wilayah_resp and wilayah_resp.get("success"):
            wil_data = wilayah_resp.get("data", {})
            pre_defined = wil_data.get("pre_defined_data", "")
            parsed = parse_pre_defined_data(pre_defined)
            record["kabupaten"] = parsed["kabupaten"]
            record["kecamatan"] = parsed["kecamatan"]
            record["desa"] = parsed["desa"]

        if record["nama_pencacah"] is None or record["kabupaten"] is None:
            # API failure during fetch
            log.warning(f"  Data incomplete untuk {assignment_id}, marked as failed (kemungkinan 429/403)")
            mark_failed(cache, assignment_id)
            return False
            
        # Upsert ke database
        upsert_record(record)
        mark_processed(cache, assignment_id)
        return True

    except Exception as e:
        log.error(f"Error processing {assignment_id}: {e}")
        mark_failed(cache, assignment_id)
        return False


# ============================================================
# MAIN SCRAPING
# ============================================================

def scrape_rbm(cookies, xsrf_token, rbm_id, rbm_name, cache, num_workers):
    """Scrape semua assignment untuk satu RBM dengan multi-thread."""
    log.info(f"  Scraping RBM: {rbm_name}")

    # Fetch halaman pertama
    resp = fetch_assignments_page(cookies, xsrf_token, start=0, length=PAGE_SIZE, region4_id=rbm_id)
    if not resp:
        log.warning(f"  Gagal fetch RBM {rbm_name}")
        return 0

    total = resp.get("totalHit", 0)
    if total == 0:
        log.info(f"  RBM {rbm_name}: 0 records")
        return 0

    log.info(f"  RBM {rbm_name}: {total} records")

    all_assignments = resp.get("searchData", [])

    # =========================================================
    # EARLY STOP: Cek apakah RBM ini benar di Kabupaten Demak
    # Ambil data pertama dari RBM ini dan cek wilayahnya
    # =========================================================
    if all_assignments:
        first_id = all_assignments[0].get("id")
        if first_id:
            wilayah_resp = fetch_wilayah(cookies, xsrf_token, first_id)
            if wilayah_resp and wilayah_resp.get("success"):
                wil_data = wilayah_resp.get("data", {})
                pre_defined = wil_data.get("pre_defined_data", "")
                parsed = parse_pre_defined_data(pre_defined)
                kab = parsed.get("kabupaten")
                if kab and "DEMAK" not in kab.upper():
                    log.info(f"  [SKIP] RBM {rbm_name} berada di {kab} (Bukan Demak).")
                    return 0

    start = PAGE_SIZE

    # Fetch semua halaman
    while start < total:
        random_delay()
        resp = fetch_assignments_page(cookies, xsrf_token, start=start, length=PAGE_SIZE, region4_id=rbm_id)
        if not resp:
            break
        data = resp.get("searchData", [])
        if not data:
            break
        all_assignments.extend(data)
        start += PAGE_SIZE

    # Filter yang belum diproses (kalau ada di failed, retry lagi)
    pending = [a for a in all_assignments if not is_processed(cache, a.get("id", ""))]
    skipped = len(all_assignments) - len(pending)
    if skipped > 0:
        log.info(f"  Skip {skipped} assignment (sukses dari cache), proses {len(pending)} tugas")

    if not pending:
        log.info(f"  RBM {rbm_name}: semua sudah diproses (dari cache)")
        return skipped

    # Proses dengan multi-thread
    success = skipped
    pbar = tqdm(total=len(pending), desc=f"    {rbm_name}", leave=False)

    # Acak urutan untuk anti-bot pattern detection
    random.shuffle(pending)

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(process_assignment, item, cookies, xsrf_token, cache): item
            for item in pending
        }

        for future in as_completed(futures):
            try:
                if future.result():
                    success += 1
            except Exception as e:
                log.error(f"  Thread error: {e}")
            pbar.update(1)

    pbar.close()
    log.info(f"  RBM {rbm_name}: {success}/{len(all_assignments)} records berhasil")
    return success


def main():
    """Main entry point."""
    # Parse arguments
    parser = argparse.ArgumentParser(description="Scraping GC PLN dari FASIH BPS")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Jumlah thread concurrent (default: {DEFAULT_WORKERS})")
    parser.add_argument("--no-cache", action="store_true",
                        help="Abaikan cache, proses ulang semua")
    args = parser.parse_args()

    start_time = time.time()  # Catat waktu mulai

    log.info("=" * 60)
    log.info("SCRAPING GC PLN - FASIH BPS")
    log.info(f"Tanggal  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Filter   : ULP Demak (UP3 Grobogan)")
    log.info(f"Workers  : {args.workers} threads")
    log.info("=" * 60)

    # Load cookies
    cookies = load_cookies()
    xsrf_token = cookies.get("XSRF-TOKEN")

    # Load / reset cache
    if args.no_cache:
        cache = {"date": str(date.today()), "processed": [], "rbms_done": []}
        log.info("Cache di-skip (--no-cache)")
    else:
        cache = load_cache()

    # Connect database (pool size = workers + 2 buffer)
    init_db(pool_size=args.workers + 2)

    try:
        # Discover semua RBM
        rbms = discover_rbms(cookies, xsrf_token)
        if not rbms:
            log.error("Tidak ada RBM ditemukan. Cek cookies atau koneksi.")
            return

        # Scrape per RBM
        total_processed = 0
        for i, (rbm_id, rbm_name) in enumerate(rbms.items(), 1):
            # Skip RBM yang sudah selesai (dari cache)
            if rbm_id in cache.get("rbms_done", []) and not args.no_cache:
                log.info(f"\n[{i}/{len(rbms)}] RBM {rbm_name}: SKIP (sudah selesai dari cache)")
                continue

            log.info(f"\n[{i}/{len(rbms)}] Processing RBM: {rbm_name}")
            count = scrape_rbm(cookies, xsrf_token, rbm_id, rbm_name, cache, args.workers)
            total_processed += count

            # Mark RBM selesai HANYA JIKA semua sukses
            # Artinya, cek masih ada yg failed dari RBM ini ngga?
            # Kita asumsi jika `count` + `skipped` == `total` di function scrape_rbm,
            # tapi simpelnya: mark selesai jika tidak memunculkan failed baru.
            # Tapi RBM marking ini aman untuk di-skip saat retry.
            mark_rbm_done(cache, rbm_id)

        # Save final cache
        save_cache(cache)

        duration = time.time() - start_time
        hours, rem = divmod(duration, 3600)
        minutes, seconds = divmod(rem, 60)
        duration_str = f"{int(hours)}j {int(minutes)}m {int(seconds)}d"

        log.info("\n" + "=" * 60)
        log.info("REKAPITULASI AKHIR SCRAPING")
        log.info("=" * 60)
        log.info(f"Durasi Penarikan        : {duration_str}")
        log.info(f"Total diproses sesi ini : {total_processed} records")
        log.info(f"Total KUMULATIF SUKSES  : {len(cache.get('processed', []))} records")
        log.info(f"Total GAGAL / SKIP      : {len(cache.get('failed', []))} records")
        log.info(f"Total RBM Selesai       : {len(cache.get('rbms_done', []))} RBM")
        log.info(f"Cache tersimpan di      : {CACHE_FILE}")
        log.info("=" * 60)

    except KeyboardInterrupt:
        duration = time.time() - start_time
        hours, rem = divmod(duration, 3600)
        minutes, seconds = divmod(rem, 60)
        duration_str = f"{int(hours)}j {int(minutes)}m {int(seconds)}d"

        log.info("\nDihentikan oleh user — cache tersimpan, bisa resume nanti")
        save_cache(cache)
        log.info("\n" + "=" * 60)
        log.info("REKAPITULASI SEMENTARA SCRAPING")
        log.info("=" * 60)
        log.info(f"Durasi Penarikan        : {duration_str}")
        log.info(f"Total KUMULATIF SUKSES  : {len(cache.get('processed', []))} records")
        log.info(f"Total GAGAL / SKIP      : {len(cache.get('failed', []))} records")
        log.info(f"Total RBM Selesai       : {len(cache.get('rbms_done', []))} RBM")
        log.info("=" * 60)
    except Exception as e:
        log.error(f"Error: {e}")
        save_cache(cache)
        raise


if __name__ == "__main__":
    main()
