#!/usr/bin/env bash
#
# ══════════════════════════════════════════════════════════════════════════════
#  MovieApp — imaj üretimi ve Docker Hub'a gönderimi (Ubuntu / Debian)
#
#  Kullanım:
#      ./scripts/build-push.sh                    # latest
#      IMAGE_TAG=1.1.0 ./scripts/build-push.sh    # sürümlü
#      RUN_TESTS=1 ./scripts/build-push.sh        # testleri çalıştırıp öyle build et
#      PLATFORM=linux/amd64,linux/arm64 ./scripts/build-push.sh   # çoklu mimari
#
#  Ya da tek seferlik ayarlarla:
#      export DOCKERHUB_USER=burakaydogan
#      export DOCKERHUB_TOKEN=...      # Personal Access Token
#      ./scripts/build-push.sh
#
#  ── Gereksinimler (Ubuntu) ──────────────────────────────────────────────────
#  Docker kurulu değilse:
#      curl -fsSL https://get.docker.com | sudo sh
#      sudo usermod -aG docker "$USER"    # sonra: newgrp docker (ya da logout)
#
#  ── Sır YÖNETİMİ ───────────────────────────────────────────────────────────
#  Parola komut satırına ASLA yazılmaz (`ps` ve shell history'de görünür).
#  Betik token'ı --password-stdin ile okur. En güvenlisi:
#      read -rs DOCKERHUB_TOKEN && export DOCKERHUB_TOKEN
#  veya dosya: ~/.movieapp-docker-token (chmod 600)
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Ayarlar ──────────────────────────────────────────────────────────────────
# Proje köküne git. $0'a güvenilmez: betik PATH üzerinden çağrılırsa, kopyalanırsa
# ya da sembolik bağ olursa yanlış dizine gider. BASH_SOURCE[0] + readlink -f ile
# betiğin GERÇEK konumu çözümlenir.
SCRIPT_PATH="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
  RESOLVED="$(readlink -f "$SCRIPT_PATH" 2>/dev/null || echo "$SCRIPT_PATH")"
  [ -n "$RESOLVED" ] && SCRIPT_PATH="$RESOLVED"
fi
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "$PROJECT_ROOT" || {
  printf '✗ Proje köküne geçilemedi: %s\n' "$PROJECT_ROOT" >&2
  exit 1
}

DOCKERHUB_USER="${DOCKERHUB_USER:-}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:-}"
IMAGE_NAME="${IMAGE_NAME:-movieapp-api}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PLATFORM="${PLATFORM:-}"                       # ör. linux/amd64,linux/arm64
RUN_TESTS="${RUN_TESTS:-0}"
ALSO_LATEST="${ALSO_LATEST:-1}"                # sürümlü etiketten sonra :latest de gönder
NO_CACHE="${NO_CACHE:-0}"
TOKEN_FILE="${TOKEN_FILE:-$HOME/.movieapp-docker-token}"

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; DIM=$'\033[2m'; RESET=$'\033[0m'
step()  { printf '%s▸ %s%s\n' "$BLUE" "$*" "$RESET"; }
ok()    { printf '%s✓ %s%s\n' "$GREEN" "$*" "$RESET"; }
warn()  { printf '%s! %s%s\n' "$YELLOW" "$*" "$RESET"; }
die()   { printf '%s✗ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }

FULL_IMAGE="${DOCKERHUB_USER:+${DOCKERHUB_USER}/}${IMAGE_NAME}"

printf '\n%s╭──────────────────────────────────────────────╮%s\n' "$DIM" "$RESET"
printf '%s│  MovieApp imaj derleme ve yükleme           │%s\n' "$DIM" "$RESET"
printf '%s╰──────────────────────────────────────────────╯%s\n\n' "$DIM" "$RESET"

# ── 1) Ön kontrol ────────────────────────────────────────────────────────────
step "Ön kontrol"

command -v docker >/dev/null 2>&1 || die "docker kurulu değil. Kurulum:
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker \"\$USER\"   # ardından: newgrp docker"

docker info >/dev/null 2>&1 || die "docker çalışmıyor veya bu kullanıcı docker grubunda değil.
    Çözüm: sudo usermod -aG docker \"\$USER\" && newgrp docker"

# compose V2 eklentisi (docker compose) gerekli; V1 (docker-compose) DEĞİL
docker compose version >/dev/null 2>&1 || die "'docker compose' (V2 eklentisi) bulunamadı.
    Kurulum: sudo apt-get install -y docker-compose-plugin"

BUILD_HOST_ARCH="$(uname -m)"
case "$BUILD_HOST_ARCH" in
  x86_64)  HOST_ARCH="amd64" ;;
  aarch64) HOST_ARCH="arm64" ;;
  *)       HOST_ARCH="$BUILD_HOST_ARCH" ;;
