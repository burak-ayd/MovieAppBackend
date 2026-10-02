#!/usr/bin/env python3
"""
API denetleyicisi (supervisor).

Neden var? Çünkü `Core/Helpers/Kontrol.py` eklenti dosyalarını düzenler, ancak
`Core/Plugin/PluginLoader.py` eklentileri YALNIZCA açılışta bir kez
sınıflandırır (`PluginManager.__init__` → `load_all()`). Dosya değiştiğinde
çalışan süreç eski `main_url` değerini belleğinde tutmaya devam eder.

Bu dosya, `ops/domain_watcher.py` tarafından yazılan "yeniden yükle" bayrağını
izler ve uvicorn sürecini ZARIFÇA yeniden başlatır. Böylece:

    watcher  →  Plugins/*.py dosyalarını günceller  →  reload bayrağı yazar
    bu süreç →  bayrağı görür  →  SIGTERM + yeniden başlat  →  yeni domainler

Coolify tarafında docker socket mount etmeye gerek kalmaz (güvenlik açığı
olsaydı) ve konteyner yeniden oluşturulmaz (kesinti saniyeler mertebesinde).

Ayrıca PID 1'in tuzak (trap) davranışını doğru kurar: `docker stop` / Coolify
redeploy sırasında SIGTERM supervisor'a gelir, çocuğa iletilir ve graceful
shutdown gerçekleşir. Bu olmadan FastAPI 10 saniye sonra SIGKILL ile öldürülür
ve "lifespan shutdown" (HTTP oturumlarını kapatma) hiç çalışmaz.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/app"))
STATE_DIR = Path(os.getenv("STATE_DIR", "/state"))

HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = os.getenv("PORT", "8000")
WORKERS = max(1, int(os.getenv("API_WORKERS", "1")))
DEV_RELOAD = os.getenv("API_DEV_RELOAD", "0").strip().lower() in ("1", "true", "yes", "on")

# Yeniden yükleme bayrağı kaç saniyede bir kontrol edilecek.
RELOAD_POLL_SECONDS = max(1.0, float(os.getenv("RELOAD_POLL_SECONDS", "5")))
# SIGTERM sonrası çocuğun kendi kapanması için beklenecek süre.
GRACEFUL_TIMEOUT = max(5.0, float(os.getenv("GRACEFUL_TIMEOUT", "25")))

# Devre kesici: yeniden yükleme kaynaklı yeniden başlatmalar bir pencerede bu
# sınırı aşarsa otomatik yeniden yükleme devre dışı bırakılır. Aksi halde bir
# site her istekte yönlendirme değiştiriyorsa sonsuz yeniden başlatma döngüsü
# oluşur (her açılışta Kontrol çalıştığı için tetik yeniden üretilir).
MAX_RELOAD_RESTARTS = max(0, int(os.getenv("MAX_RELOAD_RESTARTS", "5")))
CIRCUIT_WINDOW = max(60.0, float(os.getenv("CIRCUIT_WINDOW", "600")))

RELOAD_FLAG = STATE_DIR / "reload_requested"
STATUS_FILE = STATE_DIR / "api_status.json"
HEARTBEAT_FILE = STATE_DIR / "api_heartbeat"

_stop_requested = threading.Event()
_server: subprocess.Popen | None = None


def log(message: str) -> None:
    print(f"[supervisor] {message}", flush=True)


def touch_heartbeat() -> None:
    """Sağlık kontrolünün ve teşhisin okuyabileceği tazelik damgası."""
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.touch()
    except OSError as e:
        log(f"UYARI: kalp atışı yazılamadı: {e}")


def build_command() -> list[str]:
    """
    uvicorn komutunu kur.

    `--proxy-headers` + `--forwarded-allow-ips=*`: Coolify/Heroku tipi bir ters
    vekil (Traefik) arkasında istemci IP'si ve `X-Forwarded-Proto` kaybolmasın.
    Aksi halde `request.client.host` her zaman konteyner iç IP olur ve
    `request.url` http görünür.
    """
    cmd = [
        sys.executable, "-m", "uvicorn",
        "api.app:app",
        "--host", HOST,
        "--port", PORT,
        "--proxy-headers",
        "--forwarded-allow-ips", "*",
    ]

    if WORKERS > 1:
        # ⚠️ UYARI: `api/deps.py::get_plugin_manager` her worker sürecinde
        #    Kontrol.py'yi çalıştırır. Eşzamanlı worker'larda aynı eklenti
        #    dosyasına yazma yarışı oluşabilir. Varsayılan 1 worker bu sorunu
        #    yaşanmaz kılar; yük artarsa uvicorn öncesi tek seferlik
        #    güncelleme yapıp burada --no-... eklemek yerine çalışma zamanı
        #    kilidi (ops/domain_watcher.py içindeki flock) tercih edilmelidir.
        cmd += ["--workers", str(WORKERS)]

    if DEV_RELOAD:
        cmd += ["--reload", "--reload-dir", str(PROJECT_ROOT / "Core"), "--reload-dir", str(PROJECT_ROOT / "api")]

    return cmd


def start_server() -> subprocess.Popen:
    log(f"API başlatılıyor: {' '.join(build_command())}")
    # cwd=PROJECT_ROOT şart: Kontrol.py `ana_dizin="."` (yani cwd) ve
    # PluginLoader `plugins_dir="Plugins"` (göreli yol) kullanıyor.
    return subprocess.Popen(build_command(), cwd=str(PROJECT_ROOT))


def terminate(process: subprocess.Popen) -> None:
    """Çocuğu zarifçe kapat; takılırsa zorla sonlandır."""
    if process.poll() is not None:
        return

    log(f"SIGTERM gönderiliyor (pid={process.pid}) — graceful shutdown bekleniyor...")
    process.terminate()
    try:
        process.wait(timeout=GRACEFUL_TIMEOUT)
        log("API zarifçe kapandı.")
    except subprocess.TimeoutExpired:
        log(f"UYARI: {GRACEFUL_TIMEOUT:.0f}s içinde kapanmadı, SIGKILL gönderiliyor.")
        process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log("HATA: süreç sonlandırılamadı.")


def consume_reload_request() -> dict | None:
    """Yeniden yükleme bayrağını oku ve SİL. İçeriği loglanacak sözlük."""
    try:
        if not RELOAD_FLAG.exists():
            return None

        try:
            payload = json.loads(RELOAD_FLAG.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            payload = {"reason": "bilinmeyen", "requested_at": None}
        return payload
    finally:
        try:
            RELOAD_FLAG.unlink(missing_ok=True)
        except OSError as e:
            log(f"UYARI: bayrak silinemedi: {e}")


def write_status(**fields) -> None:
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "pid": os.getpid(),
            "workers": WORKERS,
            **fields,
        }
        STATUS_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        log(f"UYARI: durum dosyası yazılamadı: {e}")


def handle_signal(signum, _frame) -> None:
    """SIGTERM/SIGINT: çocuğa ilet ve ana döngüden çık."""
    name = signal.Signals(signum).name
    log(f"{name} alındı — API'ye iletiliyor, kapanılıyor...")
    _stop_requested.set()
    if _server is not None and _server.poll() is None:
        _server.terminate()


def main() -> int:
    global _server

    if not (PROJECT_ROOT / "api" / "app.py").exists():
        print(f"[supervisor][HATA] api/app.py bulunamadı: {PROJECT_ROOT}", file=sys.stderr)
        return 1

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Uygulama açılışta zaten Control çalıştırır; yine de durum dosyasına
    # başlangıç zamanını yaz ki "API ne zaman ayağa kalktı" sorusu cevaplanabilsin.
    write_status(state="starting", restarts=0, last_restart_reason=None)

    restarts = 0
    reload_restart_times: list[float] = []   # devre kesici için
    reload_disabled = False

    while not _stop_requested.is_set():
        _server = start_server()
        started_at = time.time()
        touch_heartbeat()
        write_status(
            state="running",
            server_pid=_server.pid,
            restarts=restarts,
            started_at=datetime.fromtimestamp(started_at).astimezone().isoformat(timespec="seconds"),
            last_restart_reason=None,
        )

        restart_reason: str | None = None
        reload_payload: dict | None = None

        # İki olayı aynı döngüde dinle: sürecin ölmesi veya yeniden yükleme isteği.
        while not _stop_requested.is_set():
            exit_code = _server.poll()
            if exit_code is not None:
                log(f"API süreci sonlandı (çıkış kodu {exit_code}).")
                break

            touch_heartbeat()

            if reload_payload is None and RELOAD_FLAG.exists():
                payload = consume_reload_request()

                # Pencere dışına düşen kayıtları at (devre kesici sayacı).
                reload_restart_times = [t for t in reload_restart_times if time.time() - t < CIRCUIT_WINDOW]

                if payload and MAX_RELOAD_RESTARTS and len(reload_restart_times) >= MAX_RELOAD_RESTARTS:
                    if not reload_disabled:
                        reload_disabled = True
                        log(
                            f"[UYARI] Devre kesici: {CIRCUIT_WINDOW:.0f}s içinde "
                            f"{len(reload_restart_times)} yeniden yükleme yapıldı. "
                            "Otomatik yeniden yükleme DURDURULDU — bir eklenti "
                            "sitesi sürekli domain değiştiriyor olabilir. "
                            "Manuel: docker compose restart api"
                        )
                        write_status(
                            state="running",
                            server_pid=_server.pid,
                            restarts=restarts,
                            last_restart_reason="devre-kesici",
                        )
                elif payload:
                    reload_payload = payload
                    restart_reason = "domain-guncellendi"
                    changed = reload_payload.get("changed") or []
                    log(f"Yeniden yükleme isteği: {reload_payload.get('reason')} — {len(changed)} dosya")
                    for name in changed:
                        log(f"  ↻ {name}")

            if restart_reason:
                break

            time.sleep(RELOAD_POLL_SECONDS)

        if _stop_requested.is_set():
            terminate(_server)
            write_status(state="stopped", restarts=restarts, last_restart_reason=restart_reason)
            log("Kapatıldı.")
            return 0

        terminate(_server)
        restarts += 1
        if restart_reason:
            reload_restart_times.append(time.time())
        write_status(state="restarting", restarts=restarts, last_restart_reason=restart_reason)
        log(f"#{restarts} yeniden başlatma ({restart_reason or 'çökme'})")

        # Yeniden başlatma arası kısa bekleme: DNS/bağlantı kaynakları
        # (SocketsInUse, HTTP bağlantı havuzu) toparlanmadan art arda denemeyi engeller.
        time.sleep(2)

    log("Çıkış.")
    return 0


if __name__ == "__main__":
    sys.exit(main())