#!/usr/bin/env bash
#
# ══════════════════════════════════════════════════════════════════════════════
#  Container giriş noktası — her iki rol (api, watcher) için ortak.
#
#  Görevleri:
#    1. Saat dilimini doğrular (18:00 güncellemesi buna bağlı).
#    2. /app/Plugins birim hacmini, imajdaki değiştirilmemiş kopyadan
#       (SEED_DIR) tamamlar — DIĞER VARSAYAN DOSYALARA DOKUNMAZ, çünkü
#       içlerindeki main_url değerleri güncellenmiş olabilir.
#    3. /state paylaşılan hacmini hazırlar.
#    4. İstenen rolü çalıştırır (exec = PID 1 olur, sinyal iletimi düzgün).
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/app}"
STATE_DIR="${STATE_DIR:-/state}"
SEED_DIR="${SEED_DIR:-/app/.seed}"
PORT="${PORT:-8000}"

log() { printf '[entrypoint] %s\n' "$*"; }
fail() { printf '[entrypoint][HATA] %s\n' "$*" >&2; exit 1; }

cd "$PROJECT_ROOT" || fail "Proje kökü bulunamadı: $PROJECT_ROOT"


# ── Saat dilimi ───────────────────────────────────────────────────────────────
if [ -n "${TZ:-}" ]; then
    export TZ
    if [ ! -e "/usr/share/zoneinfo/${TZ}" ]; then
        log "UYARI: tz='${TZ}' bu imajda yok; UTC ile devam ediliyor."
    else
        log "Saat dilimi: ${TZ} (şu an: $(date '+%Y-%m-%d %H:%M:%S %Z'))"
    fi
else
    log "UYARI: TZ tanımlı değil; günlük güncelleme saati UTC varsayılır."
fi


# ── /state birim hacmi ───────────────────────────────────────────────────────
# Buraya yalnızca kilit, durum ve yeniden yükleme bayrağı yazılır. Volume
# oluşturmazsak Docker imajdaki (yani salt-okunur olmayan) /state'i kullanır ve
# diğer konteynerlerle paylaşılmaz → yeniden yükleme tetiği çalışmaz.
mkdir -p "$STATE_DIR" 2>/dev/null || true
if [ ! -w "$STATE_DIR" ]; then
    fail "$STATE_DIR yazılabilir değil. 'state:' volume'ünü kaldırmayın veya
       sahipliği 'docker compose run --rm api chown -R app:app $STATE_DIR' ile düzeltin."
fi


# ── Plugins birim hacmi ──────────────────────────────────────────────────────
# Docker, hacmi İLK mount'ta imajdaki içerikle doldurur. Ancak hacim zaten
# varsa (yeniden deploy) imajdaki YENİ eklentiler oraya girmez. Bu yüzden
# eksik dosyaları elle tamamlıyoruz.
#
# Var olan dosyalara DOKUNULMAZ: içlerindeki main_url değerleri Kontrol.py
# tarafından güncellenmiş olabilir ve o değerler kalıcıdır.
PLUGINS_DIR="$PROJECT_ROOT/Plugins"

if [ -d "$SEED_DIR/Plugins" ]; then
    mkdir -p "$PLUGINS_DIR"
    copied=0
    while IFS= read -r -d '' file; do
        target="$PLUGINS_DIR/$(basename "$file")"
        if [ ! -e "$target" ]; then
            # -p (preserve) KULLANILMAZ: root olmayan kullanıcı sahipliği
            # koruyamaz ve `set -e` yüzünden entrypoint'in burada ölmesine
            # yol açar.
            cp "$file" "$target"
            copied=$((copied + 1))
        fi
    done < <(find "$SEED_DIR/Plugins" -maxdepth 1 -type f -name '*.py' -print0)

    total=$(find "$PLUGINS_DIR" -maxdepth 1 -type f -name '*.py' | wc -l | tr -d ' ')
    if [ "$copied" -gt 0 ]; then
        log "Plugins: $copied yeni eklenti eklendi (toplam $total)."
    else
        log "Plugins: volume hazır ($total eklenti, güncel domainler korunuyor)."
    fi
else
    # Tohum dizini yoksa Plugins/ yine de konteyner içinde çalışır ama
    # güncellenen domainler kaybolur — sessiz veri kaybı.
    if [ -d "$PLUGINS_DIR" ]; then
        log "UYARI: SEED_DIR bulunamadı; Plugins/ kalıcı değil, domain "
        log "       güncellemeleri yeniden başlatmada kaybolur."
    else
        fail "Plugins dizini bulunamadı: $PLUGINS_DIR"
    fi
fi


# ── Rol seçimi ────────────────────────────────────────────────────────────────
ROLE="${1:-api}"

case "$ROLE" in
    api)
        log "Rol: api — http://0.0.0.0:${PORT}"
        exec python /app/ops/supervisor.py
        ;;
    watcher)
        log "Rol: watcher — günlük ${UPDATE_HOUR:-18}:$(printf '%02d' "${UPDATE_MINUTE:-0}") ve hata anında domain güncellemesi"
        exec python /app/ops/domain_watcher.py
        ;;
    kontrol)
        log "Rol: kontrol — tek seferlik Core/Helpers/Kontrol.py çalıştırması"
        exec python /app/Core/Helpers/Kontrol.py
        ;;
    shell)
        log "Rol: shell"
        exec /bin/bash
        ;;
    *)
        fail "Bilinmeyen rol: '$ROLE' (api | watcher | kontrol | shell)"
        ;;
esac