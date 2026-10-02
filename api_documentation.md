# MovieApp API

**Base URL:** `https://movieapi.burakaydogan.net.tr`

> ⚠️ Taban URL'in **sonuna `/api` yazmayın.** Uçlar kendi `/api` önekini
> taşır; istemci ikinci kez eklemelidir.
>
> | Doğru | Yanlış |
> |---|---|
> | `https://movieapi.burakaydogan.net.tr/api/plugins` | `https://movieapi.burakaydogan.net.tr/api/api/plugins` |
>
> İkinci hâl sunucuya 404 döner. API bu durumu yakalar ve ne yapılması
> gerektiğini söyleyen ayrıntılı bir teşhis mesajı döner.
>
> Bu dokümanda tüm uçlar taban URL'e **göreli** yazılmıştır.

Test dosyalarındaki (`HDFilmcehennemiTest.py`, `DiziboxTest.py`) interaktif CLI işlevlerini HTTP endpoint'leri olarak sunan FastAPI tabanlı REST API. Ayrıca **kullanıcı hesabı** ve **cihazlar arası senkronizasyon** uçlarını barındırır.

Plan: `SYNC_AUTH_PLAN.md` (Faz 1–3, backend).

---

## Endpoint Haritası

### Eklenti ve extractor

| Yöntem | Endpoint | Açıklama |
|--------|----------|----------|
| `GET` | `/` | API sağlık kontrolü (`status` + `version`) |
| `GET` | `/api/plugins` | Tüm eklentileri listele |
| `GET` | `/api/plugins/{name}` | Eklenti detayı |
| `GET` | `/api/plugins/{name}/categories` | Eklenti kategorileri |
| `GET` | `/api/plugins/{name}/main-page` | Ana sayfa / kategori içerikleri |
| `GET` | `/api/plugins/{name}/search?q=...` | Tek eklentide arama |
| `GET` | `/api/plugins/{name}/detail?url=...` | İçerik detayı (film / dizi) |
| `GET` | `/api/plugins/{name}/links?url=...` | İzleme bağlantıları |
| `GET` | `/api/search?q=...` | **Tüm eklentilerde** arama |
| `GET` | `/api/extractors` | Yüklü extractor'ları listele |
| `POST` | `/api/extract` | URL'den medya çıkar |

### Kimlik doğrulama

| Yöntem | Endpoint | Yetki | Açıklama |
|--------|----------|-------|----------|
| `POST` | `/api/auth/signup` | — | Hesap oluştur + oturum token'ları |
| `POST` | `/api/auth/login` | — | Giriş yap |
| `POST` | `/api/auth/refresh` | — | Refresh token ile yeni access token |
| `POST` | `/api/auth/logout` | (opsiyonel) | Oturumu kapat (`204`) |
| `GET` | `/api/auth/me` | Bearer | Profil + bağlı cihaz listesi |

### Senkronizasyon

| Yöntem | Endpoint | Yetki | Açıklama |
|--------|----------|-------|----------|
| `POST` | `/api/sync/push` | Bearer | HLC'li kayıtları koşullu uygula |
| `GET` | `/api/sync/pull?since=...` | Bearer | Tam döküm veya delta çek |
| `GET` | `/api/sync/devices` | Bearer | Bağlı cihaz listesi (dizi döner) |
| `DELETE` | `/api/sync/devices/{device_id}` | Bearer | Cihazın yetkisini kaldır |

---

## Kimlik Doğrulama

`Authorization: Bearer <access_token>` başlığı zorunludur. Yetkisiz istekler **401** döner; istemci sessizce `POST /api/auth/refresh` dener, başarısızsa oturumu kapatır.

### Token doğrulama yolu

Doğrulama SDK'nın resmî `auth.get_claims()` metoduna devredilir:

| Token imzası | Doğrulama | Ağ turu |
|--------------|-----------|---------|
| Asimetrik (`ES256` / `RS256` / `EdDSA`) | JWKS'ten `kid` ile eşleşen açık anahtarla, yerelde | Yok |
| Simetrik (`HS256`, legacy) | Auth sunucusuna `get_user` çağrısı | ~20–40 ms |

`exp` her iki yolda da yerelde denetlenir. `role != "authenticated"` olan
token'lar (örneğin sızan bir `service_role` anahtarı) reddedilir.

### `POST /api/auth/signup`

```json
{ "email": "user@example.com", "password": "••••••••",
  "username": "sinemasever", "display_name": "Sinema Sever" }
```

