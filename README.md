# MovieApp — STREAM

**Modüler medya kazıma, JIT çözümleme ve REST API motoru.**

Türkiye'de yayın yapan siteler için **eklenti** (kaynak site) ve **çıkarıcı**
(oynatıcı çözümleyici) tabanlı, tak-çalıştır bir kazıma motoru. Kaynak
siteleri ve oynatıcılar eklenti olarak eklenir; motor onları otomatik yükler,
aramayı tüm sağlayıcılarda paralel yapar ve oynatıcı linklerini çözümler.

Python 3.12 · FastAPI · 12 kaynak eklentisi · 22 çıkarıcı

### 🌐 Base URL

```
https://movieapi.burakaydogan.net.tr
```

Uçlar kendi `/api` önekini taşır — **taban URL'in sonuna `/api` yazmayın:**

| Doğru | Yanlış |
|---|---|
| `https://movieapi.burakaydogan.net.tr/api/plugins` | `https://movieapi.burakaydogan.net.tr/api/api/plugins` ❌ |

İkinci hâl 404 döner; API bu durumu yakalayıp ne yapman gerektiğini söyleyen
bir teşhis mesajıyla yanıtlar.

| | |
|---|---|
| **Swagger UI** | https://movieapi.burakaydogan.net.tr/docs |
| **ReDoc** | https://movieapi.burakaydogan.net.tr/redoc |
| **Sağlık ucu** | https://movieapi.burakaydogan.net.tr/ |
| **Mobil istemci** | `EXPO_PUBLIC_API_URL=https://movieapi.burakaydogan.net.tr` |

---

## 📛 Atıf ve lisans

Bu proje, aşağıdaki açık kaynak projenin **türevidir** ve ondan büyük ölçüde
kaynak almıştır:

### ⬆️ Upstream

