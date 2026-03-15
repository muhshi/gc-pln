# Panduan Integrasi Script Python (GC-PLN) ke Laravel + Filament

Dokumen ini berisi arsitektur dan panduan teknis untuk mengintegrasikan script `app.py` (Scraper FASIH BPS) ke dalam aplikasi berbasis Laravel + Filament. Tujuannya agar pengguna (Admin) dapat menjalankan proses Sinkronisasi / Scraping langsung dari _dashboard_ Filament dengan menekan sebuah tombol, tanpa perlu masuk ke server via terminal.

## Diagram Alur Arsitektur

1. **User (Admin)** menekan tombol "Sinkronkan Data" di _resource_ atau _dashboard_ Filament.
2. **Filament Action** memicu **Laravel Artisan Command** atau **Job Dispatcher** di _background_.
3. **Laravel Process** mengeksekusi script `python3 app.py --workers 10` menggunakan `Symfony\Component\Process\Process`.
4. Script Python berjalan, menarik data, dan **langsung menyimpan hasilnya ke dalam Database MySQL (tabel `GC_PLN`)**.
5. Karena Laravel dan Python **berbagi database MySQL yang sama**, data di _dashboard_ Filament akan otomatis ter-_update_ secara _real-time_.

---

## Prasyarat Server (Environment)
1. **Python 3.x** terpasang di _server_ tempat Laravel berjalan.
2. File script Python (`app.py`, `cookies.txt`, `cache.json`, dan `requirements.txt`) diletakkan di dalam _project_ Laravel (direkomendasikan di _folder_ khusus yang aman, misalnya: `storage/app/python-scripts/gc-pln/`).
3. Menjalankan instalasi _dependencies_ Python di _server_:
   `pip install -r storage/app/python-scripts/gc-pln/requirements.txt`
4. Koneksi Database di `app.py` harus menunjuk ke _database_ yang sama dengan Laravel (konfigurasi `.env` Laravel selaras dengan Host/User/Pass di `DB_CONFIG` Python).

---

## Langkah 1: Buat Laravel Artisan Command

Untuk mengamankan eksekusi script Python agar tidak memblokir respon HTTP (_timeout_), buatlah sebuah `Artisan Command` yang membungkus pemanggilan script Python.

Jalankan perintah ini di terminal Laravel:
```bash
php artisan make:command RunPythonScraper
```

Isi file `app/Console/Commands/RunPythonScraper.php` dengan kode berikut:

```php
<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use Symfony\Component\Process\Process;
use Symfony\Component\Process\Exception\ProcessFailedException;
use Illuminate\Support\Facades\Log;

class RunPythonScraper extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'scraper:run';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Menjalankan script Python GC-PLN untuk menarik data dari FASIH';

    /**
     * Execute the console command.
     */
    public function handle()
    {
        $this->info('Memulai sinkronisasi data FASIH (GC-PLN)...');
        Log::info('Trigger scraper Python GC-PLN...');

        // Tentukan path absolut ke script Python
        $pythonScriptPath = storage_path('app/python-scripts/gc-pln/app.py');
        $scriptDir = dirname($pythonScriptPath);

        // Menjalankan command python3 app.py --workers 10
        // Set timeout ke 0 (unlimited) karena proses scraping bisa memakan waktu lama
        $process = new Process(['python3', 'app.py', '--workers', '10']);
        $process->setWorkingDirectory($scriptDir);
        $process->setTimeout(0); 

        try {
            $process->mustRun(function ($type, $buffer) {
                // Tampilkan log output Python secara realtime di terminal (jika dijalankan manual)
                $this->output->write($buffer);
                // (Opsional) Simpan ke log Laravel
                Log::channel('scraper')->info(trim($buffer));
            });

            $this->info('Sinkronisasi selesai!');
            Log::info('Scraper Python selesai dijalankan.');
            
        } catch (ProcessFailedException $e) {
            $this->error('Proses gagal: ' . $e->getMessage());
            Log::error('ProcessFailedException: ' . $e->getMessage());
            return Command::FAILURE;
        }

        return Command::SUCCESS;
    }
}
```

_(Saran: Buat custom log channel `scraper` di `config/logging.php` agar log Python tidak bercampur dengan log `laravel.log` default)._

---

