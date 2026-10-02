#!/usr/bin/env python3
"""
Domain güncelleyici (watcher).

İki tetikleyici vardır:

  1) GÜNLÜK — `UPDATE_HOUR:UPDATE_MINUTE` (varsayılan 18:00, konteyner saat
     dilimiyle, TZ=Europe/Istanbul) geldiğinde bir kez çalışır.

  2) HATA — API'yi düzenli aralıklarla yoklar; bir eklentinin domaini hata
     verdiğinde (HTTP 5xx / zaman aşımı / DNS) Kontrol.py DERHAL çalışır.
     Yanlış pozitifleri (tek seferlik ağ hatası) elemek için
     `ERROR_THRESHOLD` ardışık başarısız tur ve `ERROR_COOLDOWN` beklemesi
     vardır.

Nasıl çalışır:

  1. Plugins/*.py içindeki `main_url` değerlerinin parmak izini (sha256) alır.
  2. `Core/Helpers/Kontrol.py`'yi AYRI BİR SÜREÇ olarak çalıştırır. (Aynı
     süreçte çalıştırmak `cikis_yap()` → `os._exit(0)` yüzünden watcher'ı
     öldürürdü: Core/Helpers/Cli.py'de herhangi bir hata `bellek_temizle()`
     + `os._exit` ile sonlanır.)
  3. Parmak izlerini karşılaştırır. Kontrol.py hataları yutup daima 0 döndüğü
     için DEĞİŞİKLİK yalnızca içerik farkından anlaşılır.
  4. Değişiklik varsa `/state/reload_requested` bayrağını yazar; supervisor
     API'yi zarifçe yeniden başlatır ve yeni domainler belleğe alınır.

Ek olarak `fcntl.flock` ile çapraz-konteyner kilidi kullanır: watcher
güncelleme yaparken API yeniden başlıyorsa (açılışta deps.py Kontrol'ü
çalıştırır) iki süreç aynı dosyaya yazmaya çalışmasın.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/app"))
STATE_DIR = Path(os.getenv("STATE_DIR", "/state"))
PLUGINS_DIR = PROJECT_ROOT / "Plugins"

# ── Ayarlar (docker-compose environment'ı ile geçersiz kılınabilir) ───────────
API_BASE = os.getenv("API_INTERNAL_URL", "http://api:8000").rstrip("/")

UPDATE_HOUR = int(os.getenv("UPDATE_HOUR", "18"))
UPDATE_MINUTE = int(os.getenv("UPDATE_MINUTE", "0"))

# Hata yoklaması aralığı (saniye). Çok kısa seçilirse her eklenti için dış
# siteye istek atılır; 5 dakika hem yeterli hem de nazik.
CHECK_INTERVAL = max(30, int(os.getenv("DOMAIN_CHECK_INTERVAL", "300")))

# Kaç ardışık tur başarısız olursa güncelleme tetiklensin. 1 = ilk hatada.
ERROR_THRESHOLD = max(1, int(os.getenv("ERROR_THRESHOLD", "1")))
# İki hata kaynaklı güncelleme arasındaki en az bekleme (saniye).
ERROR_COOLDOWN = max(0, int(os.getenv("ERROR_COOLDOWN", "1800")))
# Kontrol.py'nin çalışma süresi üst sınırı (saniye).
RUN_TIMEOUT = max(60, int(os.getenv("KONTROL_TIMEOUT", "600")))
# Watcher başlarken bir kez güncelleme yapsın mı? (kapalı: API açılışta zaten
# `api/deps.py` → `get_plugin_manager()` içinde Kontrol'ü çalıştırıyor.)
RUN_ON_START = os.getenv("RUN_ON_START", "0").strip().lower() in ("1", "true", "yes", "on")

# Arama uçları boş sonuç döndüğünde bunu HATA say. Varsayılan 0: boş sonuç bir
# eklenti hatası değil, sadece eşleşme yok demektir. Yanlış güncelleme
# (gereksiz yeniden başlatma) üretmemek için kapalı.
REQUIRE_RESULTS = os.getenv("PROBE_REQUIRE_RESULTS", "0").strip().lower() in ("1", "true", "yes", "on")
PROBE_QUERY = os.getenv("PROBE_QUERY", "matrix")
PROBE_TIMEOUT = max(5, int(os.getenv("PROBE_TIMEOUT", "45")))
# Geliştirme kolaylığı: değişiklik bulunsa bile yeniden yükleme bayrağı
# yazılmaz (yerelde uvicorn --reload devrededir).
DISABLE_RELOAD_REQUEST = os.getenv("DISABLE_RELOAD_REQUEST", "0").strip().lower() in ("1", "true", "yes", "on")

RELOAD_FLAG = STATE_DIR / "reload_requested"
LOCK_FILE = STATE_DIR / "kontrol.lock"
LAST_RUN_FILE = STATE_DIR / "last_update.json"
HEARTBEAT_FILE = STATE_DIR / "watcher_heartbeat"

# Kontrol.py'nin kullandığı desenle BİREBİR aynı olmalı: `prefix`, tırnak,
# `https?://...` değeri ve kapanış tırnağı. Farklı desen "0 değişiklik" gibi
# görünür ve güncelleme sessizce başarısız olur.
MAIN_URL_RE = re.compile(r'(main_url\s*=\s*)(["\'])(https?://.*?)(\2)')

_stop = threading.Event()


def log(message: str) -> None:
    stamp = datetime.now().astimezone().strftime("%H:%M:%S")
    print(f"[watcher {stamp}] {message}", flush=True)


def touch_heartbeat() -> None:
    """Sağlık kontrolünün izleyeceği tazelik damgası."""
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.touch()
    except OSError as e:
        log(f"UYARI: kalp atışı yazılamadı: {e}")


def next_scheduled_run(now: datetime | None = None) -> datetime:
    """Bir sonraki `UPDATE_HOUR:UPDATE_MINUTE` yerel zamanı."""
    now = now or datetime.now().astimezone()
    target = now.replace(hour=UPDATE_HOUR, minute=UPDATE_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def snapshot_main_urls() -> dict[str, str]:
    """{dosya adı: main_url} — Kontrol.py çalıştırmadan ÖNCE/SONRA karşılaştırma için."""
    result: dict[str, str] = {}
    if not PLUGINS_DIR.exists():
        return result

    for path in sorted(PLUGINS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log(f"UYARI: {path.name} okunamadı: {e}")
            continue

        match = MAIN_URL_RE.search(content)
        if match:
            result[path.name] = match.group(3)
    return result


def request_reload(reason: str, changed: dict[str, tuple[str, str]]) -> bool:
    """Supervisor'a "API'yi yeniden başlat" sinyali gönder."""
    if DISABLE_RELOAD_REQUEST:
        # Yerel geliştirmede uvicorn --reload dosya değişimini kendisi görür;
        # ikinci bir yeniden başlatma kafa karıştırıcı olurdu.
        log("DISABLE_RELOAD_REQUEST=1 — yeniden yükleme isteği atlandı.")
        return False

    payload = {
        "reason": reason,
        "requested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "changed": sorted(changed),
        "details": {name: {"from": old, "to": new} for name, (old, new) in changed.items()},
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Önce geçici dosya + rename: supervisor bayrağı okurken yarım
        # JSON görmesin.
        temp = RELOAD_FLAG.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(RELOAD_FLAG)
        log(f"Yeniden yükleme isteği yazıldı → {len(changed)} eklenti yeniden yüklenecek.")
        return True
    except OSError as e:
        log(f"HATA: yeniden yükleme isteği yazılamadı: {e}")
        return False


def write_last_run(status: str, reason: str, changed: dict, duration: float, note: str = "") -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_RUN_FILE.write_text(
            json.dumps(
                {
                    "status": status,
                    "reason": reason,
                    "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "duration_seconds": round(duration, 2),
                    "changed_plugins": changed,
                    "note": note,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        log(f"UYARI: durum dosyası yazılamadı: {e}")


@contextlib.contextmanager
def kontrol_lock():
    """
    Çapraz-konteyner kilidi (Kontrol.py tek seferlik çalışmalı).

    Beklenen durum: watcher 18:00'de, API yeniden başlarken kendi açılış
    Kontrol'ünü çalıştırıyor olabilir (`api/deps.py::get_plugin_manager`).
    İkisi aynı `Plugins/*.py` dosyasına yazmaya çalışırsa dosya bozulabilir.
    Kilit meşgulse bu çalıştırma ATLANIR — 5 dakika sonraki turda yeniden
    denenir veya bir sonraki günlük koşu devralır.

    Yield değerleri:
        True  → kilit alındı, çalıştırılabilir
        False → başka bir süreç çalıştırıyor, atla
        None  → kilit dosyası açılamadı, kilitsiz devam et
    """
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        log(f"UYARI: kilit dosyası açılamadı ({e}); kilitsiz devam ediliyor.")
        yield None
        return

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        yield False
        return

    try:
        yield True
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def run_kontrol(reason: str) -> dict[str, tuple[str, str]]:
    """
    Kontrol.py'yi çalıştır, değişen main_url'leri döndür.

    Çıktı sözlüğü: {dosya adı: (eski url, yeni url)}
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with kontrol_lock() as acquired:
        if acquired is False:
            log(f"Atlandı: başka bir süreç Kontrol'ü çalıştırıyor (neden: {reason}).")
            return {}

        before = snapshot_main_urls()
        started = time.monotonic()
        log(f"Kontrol.py çalıştırılıyor (neden: {reason}) — {len(before)} eklenti.")

        try:
            completed = subprocess.run(
                [sys.executable, "Core/Helpers/Kontrol.py"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "PYTHONUNBUFFERED": "1"},
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - started
            log(f"HATA: Kontrol.py {RUN_TIMEOUT}s içinde bitmedi; iptal edildi.")
            write_last_run("timeout", reason, {}, duration, f"{RUN_TIMEOUT}s aşıldı")
            return {}
        except Exception as e:
            duration = time.monotonic() - started
            log(f"HATA: Kontrol.py çalıştırılamadı: {type(e).__name__}: {e}")
            write_last_run("error", reason, {}, duration, f"{type(e).__name__}: {e}")
            return {}

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if stdout:
            print(stdout, flush=True)
        if stderr:
            print(stderr, file=sys.stderr, flush=True)
        # Kontrol.py hataları yutup yutuyor (getirileri `continue` ile atılır);
        # 0 dönmesi "başarılı" demek değildir. Tek güvenilir sinyal, dosya
        # içeriğinin değişip değişmemesidir.
        if completed.returncode != 0:
            log(f"Kontrol.py {completed.returncode} koduyla çıktı (normal değil, çoğu zaman 0).")

        after = snapshot_main_urls()
        duration = time.monotonic() - started

    changed: dict[str, tuple[str, str]] = {}
    for name, new_url in after.items():
        old_url = before.get(name)
        if old_url is not None and old_url != new_url:
            changed[name] = (old_url, new_url)
            log(f"  ↻ {name}: {old_url} → {new_url}")

    # Depoda yeni eklenen eklentiler de API'nin yeniden yüklenmesini gerektirir.
    added = sorted(name for name in after if name not in before)
    for name in added:
        log(f"  + yeni eklenti: {name}")

    if changed or added:
        request_reload(reason, changed)
        write_last_run("updated", reason, sorted(changed), duration)
        log(f"Tamamlandı: {len(changed)} domain güncellendi, {len(added)} yeni eklenti ({duration:.1f}s).")
    else:
        write_last_run("no_change", reason, {}, duration)
        log(f"Tamamlandı: değişiklik yok ({duration:.1f}s).")

    return changed


# ── API yoklaması ────────────────────────────────────────────────────────────

def fetch(path: str, timeout: float) -> tuple[int, bytes]:
    """(durum kodu, gövde) — hata durumunda durum kodu 0 döner."""
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"User-Agent": "movieapp-domain-watcher/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        # Timeout, DNS, bağlantı sıfırlama... hepsi "API/e k u l e n g i d e"
        return 0, b""


def list_plugins(timeout: float = 20.0) -> list[str]:
    """`GET /api/plugins` → eklenti adları."""
    status, body = fetch("/api/plugins", timeout)
    if status != 200:
        log(f"UYARI: /api/plugins → {status or 'ulaşılamadı'}")
        return []

    try:
        payload = json.loads(body)
    except ValueError:
        log("UYARI: /api/plugins yanıtı JSON değil.")
        return []

    plugins = payload.get("plugins") or []
    return [str(p.get("name")) for p in plugins if p.get("name")]


def probe_plugins(names: list[str]) -> tuple[list[str], list[str]]:
    """
    Her eklenti için hafif bir arama isteği at.

    Dönüş: (başarısız eklenti adları, sağlıklı eklenti adları)

    `api/routes/plugins.py::search_in_plugin` eklenti istisnası yakalayıp
    HTTP 500 döndürdüğü için, domain ölüyse burada doğrudan görünür.
    """
    failed: list[str] = []
    healthy: list[str] = []

    for name in names:
        query = urllib.parse.quote(PROBE_QUERY)
        path = f"/api/plugins/{urllib.parse.quote(name)}/search?q={query}"
        status, body = fetch(path, PROBE_TIMEOUT)

        if status == 0:
            reason = "zaman aşımı / bağlantı hatası"
        elif status >= 500:
            reason = f"HTTP {status}"
        elif status == 404:
            # Eklenti listede var ama uç yok → kod/URL uyuşmazlığı, domain
            # hatası değil. Sinyal olarak saymıyoruz.
            healthy.append(name)
            continue
        elif status != 200:
            reason = f"HTTP {status}"
        elif REQUIRE_RESULTS:
            try:
                results = json.loads(body).get("results") or []
            except ValueError:
                results = []
            if not results:
                reason = "boş sonuç"
            else:
                healthy.append(name)
                continue
        else:
            healthy.append(name)
            continue

        failed.append(name)
        log(f"  ✗ {name}: {reason}")

    return failed, healthy


def check_domains() -> list[str]:
    """Tek bir yoklama turu. Hata eşiğini aşarsa Kontrol tetiklenir."""
    log("Eklenti domainleri yoklanıyor...")

    names = list_plugins()
    if not names:
        log("Eklenti listesi alınamadı (API hazır değil ya da yanlı URL). Bu tur atlanıyor.")
        return []

    failed, healthy = probe_plugins(names)
    log(f"Yoklama tamamlandı: {len(healthy)} sağlıklı, {len(failed)} hatalı.")

    if not failed:
        return []

    # Eşik: 2 denemeden az ise sitelerin kendi kısa süreli hatası olabilir.
    if len(failed) < ERROR_THRESHOLD:
        log(f"{len(failed)} hata var ama eşik ({ERROR_THRESHOLD}) aşılmadı.")
        return failed

    return failed


# ── Ana döngü ────────────────────────────────────────────────────────────────

def sleep_until_or_stop(seconds: float) -> None:
    """Sinyal gelene kadar bekle (sıfırlanabilir uyku)."""
    _stop.wait(timeout=max(0.0, seconds))


def handle_signal(signum, _frame) -> None:
    log(f"{signal.Signals(signum).name} alındı — kapanılıyor.")
    _stop.set()


def main() -> int:
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()
    upcoming = next_scheduled_run(now)
    log(f"Başladı. API: {API_BASE}")
    log(f"Zaman dilimi: {time.tzname[0]} | Günlük güncelleme: {upcoming:%Y-%m-%d %H:%M}")
    log(f"Yoklama aralığı: {CHECK_INTERVAL}s | Hata eşiği: {ERROR_THRESHOLD} | Bekleme: {ERROR_COOLDOWN}s")

    if RUN_ON_START:
        log("RUN_ON_START=1 — açılışta bir kez güncelleniyor.")
        run_kontrol("startup")

    touch_heartbeat()

    consecutive_failures = 0
    last_error_run = 0.0
    next_run = upcoming

    while not _stop.is_set():
        now = datetime.now().astimezone()
        touch_heartbeat()

        # ── 1) Günlük zaman aşımı ──────────────────────────────────────────
        if now >= next_run:
            log(f"Günlük güncelleme zamanı geldi ({next_run:%H:%M}).")
            run_kontrol("schedule")
            next_run = next_scheduled_run()
            log(f"Bir sonraki günlük güncelleme: {next_run:%Y-%m-%d %H:%M}")
            # Günlük koşudan sonra hemen yoklama yapmayı atla.
            sleep_until_or_stop(CHECK_INTERVAL)
            continue

        # ── 2) Hata yoklaması ──────────────────────────────────────────────
        failed = check_domains()

        if failed:
            consecutive_failures += 1
        else:
            consecutive_failures = 0

        if consecutive_failures >= ERROR_THRESHOLD:
            elapsed = time.monotonic() - last_error_run
            if elapsed >= ERROR_COOLDOWN:
                log(f"HATA TETİKLENDİ: {', '.join(failed)}")
                run_kontrol("error:" + ",".join(failed[:3]))
                last_error_run = time.monotonic()
                consecutive_failures = 0
            else:
                remaining = ERROR_COOLDOWN - elapsed
                log(f"Bekleme süresi dolmadı ({remaining:.0f}s kaldı), güncelleme ertelendi.")
        else:
            log(f"Hata eşiği dolmadı (1/{ERROR_THRESHOLD}); bir sonraki turda tekrar denenecek.")

        # ── 3) Bir sonraki olaya kadar bekle ──────────────────────────────
        until_schedule = (next_run - datetime.now().astimezone()).total_seconds()
        sleep_until_or_stop(max(1.0, min(CHECK_INTERVAL, until_schedule)))

    log("Kapatıldı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())