esac

[ -z "$PLATFORM" ] && PLATFORM="linux/${HOST_ARCH}"
warn "derleme mimarisi: ${PLATFORM} (bu sunucu: ${BUILD_HOST_ARCH})"

if [ -z "$DOCKERHUB_USER" ]; then
  DOCKERHUB_USER="$(id -un)"
  warn "DOCKERHUB_USER tanımsız, kullanıcı adına düşülüyor: ${DOCKERHUB_USER}"
fi

# Mimari tutarsızlığı: sunucu amd64 ama Coolify ARM ise imaj orada ÇALIŞMAZ.
case "$PLATFORM" in
  *,*)
    warn "çoklu mimari — buildx + emülatör kullanılacak (yavaş olabilir)"
    ;;
  linux/amd64)
    if [ "$HOST_ARCH" != "amd64" ]; then
      warn "DİKKAT: sunucu ${HOST_ARCH} ama yalnızca amd64 üretiliyor"
    fi
    ;;
  linux/arm64)
    if [ "$HOST_ARCH" != "arm64" ]; then
      warn "DİKKAT: sunucu ${HOST_ARCH} ama yalnızca arm64 üretiliyor"
    fi
    ;;
esac

ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?') · compose $(docker compose version --short 2>/dev/null || echo '?')"
ok "hedef imaj: ${FULL_IMAGE}:${IMAGE_TAG}"

# Etiket geçerliliği — Docker Hub'da büyük harf kabul edilmez
echo "$IMAGE_TAG" | grep -qE '^[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$' \
  || die "geçersiz IMAGE_TAG: '${IMAGE_TAG}' (yalnızca harf, rakam, . _ - kullanın)"

# ── 2) Depoda mı? ────────────────────────────────────────────────────────────
step "Derleme bağlamı"
[ -f Dockerfile ] || die "Dockerfile bulunamadı: $(pwd)/Dockerfile"
[ -f requirements.txt ] || die "requirements.txt bulunamadı"
CONTEXT_MB=$(du -sm --exclude=.git . 2>/dev/null | cut -f1)
ok "kaynak ağacı ${CONTEXT_MB} MB ($(pwd))"
[ -f .dockerignore ] && ok ".dockerignore mevcut — .git, .env ve cache bağlam dışında" \
  || warn ".dockerignore yok — .git ve .env derleme bağlamına girebilir"

# ── 3) Testler (isteğe bağlı kapı) ───────────────────────────────────────────
if [ "$RUN_TESTS" = "1" ]; then
  step "Testler"
  if command -v python3 >/dev/null 2>&1; then
    if python3 -c 'import pytest' 2>/dev/null; then
      python3 -m pytest tests -q --no-header || die "TESTLER BAŞARISIZ — imaj üretilmedi"
      ok "testler geçti"
    else
      warn "pytest kurulu değil, testler atlandı (pip install -r requirements-dev.txt)"
    fi
  else
    warn "python3 yok, testler atlandı"
  fi
else
  step "Testler"
  warn "RUN_TESTS=1 verilmedi — testler çalıştırılmadı"
fi

