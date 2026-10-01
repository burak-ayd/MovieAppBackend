-- ═══════════════════════════════════════════════════════════════════════════
--  STREAM / MovieAppNew — Kullanıcı Hesabı ve Cihazlar Arası Senkronizasyon
--  Şema: supabase/schema_sync.sql
--
--  Uygulama: SYNC_AUTH_PLAN.md §4.4
--  Çalıştırma: Supabase Dashboard → SQL Editor → bu dosyayı yapıştır → Run
--
--  ⚠️  Bu betik TEKRAR ÇALIŞTIRILABİLİR (idempotent).
--  ⚠️  Kimlik doğrulama için Supabase Auth (auth.users) kullanılır; burada
--      parola hash'i tutulmaz.
--  ⚠️  Dashboard → Authentication → Providers → Email → "Confirm email" KAPALI
--      olmalıdır; aksi halde oturum token'ı dönmez.
-- ═══════════════════════════════════════════════════════════════════════════


-- ═══════════════════════════════════════════════════════════════════════════
-- 5. Kullanıcı Profili
-- NOT: Kimlik doğrulama Supabase Auth (auth.users) tarafından yürütülür.
-- Bu tablo yalnızca uygulamaya özel profil alanlarını tutar.
-- E-posta burada BİLEREK tutulmaz — tek kopya ilkesi (auth.users + JWT).
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
                                                        -- auth.users.id ile birebir eşleşir
    username TEXT UNIQUE,                         -- giriş adı
    display_name TEXT,                            -- görünen ad
    avatar_url TEXT,                              -- profil fotoğrafı
    bio TEXT,                                     -- kısa tanıtım
    language TEXT DEFAULT 'tr',                   -- tercih edilen dil
    birth_date DATE,                              -- doğum tarihi
    is_private BOOLEAN DEFAULT FALSE,             -- profil gizliliği
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_username ON user_profiles(username);


-- ═══════════════════════════════════════════════════════════════════════════
-- 5.5 Sunucu Saati
-- NOT: Delta senkronizasyonu `updated_at > since` karşılaştırmasına dayanır ve
-- `updated_at` sütunu veritabanının NOW() değeriyle yazılır. `since` damgası
-- API sunucusunun saatinden gelirse iki saat arasındaki kayma sessizce kayıp
-- satırlara yol açar (ölçülen gerçek kayma: ~1 saniye). Bu fonksiyon damgayı
-- updated_at ile AYNI saat kaynağından alır.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION server_now()
RETURNS TIMESTAMPTZ
LANGUAGE sql
STABLE
AS $$
    SELECT NOW();
$$;


-- ═══════════════════════════════════════════════════════════════════════════
-- 6. Kullanıcı Belgeleri (blob senkronizasyon)
-- Her belge türü kullanıcı başına tek satırdır ve belge bazlı LWW ile birleşir.
-- Belge türleri: player_settings | search_history | theme | selected_platform
--                | plugin_visibility | category_visibility
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_documents (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,                       -- yukarıdaki belge türü adı
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,   -- belge içeriği
    is_deleted BOOLEAN DEFAULT FALSE,             -- tombstone (user_library ile aynı anlam)
    hlc_wall BIGINT NOT NULL,                     -- HLC fiziksel zaman (ms)
    hlc_counter INTEGER NOT NULL DEFAULT 0,       -- HLC mantıksal sayaç
    device_id TEXT NOT NULL,                      -- son yazan cihaz (eşitlik bozucu)
    client_updated_at TIMESTAMPTZ,                -- istemcinin bildirdiği zaman (denetim izi)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),          -- sunucu tarafı son değişim (delta sorgusu)
    CONSTRAINT unique_user_document UNIQUE (user_id, doc_type)
);

CREATE INDEX IF NOT EXISTS idx_user_documents_user_doc ON user_documents(user_id, doc_type);
-- Pull sorgularının ana erişim yolu
CREATE INDEX IF NOT EXISTS idx_user_documents_user_updated
    ON user_documents(user_id, updated_at DESC);


-- ═══════════════════════════════════════════════════════════════════════════
-- 7. Kullanıcı Kütüphanesi (kayıt bazlı senkronizasyon)
-- Favoriler, Listem, İzleme Geçmişi ve Kaldığın Yerden burada tutulur.
-- is_deleted bir TOMBSTONE'dır: cihazlar arası silme aktarımı için zorunludur.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_library (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL
        CHECK (item_type IN ('favorite', 'watchlist', 'watch_history', 'continue_watching')),
    content_id TEXT NOT NULL,                     -- içerik kimliği (id veya url)
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,   -- beyaz listeye uygun içerik alanları
    is_deleted BOOLEAN DEFAULT FALSE,             -- tombstone
    hlc_wall BIGINT NOT NULL,                     -- HLC fiziksel zaman (ms)
    hlc_counter INTEGER NOT NULL DEFAULT 0,       -- HLC mantıksal sayaç
    device_id TEXT NOT NULL,                      -- son yazan cihaz (eşitlik bozucu)
    client_updated_at TIMESTAMPTZ,                -- istemcinin bildirdiği zaman (denetim izi)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),          -- sunucu tarafı son değişim (delta sorgusu)
    CONSTRAINT unique_user_item UNIQUE (user_id, item_type, content_id)
);