## Langkah 2: Buat Job Queue (PENTING!)

Karena proses eksekusi Python ini memakan waktu yang lama (bisa berjam-jam), proses ini **HARUS** di-_dispatch_ menggunakan Queue di Laravel agar _request_ Filament (PHP-FPM) pengguna tidak mengalami RTO (_Request Time Out_ 504) atau layar memutar terus tanpa henti.

Buat Job baru:
```bash
php artisan make:job DispatchPythonScraper
```

Ubah file `app/Jobs/DispatchPythonScraper.php` menjadi:

```php
<?php

namespace App\Jobs;

use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;
use Illuminate\Support\Facades\Artisan;

class DispatchPythonScraper implements ShouldQueue
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    // Tambahkan timeout yang panjang (misalnya 4 jam / 14400 detik)
    public $timeout = 14400;

    /**
     * Execute the job.
     */
    public function handle(): void
    {
        // Memanggil Artisan Command secara synchronous di dalam worker Queue
        Artisan::call('scraper:run');
    }
}
```

Pastikan Laravel Queue Worker berjalan di _server_ (menggunakan Supervisor atau command `php artisan queue:work --timeout=14400`).

---

## Langkah 3: Integrasi Tombol / Header Action di Filament

Di _Resource_ atau _Widget/Dashboard_ Filament terkait (Misalnya `GcPlnResource.php` atau di `ListGcPlns.php`), tambahkan _Header Action_ yang memicu Job tersebut berjalan di _background_, lalu menampilkan Notifikasi bahwa proses sedang berjalan.

Contoh di `app/Filament/Resources/GcPlnResource/Pages/ListGcPlns.php`:

```php
<?php

namespace App\Filament\Resources\GcPlnResource\Pages;

use App\Filament\Resources\GcPlnResource;
use Filament\Actions;
use Filament\Resources\Pages\ListRecords;
use Filament\Notifications\Notification;
use App\Jobs\DispatchPythonScraper;

class ListGcPlns extends ListRecords
{
    protected static string $resource = GcPlnResource::class;

    protected function getHeaderActions(): array
    {
        return [
            Actions\Action::make('sync-fasih')
                ->label('Tarik Data FASIH')
                ->icon('heroicon-o-arrow-path')
                ->color('primary')
                ->requiresConfirmation()
                ->modalHeading('Mulai Sinkronisasi Data?')
                ->modalDescription('Proses ini akan menjalankan script Python di latar belakang untuk menarik data terbaru dari server BPS. Proses ini memakan waktu.')
                ->modalSubmitActionLabel('Ya, Sinkronkan')
                ->action(function () {
                    
                    // Dispatch Job ke Queue
                    DispatchPythonScraper::dispatch();

                    // Tampilkan notifikasi ke User (Admin)
                    Notification::make()
                        ->title('Sinkronisasi Dimulai')
                        ->body('Proses scraping sedang berjalan di latar belakang. Data akan otomatis terupdate jika Anda me-refresh halaman ini beberapa saat lagi.')
                        ->success()
                        ->send();
                }),
        ];
    }
}
```

---

## Langkah 4: Sinkronisasi Database (Model Laravel)
Tidak perlu membuat _migration_ Laravel kecuali belum ada tabelnya. Jika tabel `GC_PLN` sudah jadi hasil bentukan Python, kamu cukup membuat Model Laravel yang membaca tabel tersebut.

```bash
php artisan make:model GcPln
```
Kemudian di `app/Models/GcPln.php`, kaitkan Model tersebut dengan nama tabel yang spesifik:

```php
<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class GcPln extends Model
{
    protected $table = 'GC_PLN';
    
    // Nonaktifkan default Laravel timestamps jika berbeda namanya,
    // (Namun Python app.py mendefinisikan `created_at` dan `updated_at`,
    // sehingga kompatibel 100% dengan standar Laravel)
    public $timestamps = false; // Set true jika ingin di-manage sebagian oleh Laravel, tapi lebih baik false karena Python menggunakan fungsi ON UPDATE CURRENT_TIMESTAMP MySQL.

    protected $guarded = [];
}
```

Setelah itu, jadikan model ini basis Data Source untuk tabel Filament Anda.

*(Selesai! Berikan dokumen panduan ini kepada AI asisten yang berada di repo Laravel-mu.)*