# ── 4) Docker Hub girişi ─────────────────────────────────────────────────────
step "Docker Hub oturumu"

if [ -z "$DOCKERHUB_TOKEN" ] && [ -f "$TOKEN_FILE" ]; then
  DOCKERHUB_TOKEN="$(cat "$TOKEN_FILE")"
  ok "token dosyadan okundu: ${TOKEN_FILE}"
fi

if [ -z "$DOCKERHUB_TOKEN" ]; then
  printf '  Docker Hub Personal Access Token: '
  read -rs DOCKERHUB_TOKEN
  printf '\n'
  [ -n "$DOCKERHUB_TOKEN" ] || die "token boş — oturum açılamadı"
  printf '  Kalıcı kayıt için: umask 077; printf %%s "$DOCKERHUB_TOKEN" > %s\n' "$TOKEN_FILE"
  printf '  (kaydetmek istemiyorsanız bu adımı atlayın)\n'
fi

# --password-stdin: parola komut satırına ve shell history'ye GİRMEZ
printf '%s' "$DOCKERHUB_TOKEN" | docker login --username "$DOCKERHUB_USER" --password-stdin >/dev/null \
  || die "docker login başarısız — kullanıcı adı veya token hatalı"
unset DOCKERHUB_TOKEN
ok "oturum açıldı: ${DOCKERHUB_USER}"

# ── 5) Derleme ───────────────────────────────────────────────────────────────
# --pull: taban imajını (python:3.12-slim) güncel çeker → güvenlik yamaları
#        derlemeye dahil olur. Üretim imajı için önemli.
BUILD_PULL=(--pull)
if [ "$NO_CACHE" = "1" ]; then
  BUILD_PULL+=(--no-cache)
fi

NATIVE_PLATFORM="linux/${HOST_ARCH}"
IS_MULTI="0"
case "$PLATFORM" in
  *,*) IS_MULTI="1" ;;
esac

if [ "$PLATFORM" = "$NATIVE_PLATFORM" ] && [ "$IS_MULTI" = "0" ]; then
  # Yerel mimari, tek hedef → compose build. İmajı önce yerelde üretir,
  # sonra bölüm 7'de etiketleyip push ederiz (boyut raporu için gerekir).
  step "derleniyor (${PLATFORM})"
  BUILD_CMD=(docker compose -f docker-compose.build.yml build "${BUILD_PULL[@]}")

else
  # Çoklu mimari VEYA çapraz mimari → buildx zorunlu (emülasyon gerekir).
  if ! docker buildx version >/dev/null 2>&1; then
    die "çoklu mimari için buildx gerekli ama bulunamadı.
    Not: 'docker buildx build --platform a,b --push' tek seferlik çoklu mimari
    push yapar. Desteklenmiyorsa sunucu mimarisini Coolify sunucusuyla
    AYNI yapmak daha basittir (PLATFORM tanımlamadan çalıştırın)."
  fi

  if [ "$IS_MULTI" = "1" ]; then
    if ! docker buildx inspect movieapp-builder >/dev/null 2>&1; then
      step "buildx hazırlanıyor (container sürücü + emülatör)"
      docker buildx create --name movieapp-builder --driver docker-container --use >/dev/null
    else
      docker buildx use movieapp-builder >/dev/null
    fi
  fi

  step "derleniyor (buildx, ${PLATFORM}) — yerelde aracı görüntü oluşmaz, doğrudan push edilir"
  warn "çapraz/çoklu mimari emülasyon kullanır; ARM sunucuda amd64 derlemek saatler sürebilir"

  BUILD_CMD=(docker buildx build --platform "$PLATFORM" --push)
  BUILD_CMD+=(--tag "${FULL_IMAGE}:${IMAGE_TAG}")
  if [ "$ALSO_LATEST" = "1" ] && [ "$IMAGE_TAG" != "latest" ]; then
    BUILD_CMD+=(--tag "${FULL_IMAGE}:latest")
  fi
  BUILD_CMD+=("${BUILD_PULL[@]}" .)
  # buildx --push ile yol 7'de tekrar push etmemize GEREK YOK; bayrak kur.
  PUSHED_BY_BUILDX=1
