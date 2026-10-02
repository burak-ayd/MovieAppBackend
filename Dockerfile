# syntax=docker/dockerfile:1.7
#
# ══════════════════════════════════════════════════════════════════════════════
#  MovieApp API — üretim imajı (minimum boyut)
#
#  Çalışan iki rol vardır, ikisi de AYNI imajı kullanır:
#
#    command: ["api"]      → FastAPI (uvicorn) + yeniden yükleme denetleyicisi
#    command: ["watcher"]  → domain güncelleyici (18:00 + hata anında)
#
#  ── Boyut stratejisi ────────────────────────────────────────────────────────
#  Ölçülen bağımlılık boyutları (pip install --target ile ölçüldü):
#
#      playwright .......... 104,5 MB   ⚠️ BİLEREK KURULMAZ (aşağıda)
#      InquirerPy zinciri ...  8,6 MB   ⚠️ BİLEREK KURULMAZ (aşağıda)
#      selectolax ..........  10,4 MB   gerekli
#      cryptography .........   9,9 MB   gerekli (PyJWT de kullanıyor)
#      lxml ................   8,5 MB   parsel'in bağımlılığı
#      rapidfuzz ............   5,7 MB   gerekli
#      pydantic_core ........   5,1 MB   gerekli
#      pycryptodome .........   4,0 MB   gerekli
#      curl_cffi.libs .......   3,7 MB   gerekli
#      diğerleri ...........  ~15   MB
#      ─────────────────────────────────────
#      toplam ...............  ~65   MB   (178 MB'ten düştü)
#
#  Taban: python:3.12-slim-bookworm (~125 MB).
#  Alpine MÜMKÜN DEĞİL: selectolax yalnızca manylinux (glibc) tekerlek
#  yayımlıyor; musl'da kaynak koddan derlenmesi gerekirdi. Bu yüzden slim.
#
#  ── Build ───────────────────────────────────────────────────────────────────
#      docker compose -f docker-compose.build.yml build
#      docker compose -f docker-compose.build.yml push
# ══════════════════════════════════════════════════════════════════════════════


# ── 1) Bağımlılık derleme aşaması ─────────────────────────────────────────────
# Yalnızca bu aşamaya kurulur; sonuç (runtime) imajına sadece /opt/venv taşınır.
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Bazı bağımlılıkların (curl_cffi, lxml) sarmalayıcı bulunmayan mimarilerde
# kaynak koddan derlenmesi gerekebilir. Son imaja TAŞINMAZ.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt ./

# --no-compile: .pyc dosyaları (~15-20 MB) imaja yazılmaz. Bedeli container
# ilk açılışta bytecode'nin bellekte yeniden üretilmesidir (~1-2 sn).
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-compile --no-cache-dir -r requirements.txt


# ── 2) Çalışma (runtime) imajı ───────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

# TZ: 18:00 güncellemesinin yerel saatte çalışması için tzdata şart.
# (python:3.12-slim içinde zoneinfo bulunmadığından paket kurulmalı.)
# Başka paket KURULMAZ: curl vb. eklendiğinde ~5 MB ve bağımlılıkları gelir.
# Sağlık kontrolu stdlib urllib kullanır, curl'a ihtiyaç duymaz.
ENV TZ=Europe/Istanbul \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PROJECT_ROOT=/app \
    STATE_DIR=/state \
    SEED_DIR=/app/.seed

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Uygulamayı root olmayan kullanıcı olarak çalıştır.
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Kaynak kod + operasyon betikleri
COPY --chown=app:app . /app

# Tohum (seed) kopyası: volume'de eksik eklenti dosyalarını tamamlamak için.
# /app/Plugins'in DEĞİŞTİRİLMEMİŞ hali tutulur; aksi halde yeni deploy'da
# eksik eklentiler geri gelmez.
#
# chmod +x ZORUNLU: proje Windows üzerinde geliştirildiği için git bu dosyayı
# 100644 (çalıştırılabilir değil) olarak görebilir. İmaj içinde izin verilmezse
# entrypoint "permission denied" ile ölür ve konteyner hiç açılmaz.
RUN chmod +x /app/docker/entrypoint.sh \
    && cp -a /app/Plugins /app/.seed/Plugins \
    && mkdir -p /state \
    && chown -R app:app /state /app

USER app

EXPOSE 8000

# Coolify bu healthcheck'i kullanarak proxy'yi yönlendirmeye başlatır.
# Uygulamanın kendi sağlık ucu: GET /  → {"status":"ok", ...}
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=5 \
    CMD python /app/ops/healthcheck.py api || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api"]