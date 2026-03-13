# GC PLN

Scraping data GC PLN dari FASIH BPS.

## Fitur
- Auto-discover RBM (bypassing 10,000 document limit Elasticsearch)
- Concurrency dengan multiple workers
- Cache support dan retry failed assignment
- Upsert ke databse MySQL

## Cara Instalasi dan Menjalankan

1. **Clone Repository**
   ```bash
   git clone https://github.com/muhshi/gc-pln.git
   cd gc-pln
   ```

2. **Buat Virtual Environment & Install Dependencies**
   Disarankan menggunakan virtual environment agar *package* tidak bentrok dengan instalasi Python global.
   ```bash
   python -m venv .venv
   
   # Aktivasi Virtual Environment
   # Di Windows (Command Prompt / PowerShell):
   .venv\Scripts\activate
   # Di Mac / Linux:
   source .venv/bin/activate
   
   # Install requirement
   pip install -r requirements.txt
   ```

3. **Siapkan `cookies.txt`**
   - Buka browser dan login ke situs [FASIH BPS](https://fasih-sm.bps.go.id).
   - Buka **Developer Tools** (tekan F12) lalu pergi ke tab **Network**.
   - Cari request ke `fasih-sm.bps.go.id`, klik di request tersebut, masuk ke tab **Headers**, cari baris **Request Headers** -> **Cookie**.
   - *Copy* semua teks _value_ cookie tersebut.
   - Buat file baru bernama `cookies.txt` di *root* folder repositori ini dan *paste* cookie tersebut di dalamnya.

4. **Menjalankan Script**
   Jalankan script menggunakan *worker* (thread) agar lebih cepat. Semakin banyak worker, semakin cepat data diambil (namun hati-hati terkena rate limit server/429).
   
   ```bash
   # Default 3 workers
   python app.py
   
   # Menjalankan spesifik dengan 10 workers
   python app.py --workers 10
   
   # Memaksa ulang proses tanpa menggunakan hasil cache hari ini
   python app.py --no-cache
   ```

## Changelog
- **2026-03-13**:
  - Initial upload: Push script scraping GC PLN ke repository.
  - Fix issue dengan API bypass limit totalHit 10K via dynamic prefix expansion.
  - Menambahkan daily cache dan retry mechanism untuk assignment yang failed (HTTP 429 Error).
  - Menyembunyikan data sensitif di .gitignore.