fi

: "${PUSHED_BY_BUILDX:=0}"

printf '  komut: %s\n\n' "${BUILD_CMD[*]}"
BUILD_START=$(date +%s)
"${BUILD_CMD[@]}" || die "derleme başarısız"
BUILD_SEC=$(( $(date +%s) - BUILD_START ))
ok "derleme tamamlandı (${BUILD_SEC} sn)"

# ── 6) Boyut raporu ──────────────────────────────────────────────────────────
# buildx --push yerelde görüntü bırakmadığı için raporlanamaz.
if [ "$PUSHED_BY_BUILDX" = "0" ]; then
  step "Boyut"
  SIZE_BYTES=$(docker image inspect "${FULL_IMAGE}:${IMAGE_TAG}" --format '{{.Size}}' 2>/dev/null || echo 0)
  if [ "${SIZE_BYTES:-0}" -gt 0 ] 2>/dev/null; then
    HUMAN=$(numfmt --to=iec --suffix=B "$SIZE_BYTES" 2>/dev/null || echo "${SIZE_BYTES} bayt")
    ok "sıkıştırılmamış: ${HUMAN}  (Docker Hub sıkıştırılmış hâlini gösterir, ~%60-65 küçük)"
  else
    warn "boyut okunamadı"
  fi
fi

# ── 7) Etiketleme ve gönderme ────────────────────────────────────────────────
if [ "$PUSHED_BY_BUILDX" = "0" ]; then
  if [ "$ALSO_LATEST" = "1" ] && [ "$IMAGE_TAG" != "latest" ]; then
    step "Etiketleme"
    docker tag "${FULL_IMAGE}:${IMAGE_TAG}" "${FULL_IMAGE}:latest"
    ok "${IMAGE_TAG} → latest"
  fi

  step "Docker Hub'a gönderiliyor"
  docker push "${FULL_IMAGE}:${IMAGE_TAG}"
  ok "gönderildi: ${FULL_IMAGE}:${IMAGE_TAG}"

  if [ "$ALSO_LATEST" = "1" ] && [ "$IMAGE_TAG" != "latest" ]; then
    docker push "${FULL_IMAGE}:latest"
    ok "gönderildi: ${FULL_IMAGE}:latest"
  fi
else
  ok "gönderim buildx --push ile tamamlandı"
fi

# ── 8) Özet ──────────────────────────────────────────────────────────────────
printf '\n%s──────────────────────────────────────────────%s\n' "$DIM" "$RESET"
printf '%s TAMAMLANDI%s\n' "$GREEN" "$RESET"
printf '%s──────────────────────────────────────────────%s\n' "$DIM" "$RESET"
printf '  imaj      : %s:%s\n' "$FULL_IMAGE" "$IMAGE_TAG"
printf '  mimari    : %s\n' "$PLATFORM"
printf '  süre      : %s sn\n' "$BUILD_SEC"

printf '\n%s  Sunucuda doğrulamak için:%s\n' "$DIM" "$RESET"
printf '    docker pull %s:%s\n' "$FULL_IMAGE" "$IMAGE_TAG"
printf '    docker run --rm -p 8000:8000 %s:%s\n' "$FULL_IMAGE" "$IMAGE_TAG"
printf '    curl http://localhost:8000/\n'

printf '\n%s  Coolify tarafında:%s\n' "$DIM" "$RESET"
printf '    IMAGE_TAG=%s olarak ayarla ve redeploy yap\n' "$IMAGE_TAG"

printf '\n%s  Disk alanı kazanmak için:%s\n' "$DIM" "$RESET"
printf '    docker builder prune --filter until=168h   # önbellek\n'
printf '    docker image prune -a --filter until=720h  # eski imajlar\n\n'