> **☁️ CloudStream için Türkçe Eklentiler**
> [github.com/keyiflerolsun/Kekik-cloudstream](https://github.com/keyiflerolsun/Kekik-cloudstream)
>
> CloudStream için Türkçe yayın yapan sitelere ait eklentiler
> — Kotlin ile yazılmıştır.

| | |
|---|---|
| **Yazar** | [keyiflerolsun](https://github.com/keyiflerolsun) ❤️ |
| **Telif** | Copyright (C) 2023 — keyiflerolsun |
| **Lisans** | [GNU GPL v3.0](https://github.com/keyiflerolsun/Kekik-cloudstream/blob/master/LICENSE) |
| **Orijinal repo** | `recloudstream/TestPlugins` (fork) |
| **Durum** | 13 Mart 2025'te arşivlenmiş (salt okunur) |
| **Yazıldığı yer** | [KekikAkademi](https://t.me/KekikAkademi) |

**Bu depodaki eklenti ve çıkarıcı kodlarının büyük bir kısmı, yukarıdaki
projedeki Kotlin eklentilerinin Python'a portudur.** Port sırasında çözüm
mantığı korunmuş, yapılar FastAPI + async + Pydantic tabanlı Python
mimarisine uyarlanmıştır. Orijinal çözümleme algoritmalarının kaynağı:

| Bu proje | Upstream (Kotlin) |
|---|---|
| `Plugins/Dizibox.py` | `DiziBox` |
| `Plugins/DiziMom.py` | `DiziMom` |
| `Plugins/DiziPal.py`, `DiziPalOriginal.py` | `DiziPal`, `DiziPalOriginal` |
| `Plugins/Dizilla.py` | `Dizilla` |
| `Plugins/FilmMakinesi.py` | `FilmMakinesi` |
| `Plugins/FilmModu.py` | `FilmModu` |
| `Plugins/FullHDFilmizlesene.py` | `FullHDFilmizlesene` |
| `Plugins/HDFilmCehennemi.py` | `HDFilmCehennemi` |
| `Plugins/SelcukFlix.py` | `SelcukFlix` |
| `Plugins/SinemaCX.py` | `SinemaCX` |
| `Plugins/Sinewix.py` | `SineWix` |
| `Extractors/*` | Upstream çıkarıcıları |

Upstream ayrıca şu projelere teşekkür eder:

- [recloudstream/cloudstream](https://github.com/recloudstream/cloudstream)
- [hexated/cloudstream-extensions-hexated](https://github.com/hexated/cloudstream-extensions-hexated)
- [Jacekun/cs3xxx-repo](https://github.com/Jacekun/cs3xxx-repo)
- [recloudstream/extensions](https://github.com/recloudstream/extensions)

### ✍️ Bu proje

| | |
|---|---|
| **Oluşturan** | **Burak Aydoğan** |
| **Sürüm** | 1.1.0 |
| **Lisans** | [GNU GPL v3.0](https://github.com/keyiflerolsun/Kekik-cloudstream/blob/master/LICENSE) *(upstream ile aynı — türev çalışma olduğu için)* |

> ⚠️ **Lisans notu:** Upstream GPL-3.0 lisanslıdır ve bu proje ondan türetilmiş
> kod içerir. GPL-3.0, türev çalışmaların **aynı lisansla** dağıtılmasını ve
> **atfın korunmasını** gerektirir. Bu README'deki atıfın yanında deponun
> köküne upstream `LICENSE` metninin bir kopyasını eklemeniz gerekir.

---

## ✨ Özellikler

**Kaynak katmanı**
- 12 kaynak eklentisi (dizi + film), tek satır `Plugins/` klasörüne bırakılarak eklenir
- Otomatik keşif: yeni eklenti dosyası yazıldığı anda API yeniden başlatmada yüklenir
- Kategori sayfalama, arama, detay, sezon/bölüm ağacı, benzer içerik
- Cloudflare korumalı siteler için TLS parmak izi taklidi (`curl_cffi`) ve
  gerektiğinde Playwright

**Çıkarıcı katmanı**
- 22 çıkarıcı: AES/CBC, PBKDF2, P.A.C.K.E.R. unpacking, hex kaçış çözme,
  özel XOR/Caesar karışımları
- Oynatıcı → çıkarıcı otomatik eşleştirme (`ExtractorManager.map_links_to_extractors`)
- Lazy-load oynatıcılar için `EmbedHelper`: `src="about:blank"` tuzağını ve
  21 farklı `data-*` özniteliğini tek yerde çözer

**API katmanı**
- FastAPI, tam Swagger (`/docs`) ve ReDoc (`/redoc`)
- Kullanıcı hesabı (Supabase GoTrue) ve cihazlar arası delta senkronizasyonu
- JWT doğrulaması asimetrik (JWKS) veya simetrik (HS256) modu otomatik seçer
- Türkçe, düz okunabilir hata mesajları (`detail` her zaman metin)
- CORS varsayılan olarak **kapalı** — beyaz liste gerekir

**Domain kendini onarma**
- `Core/Helpers/Kontrol.py` eklenti `main_url` değerlerini otomatik günceller
- Günlük 18:00 + bir eklenti hata verdiğinde anında çalışır
- Güncellenen domainler kalıcıdır ve çalışan API'ye **yeniden yüklenir**

**Dağıtım**
- Tek imaj, iki servis (`api` + `domain-updater`)
- Non-root kullanıcı, düşük ayrıcalıklı container, log rotasyonu
- Sağlık kontrolü: HTTP ucu + süreç kalp atışı

---

## 📂 Dizin yapısı

```
.
├── api/                      # FastAPI uygulaması
│   ├── app.py                #   uygulama kurulumu, hata işleyicileri, lifespan
│   ├── deps.py               #   paylaşılan bağımlılıklar (singleton) + Bearer auth
│   └── routes/               #   plugins · extractors · auth · sync
├── Core/
│   ├── Extractor/            # çıkarıcı tabanı, yükleyici, yönetici, modeller
│   │   └── Players/          #   ortak oynatıcı çözümleme tabanları
│   ├── Helpers/
│   │   ├── Cli.py            #   konsol (rich) ve hata yönetimi
│   │   ├── EmbedHelper.py    #   lazy-load gömülü adres çıkarma
│   │   ├── HTMLHelper.py     #   HTML çekme/ayrıştırma, Cloudflare aşma
│   │   ├── Kontrol.py        #   domain otomatik güncelleme
│   │   └── Sifreleme.py      #   CryptoJS · HexCodec · Packer
│   ├── Libs/                 # Supabase, Supabase Auth, TMDB, modeller
│   ├── Media/                # yerel oynatma (yt-dlp / mpv / vlc)
│   └── Plugin/               # eklenti tabanı, yükleyici, yönetici, modeller
├── Extractors/               # 22 oynatıcı çıkarıcısı
├── Plugins/                  # 12 kaynak eklentisi
├── ops/                      # container süreç yönetimi
│   ├── supervisor.py         #   uvicorn + yeniden yükleme denetleyicisi
│   ├── domain_watcher.py     #   09:00 + 18:00 slotlarında domain kontrolü/güncellemesi
│   └── healthcheck.py        #   sağlık kontrolü
├── docker/entrypoint.sh      # container giriş noktası
├── Dockerfile
├── docker-compose.yml        # üretim (Coolify)
└── docker-compose.dev.yml    # yerel geliştirme
```

---

## 🚀 Hızlı başlangıç (yerel)

```bash
# 1) Bağımlılıklar
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt

# 2) Ortam değişkenleri
copy .env.example .env          # Windows
# veya: cp .env.example .env

# 3) API'yi çalıştır
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

Swagger: <http://localhost:8000/docs>

Eklenti listesini doğrula:

```bash
curl http://localhost:8000/api/plugins
```

---

## 🐳 Docker / Coolify dağıtımı

```bash
docker compose up -d --build
```

İki servis, tek imaj:

| Servis | Görev | Port |
|---|---|---|
| `api` | FastAPI (uvicorn) + yeniden yükleme denetleyicisi | 8000 |
| `domain-updater` | Domain güncelleyici (18:00 + hata anında) | — |

İki birim hacmi kritiktir:

| Volume | Mount | Neden |
|---|---|---|
| `plugins` | `/app/Plugins` | `Kontrol.py` eklenti dosyalarını **düzenler**. Volume yoksa güncellenen domainler her redeploy'da kaybolur. |
| `state` | `/state` | `watcher` ↔ `api` iletişimi: kilit, durum ve yeniden yükleme bayrağı. |

### Coolify ayarları

1. **Resource Type:** Docker Compose → aşağıdaki değişkenleri Coolify UI'dan tanımlayın
2. **Environment Variables:**

   ```
   PUBLIC_API_URL=https://movieapi.burakaydogan.net.tr
   SUPABASE_URL=https://<proje>.supabase.co
   SUPABASE_ANON_KEY=<anon key>
   SUPABASE_SERVICE_ROLE_KEY=<service role key>
   TMDB_API_KEY=<tmdb key>
   CORS_ORIGINS=<tarayıcı istemcinizin origin'i>
   TZ=Europe/Istanbul
   ```

   `CORS_ORIGINS` yalnızca **tarayıcı tabanlı** istemci için gereklidir ve
   oraya API'nin değil **istemcinin** adresi yazılır. React Native / Expo
   istemcisi CORS motoru çalıştırmadığı için boş bırakılabilir.

3. **Domain:** `api` servisine bağlayın → `movieapi.burakaydogan.net.tr`, port **8000**
4. Sağlık kontrolü tanımlıdır; Coolify yönlendirmeyi buna göre başlatır

> **Değiştirmeyin:** `API_INTERNAL_URL` (`http://api:8000`) ve `API_BIND`
> (`0.0.0.0`) değerleri public domain olmamalıdır. Biri container→container
> trafiği, diğeri host portudur; ikisi de Coolify proxy'sinin çalışması için
> gereklidir. Ayrıntılı açıklama `docker-compose.yml` içinde.

> Sırları `docker-compose.yml` içindeki `environment:` bloğuna yazmayın —
> oraya boş bir varsayılan koymak, Coolify'in inject ettiği değerleri ezer.
> Blok bilinçli olarak yalnızca operasyonel değişkenleri içerir.

### Zamanlanmış görev ayarları

Domain kontrolü **günde iki kez** yapılır: sabah `PROBE_HOUR:PROBE_MINUTE`
slotunda yoklama, akşam `UPDATE_HOUR:UPDATE_MINUTE` slotunda yoklama + domain
güncellemesi. Slotlar arasında dışarıya hiçbir istek atılmaz.

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `PROBE_HOUR` / `PROBE_MINUTE` | `9` / `0` | Sabah domain kontrolü saati (`TZ` ile yorumlanır) |
| `UPDATE_HOUR` / `UPDATE_MINUTE` | `18` / `0` | Akşam slotu: kontrol + günlük güncelleme |
| `HEARTBEAT_INTERVAL` | `60` | Bekleme sırasında kalp atışı aralığı (saniye, < 180 olmalı) |
| `ERROR_THRESHOLD` | `1` | Kaç eklenti hata verirse güncelleme |
| `ERROR_COOLDOWN` | `1800` | İki güncelleme arası en az bekleme |
| `PROBE_QUERY` | `matrix` | Yoklama arama sorgusu |
| `PROBE_REQUIRE_RESULTS` | `0` | Boş sonuç hata sayılsın mı (kapalı önerilir) |
| `RUN_ON_START` | `0` | Watcher açılışta da bir kez güncellesin mi |
| `API_WORKERS` | `1` | ⚠️ 1'den fazlası `Plugins/` dosyalarına eşzamanlı yazma riski taşır |

> `DOMAIN_CHECK_INTERVAL` (eski 5 dakikalık yoklama aralığı) kullanımdan
> kaldırıldı; artık yalnızca uyarı üretir ve yok sayılır.

### Elle domain güncelleme

```bash
docker compose run --rm domain-updater kontrol
```

---

## 🔌 API uçları

| Yöntem | Yol | Açıklama |
|---|---|---|
| `GET` | `/` | Sağlık ucu |
| `GET` | `/api/plugins` | Yüklü eklentiler ve `main_url` bilgisi |
| `GET` | `/api/search?q=` | Tüm eklentilerde paralel arama |
| `GET` | `/api/plugins/{name}` | Eklenti detayı |
| `GET` | `/api/plugins/{name}/categories` | Kategoriler |
| `GET` | `/api/plugins/{name}/main-page` | Ana sayfa içerikleri (sayfalı) |
| `GET` | `/api/plugins/{name}/search?q=` | Eklentide arama |
| `GET` | `/api/plugins/{name}/detail?url=` | Film/bölüm detayı |
| `GET` | `/api/plugins/{name}/links?url=` | Çözülmüş izleme bağlantıları |
| `GET` | `/api/plugins/{name}/random` | Eklentiden rastgele içerik |
| `GET` | `/api/plugins/random` | Tüm eklentilerden rastgele içerik |
| `GET` | `/api/extractors` | Yüklü çıkarıcılar |
| `GET`/`POST` | `/api/extract` | Embed/medya URL'sini çözümle |
| `POST` | `/api/auth/signup` · `/login` · `/refresh` · `/logout` | Kimlik doğrulama |
| `GET` | `/api/auth/me` | Oturum ve profil |
| `POST` | `/api/sync/push` · `GET /api/sync/pull` | Delta senkronizasyon |
| `GET` | `/api/sync/devices` · `DELETE /api/sync/devices/{id}` | Cihaz yönetimi |

**Not:** Taban URL'in sonuna `/api` **yazmayın**. FastAPI hata işleyicisi bu
durumu yakalar ve sorunu düz Türkçe bir mesajla bildirir.

Kimlik doğrulama gerektiren uçlar `Authorization: Bearer <access_token>` bekler.

---

## 🧩 Yeni eklenti ekleme

`Plugins/` klasörüne tek dosya eklemek yeterlidir:

```python
# Plugins/OrnekSite.py
from typing import List
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SearchResult


class OrnekSite(PluginBase):
    name     = "ÖrnekSite"
    language = "tr"
    main_url = "https://www.example.com"

    main_page = {"Ana Sayfa": f"{main_url}/", "Filmler": f"{main_url}/filmler/"}

    async def search(self, query: str) -> List[SearchResult]:
        istek = await self.httpx.get(f"{self.main_url}/arama?q={query}")
        secici = self._secici(istek.text)

        return [
            SearchResult(
                title=baslik.strip(),
                url=self.fix_url(adres),
                description=(aciklama or "").strip() or None,
                poster=self.fix_url(afis) if afis else None,
                year=self._yil(baslik),
            )
            for baslik, adres, afis, aciklama in (...)
        ]
```

Çıkarıcı eklemek için aynı şekilde `Extractors/` klasörüne bir dosya ekleyin ve
`ExtractorLoader`'ın bulmasını sağlayın.

**Lazy-load uyarısı:** Oynatıcı siteleri iframe'i tembel yükler
(`src="about:blank"` + `data-src="<gerçek adres>"`). Ham `src` okumak sessizce
bozuk adres üretir. Şunu kullanın:

```python
embed = self.gomulu_adres(secici, "div.video p iframe")   # PluginBase kısayolu
# veya doğrudan
from Core.Helpers.EmbedHelper import EmbedHelper
embed = EmbedHelper.gomulu_adres(iframe)
```

---

## 🛡️ Güvenlik notları

- **Supabase service role key** asla istemciye verilmez; yalnızca sunucuda kalır
- CORS varsayılan olarak kapalıdır; `allow_credentials` **false**'tur
  (Bearer token taşınır, cookie yok)
- JWT doğrulaması simetrik (HS256) olduğunda her istekte Auth sunucusuna gider.
  Dashboard → Authentication → JWT Signing Keys bölümünden asimetrik bir
  anahtara geçmek ağ turunu otomatik keser, kod değişikliği gerektirmez
- Senkronizasyon delta karşılaştırması `updated_at > since` üzerine kuruludur;
  `supabase/schema_sync.sql` içindeki `server_now()` fonksiyonu kurulu değilse
  saat kayması sessiz veri kaybına yol açabilir
- Container non-root çalışır, `cap_drop: ALL` uygulanır

---

## 🧪 Testler

```bash
pytest tests -q
```

| Test dosyası | Kapsam |
|---|---|
| `tests/test_embed_helper.py` | Lazy-load gömülü adres çıkarma (70 senaryo) |
| `tests/test_plugins.py` | Eklenti yükleme, arama, detay, ana sayfa |
| `tests/test_auth_api.py` | Kimlik doğrulama uçları |
| `tests/test_sync_merge.py` | Senkronizasyon birleştirme kuralları |

---

## 📝 Ortam değişkenleri

| Değişken | Zorunlu | Açıklama |
|---|---|---|
| `SUPABASE_URL` | evet* | Proje adresi. Eksikse giriş ve senkronizasyon uçları 503 döner |
| `SUPABASE_ANON_KEY` | evet* | GoTrue istemci anahtarı |
| `SUPABASE_SERVICE_ROLE_KEY` | evet* | PostgREST sunucu anahtarı. **İstemciye vermeyin** |
| `PUBLIC_API_URL` | hayır | İstemcilere gösterilen taban adres. Yalnızca teşhis mesajlarında kullanılır. Varsayılan `https://movieapi.burakaydogan.net.tr` |
| `CORS_ORIGINS` | hayır | Virgülle ayrılmış **istemci** origin beyaz listesi (API'nin adresi değil). Boşsa CORS kapalı — mobil istemci için doğru seçim |
| `TMDB_API_KEY` | hayır | Yalnızca meta veri zenginleştirme |
| `DEBUG` | hayır | `1/true/yes/on` → ayrıntılı günlük |
| `TZ` | hayır | Varsayılan `Europe/Istanbul` (18:00 kuralı buna bağlı) |

\* `api/app.py` eksik yapılandırmayı başlangıçta gürültülü bir uyarı olarak
bildirir ve **çalışmaya devam eder**; eklenti uçları Supabase'a ihtiyaç duymaz.

**Coolify'da `docker-compose.yml`'in `environment:` bloğuna sır yazmayın.**
O blok bilinçli olarak yalnızca operasyonel değişkenleri içerir; oraya boş bir
varsayılan koymak Coolify'in inject ettiği değerleri ezerdi. Sırlar Coolify
UI → Environment Variables üzerinden verilir.

---

## 📄 Durum

- API sürümü **1.1.0**
- 12 kaynak eklentisi · 22 çıkarıcı · 4 test dosyası
- Upstream (Kekik-cloudstream) 13 Mart 2025'te arşivlendiği için bu port,
  güncel site değişikliklerini takip etmek için ayrı bakım gerektirir

---

## 🔗 İlgili bağlantılar

- Upstream · [github.com/keyiflerolsun/Kekik-cloudstream](https://github.com/keyiflerolsun/Kekik-cloudstream)
- CloudStream · [recloudstream/cloudstream](https://github.com/recloudstream/cloudstream)
- CloudStream dokümanı · [recloudstream.github.io/csdocs](https://recloudstream.github.io/csdocs/)

---

<div align="center">

**Oluşturan: Burak Aydoğan** ❤️

*Kotlin çözümleme algoritmaları için
[github.com/keyiflerolsun/Kekik-cloudstream](https://github.com/keyiflerolsun/Kekik-cloudstream)
projesine teşekkürler — GPL-3.0.*

</div>
