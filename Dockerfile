# syntax=docker/dockerfile:1.7
#
# ══════════════════════════════════════════════════════════════════════════════
#  MovieApp API — production imajı
#
#  Çalışan iki rol vardır, ikisi de AYNI imajı kullanır:
#
#    command: ["api"]      → FastAPI (uvicorn) + yeniden yükleme denetleyicisi
#    command: ["watcher"]  → domain güncelleyici (18:00 + hata anında)
#
#  Kritik tasarım kararı — Plugins/ birim hacmidir:
#    Core/Helpers/Kontrol.py eklenti .py dosyalarını DÜZENLER (main_url satırı).
#    Bu dosyalar konteyner içinde kalıcı değildir; `plugins:` volume'ü
#    /app/Plugins üzerine mount edilir, böylece güncellenen domainler
#    yeniden deploy ve konteyner yeniden oluşturulduğunda KAYBOLMAZ.
#    /app/.seed/Plugins ise imajdaki değiştirilmemiş kopyadır; entrypoint
#    volume'de eksik olan dosyaları oradan tamamlar.
# ══════════════════════════════════════════════════════════════════════════════


# ── 1) Bağımlılık derleme aşaması ─────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Bazı bağımlılıklar (rjsmin, csscompressor, Kekik ...) sarmalayıcı bulunmayan
# mimarilerde kaynak koddan derlenir. Derleme aşamasına build-essential koyarız;
# sonuç (runtime) imajına taşınmaz.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt ./

# Sanal ortamı /opt/venv'e kur; son imaja tek COPY ile taşınır.
# --no-compile: bytecode üretimi çalışma anında yapılır, imaj küçük kalır.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r requirements.txt


# ── 2) Çalışma (runtime) imajı ───────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

# TZ: 18:00 güncellemesinin yerel saatte çalışması için tzdata şart.
# (python:3.12-slim içinde zoneinfo bulunmadığından paket kurulmalı.)
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

# tzdata ŞART: python:3.12-slim içinde zoneinfo yok. TZ=Europe/Istanbul
# kurulmadan 18:00 güncellemesi UTC'ye kayar (18:00 TR = 15:00 UTC).
# curl yalnızca teşhis için (docker exec ile canlı kontrol); kaldırmak imajı
# ~1 MB küçültür.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        curl \
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

# Coolify bu healthcheck'i kullanarak proxy'yi yönlendirmeye başlar.
# Uygulamanın kendi sağlık ucu: GET /  → {"status":"ok", ...}
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=5 \
    CMD python /app/ops/healthcheck.py api || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api"]