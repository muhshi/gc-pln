# GC PLN

Scraping data GC PLN dari FASIH BPS.

## Fitur
- Auto-discover RBM (bypassing 10,000 document limit Elasticsearch)
- Concurrency dengan multiple workers
- Cache support dan retry failed assignment
- Upsert ke databse MySQL

## Changelog
- **2026-03-13**:
  - Initial upload: Push script scraping GC PLN ke repository.
  - Fix issue dengan API bypass limit totalHit 10K via dynamic prefix expansion.
  - Menambahkan daily cache dan retry mechanism untuk assignment yang failed (HTTP 429 Error).
  - Menyembunyikan data sensitif di .gitignore.