**200**

```json
{ "access_token": "eyJhbGciOi...", "refresh_token": "v1-refresh-...",
  "token_type": "bearer", "expires_in": 3600,
  "user": { "id": "uuid", "email": "user@example.com",
            "username": "sinemasever", "display_name": "Sinema Sever",
            "avatar_url": null, "bio": null, "language": "tr",
            "is_private": false, "birth_date": null,
            "created_at": "...", "updated_at": "..." } }
```

| Kod | `detail` |
|-----|----------|
| `400` | `Bu e-posta adresi zaten kayıtlı.` |
| `409` | `Bu kullanıcı adı alınmış.` |
| `422` | `Gönderilen bilgiler geçersiz: …` (geçersiz e-posta / parola < 6 / kullanıcı adı < 3) |

`422` yanıtlarında `detail` her zaman **Türkçe metindir** (FastAPI'nin varsayılan
hata dizisi ve İngilizce Pydantic mesajları değil) — mobil istemci bu metni
doğrudan kullanıcıya gösterir. Örnek:

```json
{ "detail": "Gönderilen bilgiler geçersiz: email: geçerli bir e-posta adresi girin." }
```

### `POST /api/auth/login`

```json
{ "email": "user@example.com", "password": "••••••••" }
```

**200** → `signup` ile aynı gövde.

| Kod | `detail` |
|-----|----------|
| `400` | `E-posta veya parola hatalı.` |

> 🔴 Kimlik bilgisi hataları **bilinçli olarak 400** döner, 401 değil. Mobil
> istemci 401'i "oturumun süresi doldu" sanıp sessizce `refresh` dener ve
> başarısız olursa oturumu kapatır — yanlış parolada kullanıcı ekranından atılırdı.
> GoTrue'nin durum kodu sürümden sürüme değişebildiği için sunucu tarafında
> sabitlenir.

### `POST /api/auth/refresh`

```json
{ "refresh_token": "v1-refresh-..." }
```

**200** → yeni `access_token` + `refresh_token`. Süresi dolmuş token'da `401` `Oturumun süresi doldu. Lütfen tekrar giriş yap.`

### `POST /api/auth/logout`