CREATE INDEX IF NOT EXISTS idx_user_library_user_type ON user_library(user_id, item_type);
CREATE INDEX IF NOT EXISTS idx_user_library_content_id ON user_library(content_id);
-- Pull sorgularının ana erişim yolu
CREATE INDEX IF NOT EXISTS idx_user_library_user_updated
    ON user_library(user_id, updated_at);


-- ═══════════════════════════════════════════════════════════════════════════
-- 8. Cihaz Envanteri
-- Kullanıcının hesabına bağlı cihazları listelemek ve iptal etmek için.
-- is_current, "son push yapan cihaz" anlamına gelir; push sırasında yazılır.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_devices (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,                      -- cihazda üretilen kalıcı UUID
    device_name TEXT,                             -- örn: 'Salon TV', 'iPhone'
    platform TEXT,                                -- 'ios' | 'android' | 'web'
    app_version TEXT,                             -- örn: '1.0.0'
    is_current BOOLEAN DEFAULT FALSE,             -- bu isteği yapan cihaz
    last_pulled_at TIMESTAMPTZ,
    last_pushed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,                       -- iptal edilmişse dolu
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_user_device UNIQUE (user_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_user_devices_user_id ON user_devices(user_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- 9. updated_at Tetikleyicileri
-- NOT: Varsayılan tablolarda bu tetikleyici YOKTUR ve bu bir latent hatadır —
-- DEFAULT NOW() yalnızca INSERT'te uygulanır, PostgREST'in ON CONFLICT DO
-- UPDATE'i ise yalnızca gönderilen kolonları günceller; bu yüzden updated_at
-- hiçbir zaman güncellenmez ve delta sorgusu bozulur. Tekrarlanmaması için
-- burada zorunludur.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_profiles_updated_at ON user_profiles;
CREATE TRIGGER trg_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_documents_updated_at ON user_documents;
CREATE TRIGGER trg_user_documents_updated_at
    BEFORE UPDATE ON user_documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_library_updated_at ON user_library;
CREATE TRIGGER trg_user_library_updated_at
    BEFORE UPDATE ON user_library
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_devices_updated_at ON user_devices;
CREATE TRIGGER trg_user_devices_updated_at
    BEFORE UPDATE ON user_devices
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ═══════════════════════════════════════════════════════════════════════════
-- 10. Satır Seviyesi Güvenlik (RLS)
-- Backend tek yazıcı olduğu için doğruluk açısından gerekli değildir; savunma
-- derinliği olarak durur. Supabase anon anahtarı istemciden görülebildiği için
-- kişisel veri içeren tablolar açık bırakılmaz.
--
-- Backend `SUPABASE_SERVICE_ROLE_KEY` kullandığından RLS'i atlar; istemciden
-- gelen doğrudan PostgREST istekleri ise hiçbir satır göremez.
--
-- NOT: Politika yazılırsa politika tanımlanmadığı satırlar için varsayılan
--       "reddet" geçerlidir; Supabase Auth JWT'sindeki `auth.uid()` ile
--       eşleştirme yapılmalıdır.
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE user_profiles   ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_documents  ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_library    ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_devices    ENABLE ROW LEVEL SECURITY;


-- ═══════════════════════════════════════════════════════════════════════════
-- 11. Bakım: Tombstone Temizliği (90 gün)
-- SYNC_AUTH_PLAN.md §7.3 — `is_deleted = true` kayıtlar 90 gün sonra
-- temizlenebilir. Bir cihazın 3 ay sonra çevrimiçi olduğunda eski bir silmeyi
-- yanlışlıkla uygulamasını engeller.
--
-- ⚠️ BU SATIRLAR VERİ SİLER. Otomatik çalıştırmak için:
--      1) Aşağıdaki BLOĞU yorum satırından çıkarın, VEYA
--      2) `SELECT cron.schedule('tombstone-cleanup', '0 4 * * *',
--            $$SELECT cleanup_user_tombstones();$$);` ile pg_cron'a kaydedin.
-- ═══════════════════════════════════════════════════════════════════════════

-- CREATE OR REPLACE FUNCTION cleanup_user_tombstones()
-- RETURNS INTEGER AS $$
-- DECLARE
--     removed INTEGER;
-- BEGIN
--     DELETE FROM user_library
--      WHERE is_deleted = TRUE
--        AND updated_at < NOW() - INTERVAL '90 days';
--     GET DIAGNOSTICS removed = ROW_COUNT;
--     RETURN removed;
-- END;
-- $$ LANGUAGE plpgsql;
