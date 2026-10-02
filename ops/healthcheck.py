#!/usr/bin/env python3
"""
Container healthcheck yardımcısı (Dockerfile + docker-compose bunu kullanır).

Kullanım:
    python /app/ops/healthcheck.py api
    python /app/ops/healthcheck.py watcher --max-age 180

`api`      → HTTP sağlık ucu yanıt veriyor mu?
`watcher`  → kalp atışı dosyası taze mi? (kontrol döngüsü takılı mı?)

Ayrı bir dosyaya ihtiyaç duymamamızın sebebi: curl'ü runtime imajına
eklemek yerine stdlib kullanıyoruz; imajdaki saldırı yüzeyi ve boyut
büyümüyor, ayrıca `python` zaten PATH'in ilk sırasında.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.getenv("STATE_DIR", "/state"))


def _log(message: str) -> None:
    print(f"[healthcheck] {message}", flush=True)


def check_api(port: int, timeout: float) -> bool:
    """GET / ucu 200 döndürüyor mu? (Uygulama hazırsa tam olarak budur.)"""
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            ok = response.status == 200
            _log(f"{url} → HTTP {response.status}")
            return ok
    except urllib.error.HTTPError as e:
        _log(f"{url} → HTTP {e.code}")
        return False
    except Exception as e:
        _log(f"{url} → ulaşılamadı: {type(e).__name__}: {e}")
        return False


def check_heartbeat(name: str, max_age: float) -> bool:
    """
    Kalp atışı dosyasının yaşı `max_age` saniyeden küçük mü?

    Süreç sonsuz uykuda takılırsa (kilitlenme, kilitlenen DNS, donanım) dosya
    güncellenmez ve healthcheck başarısız olur → Coolify konteyneri yeniden
    başlatır. Bu, "process ayakta ama iş yapmıyor" durumunu yakalar.
    """
    path = STATE_DIR / f"{name}_heartbeat"
    if not path.exists():
        _log(f"{path} yok — süreç henüz başlamadı mı?")
        return False

    age = time.time() - path.stat().st_mtime
    ok = age <= max_age
    _log(f"{path.name} yaşı {age:.0f}s (sınır {max_age:.0f}s) → {'OK' if ok else 'BAŞARISIZ'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Container sağlık kontrolü")
    parser.add_argument("role", choices=["api", "watcher"], help="Kontrol edilen rol")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--max-age", type=float, default=180.0, help="Kalp atışı yaşı sınırı (saniye)")
    args = parser.parse_args()

    if args.role == "api":
        healthy = check_api(args.port, args.timeout)
    else:
        healthy = check_heartbeat("watcher", args.max_age)

    # stdout/stderr Docker log toplayıcısına gider; HEALTHCHECK exit code'a bakar.
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())