`Authorization` başlığı gerekmez; token yoksa da `204` döner (istemci token'ları her hâlükârda yerel olarak siler). Token gönderilmişse GoTrue tarafındaki oturum kapatılır.

### `GET /api/auth/me`

**200**

```json
{ "user": { "id": "uuid", "email": "…", "username": "…", "…": "…" },
  "devices": [ { "device_id": "uuid", "device_name": "Salon TV",
                 "platform": "android", "app_version": "1.0.0",
                 "is_current": true, "last_pulled_at": "…",
                 "last_pushed_at": "…", "revoked_at": null,
                 "updated_at": "…" } ] }
```

`email` JWT iddialarından (`auth.users`), `username` ve profil alanları `user_profiles` tablosundan gelir.

---

## Senkronizasyon

### Karar modeli

Sunucu tüm otoritelerdir. LWW kararı `(hlc_wall, hlc_counter, device_id)` üçlüsüyle **bir kez ve merkezî** olarak verilir — iki cihaz aynı anda push etse bile sonuç deterministiktir.

| Durum | Sonuç |
|-------|-------|
| Gelen HLC > mevcut HLC | Uygulanır → `applied` |
| Gelen HLC = mevcut HLC | Reddedilir (`server_equal`) + sunucu sürümü |
| Gelen HLC < mevcut HLC | Reddedilir (`server_newer`) + sunucu sürümü |

`rejected` listesi **sessiz veri kaybını önler**: kaybeden cihaz sunucu sürümüyle uzlaşır, kullanıcı hiçbir şey kaybetmez.

### `POST /api/sync/push`

```json
{
  "device": { "device_id": "uuid", "device_name": "iPhone 15 Pro",
              "platform": "ios", "app_version": "1.0.0" },
  "schema_version": 1,
  "records": [
    { "item_type": "favorite", "content_id": "abc123",
      "payload": { "id": "abc123", "title": "Interstellar", "type": "movie" },
      "is_deleted": false,
      "hlc": { "wall": 1760000000000, "counter": 42 },
      "device_id": "uuid",
      "client_updated_at": "2026-10-01T12:00:00.000Z" }
  ],
  "documents": {
    "player_settings": {
      "payload": { "seekDuration": 15, "autoPlay": false },
      "hlc": { "wall": 1760000000000, "counter": 43 },
      "device_id": "uuid",
      "client_updated_at": "2026-10-01T12:00:05.000Z"
    }
  }
}
```

**200**

```json
{ "applied":    [ { "item_type": "favorite", "content_id": "abc123" } ],
  "rejected":   [ { "item_type": "favorite", "content_id": "xyz789",
                    "reason": "server_newer",
                    "server_version": {
                      "payload": { "…": "sunucudaki güncel sürüm" },
                      "is_deleted": true,
                      "hlc": { "wall": 1760000009999, "counter": 7 },
                      "device_id": "başka-cihaz",
                      "client_updated_at": "…", "server_updated_at": "…" } } ],
  "documents_applied":  [ "player_settings" ],
  "documents_rejected": [ { "doc_type": "theme", "reason": "server_newer",
                            "server_version": { "…": "…" } } ],
  "server_time": "2026-10-01T12:00:10.000Z" }
```

| Alan | Açıklama |
|------|----------|
| `item_type` | `favorite` \| `watchlist` \| `watch_history` \| `continue_watching` |
| `documents` anahtarı | `player_settings` \| `search_history` \| `theme` \| `selected_platform` \| `plugin_visibility` \| `category_visibility` |
| `is_deleted` | **Tombstone.** Silme bilgisini diğer cihazlara taşır. |
| `hlc` | `{ "wall": <epoch ms>, "counter": <mantıksal sayaç> }` |
| `client_updated_at` | Yalnızca denetim izi; karşılaştırmada **kullanılmaz** (cihaz saati güvenilmez) |

Aynı `(item_type, content_id)` için gelen çoklu kayıtlar HLC'ye göre tekilleştirilir; **giriş sırası sonucu etkilemez**.

> 🔴 **`server_time` yazma işlemlerinden ÖNCE ve veritabanı saatinden alınır.**
> İstemci bu değeri bir sonraki `pull?since=` parametresi olarak saklar ve
> karşılaştırma `updated_at > since` ile yapılır:
> * Damga yazmalardan sonra alınırsa → bu push sırasında başka bir cihazın
>   yazdığı satırlar bir sonraki çekişte hiç gelmez.
> * Damga API sunucusunun saatinden gelirse → DB saati gerideyse aynı sonuç.
>
> Ayrıntı ve çözüm için aşağıdaki **"Saat kayması"** bölümüne bakın.

**Boyut sınırları:** tek seferde en fazla **1000 kayıt** ve **2 MB**. Sınırlar istemcinin
boyut kapaklarından türetilmiştir (`SIZE_CAPS`: 500 favori + 100 liste + 50 geçmiş +
50 devam et = 700 kayıt). İstemci her senkronizasyonda tüm yerel durumunu gönderir ve
**parçalamaz**; bu yüzden sınır veri kaybına yol açmayacak kadar yüksektir.

### `GET /api/sync/pull`

`?since=` verilmezse **tam döküm**, verilirse **delta** döner.

```http
GET /api/sync/pull?since=2026-10-01T08:00:00.000Z
```

**200**

```json
{ "records":   [ { "item_type": "favorite", "content_id": "abc123",
                   "payload": { }, "is_deleted": false,
                   "hlc": { "wall": 1760000000000, "counter": 42 },
                   "device_id": "uuid",
                   "server_updated_at": "2026-10-01T09:00:00.000Z" } ],
  "documents": { "player_settings": { "payload": { }, "hlc": { },
                                      "device_id": "uuid", "is_deleted": false,
                                      "server_updated_at": "…" } },
  "deleted_content_ids": [ "eski-kayit-1" ],
  "server_time": "2026-10-01T12:00:10.000Z",
  "has_more": false }
```

* Tombstone kayıtları da döner — aksi halde silme diğer cihazlara ulaşamaz.
* `limit` (varsayılan **1000**, en fazla 2000) `records` sayısını sınırlar.
* `updated_at` **veritabanı saatidir**; karşılaştırma cihaz saatine göre yapılmaz.
  Damga da aynı kaynaktan alınır (bkz. "Saat kayması" bölümü).

> 🔴 **`server_time` okumalardan ÖNCE ve veritabanı saatinden alınır.**
> Damga okuma tamamlandıktan sonra alınırsa veya API sunucusunun saatinden
> gelirse, okuma sırasında başka bir cihazın yazdığı satırlar bir sonraki
> çekişte hiç gelmez — sessiz ve kalıcı veri kaybı. Ayrıntı için "Saat kayması"
> bölümüne bakın.

> ⚠️ **Sayfalama:** `has_more: true` dönerse **kayıtların TAMAMI henüz teslim
> edilmemiştir.** Varsayılan sayfa boyutu (1000) belgelenmiş en büyük veri
> kümesini (700 kayıt) tek sayfada sığdıracak şekilde seçilmiştir, bu yüzden
> mevcut mobil istemci için `has_more` normalde `false` olur. Yine de bir istemci
> `has_more: true` görürse `limit` değerini yükseltip yeniden çağırmalı ve
> **`server_time` damgasını yalnızca `has_more: false` olduğunda** saklamalıdır.

### `GET /api/sync/devices`

Opsiyonel `X-Device-Id` başlığı `is_current` işaretini ve `pull` sırasındaki
`last_pulled_at` damgasını bu cihaza yönlendirir.

```http
GET /api/sync/devices
X-Device-Id: uuid
```

**200** — JSON **dizi** döner (istemci doğrudan diziyi bekler).

> ⚠️ **Bilinen sınır:** Mevcut mobil istemci `X-Device-Id` başlığını göndermez.
> Bu durumda `is_current` "son push yapan cihaz" anlamına gelir. Aynı anda iki
> cihaz senkronize olduğunda yanlış cihaz "Bu Cihaz" olarak işaretlenebilir —
> bu yalnızca **görüntüleme** alanıdır, yetkilendirme `user_id` izolasyonuyla
> yapılır. Düzeltmek için istemcinin `X-Device-Id` göndermesi yeterlidir.

### `DELETE /api/sync/devices/{device_id}`

**200** `{ "device_id": "uuid", "revoked": true, "message": "…" }` · **404** cihaz yoksa.

İptal edilen cihaz listeden düşer ve tekrar push ederek kendini geri çağıramaz (`revoked_at` bilinçli olarak temizlenmez).

---

## Hata Semantiği

| Kod | Anlamı | İstemci davranışı |
|-----|--------|-------------------|
| 400 | Geçersiz gövde / desteklenmeyen belge türü / şema sürümü uyuşmazlığı / **hatalı giriş bilgileri** | Göster, tekrar deneme yok |
| 401 | Oturum geçersiz veya süresi dolmuş (token eksik/geçersiz/süresi dolmuş) | Sessiz `refresh` dene, başarısızsa çıkış yap |
| 404 | Cihaz bulunamadı veya zaten iptal edilmiş | Listeyi yenile |
| 409 | Kullanıcı adı alınmış | Form hatası göster |
| 413 | Gövde çok büyük (en fazla 1000 kayıt / 2 MB) **veya** karşılaştırma tavası aşıldı (5000 satır) | Veriyi küçültüp tekrar gönder |
| 422 | Gövde şema doğrulaması (`detail` metindir) | Form hatası göster |
| 502 | Kimlik doğrulama servisine ulaşılamadı | Üstel geri çekilme |
| 503 | Supabase yapılandırılmamış (`SUPABASE_URL` veya `SUPABASE_SERVICE_ROLE_KEY` eksik) | Sunucu tarafı hata; yerel veri korunur |

---

## Ortam Değişkenleri

`.env.example` dosyasına bakın. Kritik olanlar:

| Değişken | Zorunlu | Açıklama |
|----------|---------|----------|
| `SUPABASE_URL` | Evet | Proje adresi (`https://<proje>.supabase.co`). `api/app.py` tarafından `.env`'den yüklenir. |
| `SUPABASE_ANON_KEY` | Evet | GoTrue istemci anahtarı (Dashboard → API → "anon"/"publishable"). Yalnızca kayıt/giriş/token yenileme/çıkış çağrılarında kullanılır. |
| `SUPABASE_SERVICE_ROLE_KEY` | Evet | PostgREST anahtarı (Dashboard → API → "service_role"). **İstemciye verilmez.** RLS açık, politikasız tablolara yazmanın tek yoludur; eksikse API açık bir `503` döner. Yedek anahtar kabul edilmez — sessizce boş sonuç dönmesi, HTTP 200 görünürlüğünde senkronizasyonu çalışıyormuş gibi gösterirdi. |
| `CORS_ORIGINS` | Hayır | Virgülle ayrılmış origin beyaz listesi. Yalnızca tarayıcı istemcileri için gereklidir (React Native CORS motoru çalıştırmaz). Boşsa middleware hiç eklenmez — kapalı. `*` yazmayın. |
| `DEBUG` | Hayır | `1` ise `debug_log` çalışır. |
| `TMDB_API_KEY` | Hayır | Yalnızca medya meta veri zenginleştirme; API uçları bun olmadan da çalışır. |

### 🔑 JWT imza anahtarı: `.env`'e hiçbir şey yazmıyorsunuz

Supabase token imzalamayı iki şekilde destekliyor ve backend her ikisini de
otomatik tanıyor:

| İmza tipi | Nasıl doğrulanır | Ağ turu |
|-----------|-------------------|---------|
| **Asimetrik** (RSA / ECC P-256 / EdDSA) | JWKS'ten `kid` ile eşleşen açık anahtarla **yerelde** | Yok |
| **Simetrik** (HS256, "Legacy JWT Secret") | Auth sunucusuna `get_user` çağrısı | ~20–40 ms |

Uygulama doğrulamayı SDK'nın resmî `auth.get_claims()` metoduna devreder; o metot
token'ın `alg` / `kid` başlığına bakıp yolu kendisi seçer. Bunun pratik sonucu:

* **`.env`'de imza anahtarı tutmanız gerekmez** — `SUPABASE_JWT_SECRET` yoktur.
* **Anahtar döndürme ve iptal kod değişikliği gerektirmez** — JWKS `kid` eşleşmesi
  otomatik takip edilir.
* **Proje ileride asimetrik anahtara geçerse** uygulama kendiliğinden ağ turusuz
  moda düşer; hiçbir şey yapmanız gerekmez.

Panodaki **KEY ID bir kimliktir, imza anahtarı değildir** — bu sisteme hiç
kopyalanmaz. Referans: <https://supabase.com/docs/guides/auth/jwts>

### 🔴 Saat kayması: delta damgası neden veritabanından gelir?

Delta senkronizasyonu `updated_at > since` karşılaştırmasına dayanır ve
`updated_at` sütunu **veritabanının** `NOW()` değeriyle yazılır. Eğer `since`
damgası **API sunucusunun** saatinden gelseydi, iki saat arasındaki kayma sessiz
veri kaybına yol açardı: DB gerideyse, damgadan sonra yazılan satırlar
`updated_at > since` koşulunu sağlamaz ve bir sonraki çekişte hiç gelmez.

Bu projede ölçülen gerçek kayma **~0.95 saniye** (veritabanı API sunucusundan
geride) — yani hata "nadiren" değil, sürekli olurdu.

Bu yüzden damga `SELECT NOW()` yapan `server_now()` RPC'sinden alınır:

| Durum | Davranış |
|-------|----------|
| `server_now()` tanımlı | Damga doğrudan veritabanı saati — kayma etkisiz |
| Tanımlı değil (DDL çalıştırılmamış) | API saatinden **5 saniye geri** alınır + bir kez uyarı |

Güvenlik payı (5 sn) yalnızca son birkaç saniyedeki değişikliklerin yeniden
gelmesine yol açar; HLC birleştirmesi **idempotent** olduğu için sonuç değişmez.
Zaman damgasını `push` ve `pull` her ikisi de okuma/yazma **öncesinde** alır.

> `supabase/schema_sync.sql` içindeki `server_now()` fonksiyonunu SQL Editor'da
> çalıştırmak bu payı tamamen ortadan kaldırır. Kurulu değilse sunucu şu
> uyarıyı basar:
> `[UYARI] Veritabanında server_now() fonksiyonu yok — delta damgası API saatinden ve güvenlik payı kadar geriden alınıyor.`

Başlangıçta saat farkının kendisi de raporlanır (`DEBUG=1` ile `debug_log`).

Başlangıçta uygulama hangi modda olduğunu JWKS'e sorar ve konsola yazar:

```
JWT  Doğrulama asimetrik — JWKS'te 1 anahtar (ES256). İmzalar yerel
     doğrulanıyor, ağ turu yok.
```

Simetrik projelerde ise "her istekte Auth sunucusuna gidiliyor (~20–40 ms)"
uyarısı basar. Anahtar döndürme (rotation) sonrası ilk doğrulamada yeni `kid`
JWKS'te bulunamazsa SDK önbelleği düşürüp uç noktayı yeniden çeker — kod
tarafında hiçbir şey yapmanız gerekmez.
| `CORS_ORIGINS` | Hayır | Virgülle ayrılmış origin beyaz listesi. Yalnızca tarayıcı istemcileri için gereklidir (React Native CORS motoru çalıştırmaz). Boşsa middleware hiç eklenmez — kapalı. `*` yazmayın. |
| `DEBUG` | Hayır | `1` ise `debug_log` çalışır. |
| `TMDB_API_KEY` | Hayır | Yalnızca medya meta veri zenginleştirme; API uçları bun olmadan da çalışır. |

> **Kurulum adımları**
> 1. `supabase/schema_sync.sql` dosyasını Supabase Dashboard → SQL Editor'da çalıştırın.
> 2. Authentication → Providers → Email → **"Confirm email" → KAPALI**.
> 3. `.env.example`'ı `.env` olarak kopyalayın ve yukarıdaki değerleri girin.

---

## Dosya Yapısı

```
api/
├── __init__.py                # Paket tanımı
├── app.py                     # FastAPI uygulaması, load_dotenv, CORS, lifespan
├── deps.py                    # Singleton yöneticiler + get_current_user (Depends)
└── routes/
    ├── __init__.py            # Router export'ları
    ├── plugins.py             # /api/plugins/...
    ├── extractors.py          # /api/extractors, /api/extract
    ├── auth.py                # /api/auth/{signup,login,refresh,logout,me}
    └── sync.py                # /api/sync/{push,pull,devices,devices/{device_id}}

Core/Libs/
├── Supabase.py                # SupabaseManager: kullanıcı verisi deposu (async)
├── SupabaseAuth.py            # GoTrue async sarmalayıcı + yerel JWT doğrulama
├── SyncModels.py              # Senkronizasyon sözleşmesi + HLC karar mantığı
├── AuthModels.py              # Kimlik doğrulama sözleşmesi
└── TMDB.py                    # TMDB API v3 istemcisi

supabase/
└── schema_sync.sql            # DDL: user_profiles, user_documents, user_library,
                               #      user_devices + updated_at tetikleyicileri + RLS

tests/
├── test_auth_api.py           # TestClient ile API sözleşme + koruma testleri
└── test_sync_merge.py         # HLC kararı, koşullu upsert, delta, izolasyon
```

---

## Veri Modeli

| Tablo | Ne tutar | Anahtar |
|-------|----------|---------|
| `user_profiles` | Profil alanları (`username` UNIQUE) | `id` = `auth.users.id` |
| `user_documents` | Belge tipi başına tek satır (ayarlar, tema, görünürlük) | `(user_id, doc_type)` |
| `user_library` | Kayıt tipi başına satır + **tombstone** | `(user_id, item_type, content_id)` |
| `user_devices` | Cihaz envanteri, `revoked_at` ile iptal | `(user_id, device_id)` |

Üç kolon (`hlc_wall`, `hlc_counter`, `device_id`) LWW kararını deterministik yapar; `device_id` son çare eşitlik bozucudur.

Dört tabloda `updated_at` bir `BEFORE UPDATE` tetikleyicisiyle tazelenir —
`DEFAULT NOW()` yalnızca `INSERT`'te çalıştığı için, `ON CONFLICT DO UPDATE`
kullanılan `user_library` / `user_documents` tablolarında delta sorgusu aksi hâlde
bozulurdu.

---

## Testler

```bash
pytest                                  # tüm paket (ağ gerektirmez)
pytest tests/test_sync_merge.py -v      # HLC kararı + koşullu upsert + delta + izolasyon + DDL sözleşmesi
pytest tests/test_auth_api.py -v        # API sözleşmesi + 401/400/409/413/422 + JWT doğrulama
```

Canlı Supabase testleri varsayılan olarak **atlanır**:

```bash
$env:SUPABASE_LIVE_TESTS="1"
pytest -m live
```

---

## CLI ↔ API Eşleştirmesi

| CLI İşlevi | API Karşılığı |
|------------|---------------|
| `eklenti_ile_arama()` | `GET /api/plugins/{name}/search?q=...` |
| `get_main_page()` | `GET /api/plugins/{name}/main-page` |
| `sonuc_detaylari_goster()` | `GET /api/plugins/{name}/detail?url=...` |
| `baglanti_secenekleri_goster()` | `GET /api/plugins/{name}/links?url=...` |
| `extractor_ile_oynat()` | `POST /api/extract` |
| Tüm eklentilerde arama | `GET /api/search?q=...` |
