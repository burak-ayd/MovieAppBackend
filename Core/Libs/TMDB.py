"""
TMDB API v3 istemcisi — medya görselleri için.

TASARIM İLKESİ: FAIL-OPEN
-------------------------
Bu sınıf hiçbir koşulda istisna atmaz. TMDB çöker, anahtar tanımlı değildir,
rate limit'e takılır, ağ kopar veya eşleşme bulunamazsa `None` döner. Çağıran
taraf (`Core/Helpers/TMDBEnricher.py`) plugin'in kendi verisini korur. Yani
görsel zenginleştirme bir "bonus"tur; asla veri kaybına yol açmaz.

Neden bu kadar savunmacı?
--------------------------
Ana sayfa tek seferde 20-40 öğe döner. Her öğe için TMDB'ye istek atmak
(1) hız sınırına (rate limit) ve (2) kullanıcıya bekletmeye yol açar. Bu yüzden:

* **Önbellek (TTL)**  — aynı içerik tekrar tekrar sorgulanmaz (varsayılan 7 gün).
  Negatif sonuçlar kısa süre (60 sn) önbelleğe alınır; "eşleşme yok" bir cevaptır.
* **Single-flight**   — eşzamanlı 20 istek aynı içeriği sorgularsa TEK istek atılır.
* **Devre kesici**    — üst üste hatalar (veya 429) gelirse kısa süre tüm
  istekler atlanır; çöken bir servise boşuna istek yağdırmayız.
* **Bounded eşzamanlılık** çağıran tarafta (TMDBEnricher) uygulanır.

Eşleştirme sırası (kullanıcı isteği):
1. `tmdb_id` (+ medya tipi) varsa → doğrudan detay
2. `imdb_id` varsa → `/find/{imdb_id}?external_source=imdb_id`
3. Yoksa → isim (+ yıl, + medya tipi) ile arama; bulanık eşleştirme
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

import httpx
from rapidfuzz import fuzz

# ── Görsel boyutları (TMDB image CDN) ────────────────────────────────────────
# Liste kartları için w342 (listede w500'in görünür farkı yok, 3× hafif),
# detay sayfası için w500, arka plan w1280, logo w500, oyuncu fotoğrafı w185.
POSTER_KUCUK = "w185"
POSTER_ORTA = "w342"
POSTER_BUYUK = "w500"
BACKDROP_BOYUT = "w1280"
LOGO_BOYUT = "w500"
PROFIL_BOYUT = "w185"

IMAGE_BASE = "https://image.tmdb.org/t/p"


def image_url(path: Optional[str], size: str) -> Optional[str]:
    """TMDB göreli yolunu tam URL'ye çevirir (`/abc.jpg` + boyut)."""
    if not path:
        return None
    return f"{IMAGE_BASE}/{size}{path if path.startswith('/') else '/' + path}"


# ── Başlık/yıl normalizasyonu ────────────────────────────────────────────────

# Parantez içi yıl: "Matrix (1999)" → "Matrix"
_YIL_PARANTEZ = re.compile(r"\((?:19|20)\d{2}[^)]*\)")
# Eklenti başlıklarındaki pazarlama kelimeleri ("... izle", "full türkçe")
_PAZARLAMA = re.compile(
    r"\b(izle|izleyin|full\s*(film|türkçe)?|filmini\s*full|alt\s*yazılı|altyazılı|"
    r"tr\s*dublaj|hd\s*türkçe|türkçe\s*dublaj|izlenir)\b",
    re.IGNORECASE,
)
_YIL_RAKAMI = re.compile(r"(19|20)\d{2}")


def normalize_title(raw: Optional[str]) -> str:
    """Bulanık eşleştirme için başlığı sadeleştirir (küçük harf, gereksiz kelime yok)."""
    if not raw:
        return ""
    metin = _YIL_PARANTEZ.sub(" ", str(raw))
    metin = _PAZARLAMA.sub(" ", metin)
    metin = re.sub(r"[^\w\s]", " ", metin, flags=re.UNICODE)
    return re.sub(r"\s+", " ", metin).strip().lower()


def parse_year(value: Any) -> Optional[int]:
    """`2026`, `"2026"`, `"2020-2024"`, `"1999)"` → yıl tam sayısı."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1900 <= value <= 2100 else None
    if isinstance(value, float):
        return int(value) if 1900 <= value <= 2100 else None
    eslesme = _YIL_RAKAMI.search(str(value))
    return int(eslesme.group(0)) if eslesme else None


_son_log = [0.0]


def _guvenli_yaz(metin: str) -> None:
    """
    Konsola yazar; kodlama hatasında **patlamaz**.

    Windows konsolunun codepage'i (cp1254) Türkçe karakterleri ve okları
    basamıyor. Böyle bir durumda `print` UnicodeEncodeError fırlatır ve bu
    hata, hata mesajını üretmek için çağrıldığımız yerde `_bellekli`'nin genel
    `except` bloğuna düşüp mesajı sessizce yutar. Kullanıcı en çok ihtiyaç
    duyduğu anda sebebi göremezdi. Bu yüzden burada asla istisna bırakmıyoruz.
    """
    try:
        print(metin, flush=True)
    except UnicodeEncodeError:
        try:
            print(metin.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass
    except Exception:
        pass


def _log(message: str) -> None:
    """Seyrek, kontrollü log — liste uçlarında her öğe için spam olmasın."""
    simdi = time.monotonic()
    if simdi - _son_log[0] < 30:
        return
    _son_log[0] = simdi
    _guvenli_yaz(f"[tmdb] {message}")


_V3_KEY_DESEN = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


def _anahtar_turu(anahtar: str) -> str:
    """
    Anahtarın TMDB türünü tahmin eder: `"v3"`, `"v4"` veya `"bilinmiyor"`.

    * **v3** — API Key (v3 auth): 32 onaltılık karakter. `?api_key=` ile gönderilir.
    * **v4** — Read Access Token: JWT (`baş.payload.imza`). `Authorization: Bearer` ile.

    Yanlış tür en sık hata kaynağıdır (bir Read Access Token `api_key` parametresine
    konulunca TMDB sessizce 401 döner). Bu yüzden ayrım bilinçlidir; bilinmeyen
    türde istek yine atılır, çünkü TMDB biçimini ileride değiştirebilir.
    """
    if not anahtar:
        return "bilinmiyor"
    if _V3_KEY_DESEN.match(anahtar):
        return "v3"
    if anahtar.count(".") == 2 and len(anahtar) > 100:
        return "v4"
    return "bilinmiyor"


@dataclass
class TMDBMedia:
    """Eşleşen medya + TMDB'den gelen görsel yolları."""

    media_type: str                      # "movie" | "tv"
    tmdb_id: int
    title: str = ""
    original_title: Optional[str] = None
    year: Optional[int] = None
    imdb_id: Optional[str] = None
    popularity: float = 0.0
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    logo_path: Optional[str] = None
    cast_images: dict[str, str] = field(default_factory=dict)   # ad → profil yolu
    trailer_key: Optional[str] = None

    # ── Hazır URL'ler (model alanlarına doğrudan atanır) ──
    def poster_url(self, size: str = POSTER_BUYUK) -> Optional[str]:
        return image_url(self.poster_path, size)

    def backdrop_url(self, size: str = BACKDROP_BOYUT) -> Optional[str]:
        return image_url(self.backdrop_path, size)

    def logo_url(self, size: str = LOGO_BOYUT) -> Optional[str]:
        return image_url(self.logo_path, size)

    def cast_urls(self, size: str = PROFIL_BOYUT) -> dict[str, str]:
        return {
            ad: url
            for ad, yol in self.cast_images.items()
            if (url := image_url(yol, size))
        }


class TMDBClient:
    """TMDB v3 istemcisi. Tüm hatalar yutulur; çağıran taraf fallback uygular."""

    # Bulutucu ayarları (opsiyonel env ile geçersiz kılınabilir)
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.themoviedb.org/3",
        timeout: float = 6.0,
        cache_ttl: int = 604_800,      # 7 gün
        negative_ttl: int = 60,
        eslesme_esigi: float = 78.0,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.getenv("TMDB_API_KEY", "")
        ).strip()
        self.base_url = (base_url or "https://api.themoviedb.org/3").rstrip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.negative_ttl = negative_ttl
        self.eslesme_esigi = eslesme_esigi

        # Devre kesici ayarları
        self.devre_esik = max(2, int(os.getenv("TMDB_CIRCUIT_THRESHOLD", "5")))
        self.devre_suresi = max(5.0, float(os.getenv("TMDB_CIRCUIT_SECONDS", "45")))
        # 401/403 yapılandırma hatasıdır; kendiliğinden düzelmez. Kısa devre
        # yerine uzun süre durup tek seferlik, ne yapılacağını söyleyen mesaj basarız.
        self.yetki_hatasi_suresi = max(60.0, float(os.getenv("TMDB_AUTH_BLOCK_SECONDS", "900")))
        self._blocked_until = 0.0
        self._ardik_basarisiz = 0
        self._yetki_hatasi_bildirildi = False
        self.anahtar_turu = _anahtar_turu(self.api_key)

        self._cache: dict[str, tuple[float, Any]] = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self._client: Optional[httpx.AsyncClient] = None

        # Sayaçlar (teşhis/test)
        self._sayac = {"istek": 0, "cache": 0, "basarisiz": 0, "429": 0}

    # ── Durum ────────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Anahtar tanımlı mı? Değilse tüm çağrılar ücretsizce None döner."""
        return bool(self.api_key)

    def uyari_mesaji(self) -> Optional[str]:
        """
        Anahtar şüpheliyse kullanıcıya gösterilecek açıklama (yoksa None).

        Uygulama açılışında bir kez yazdırılır; böylece hata ilk istekte değil
        daha ilk anda görünür.
        """
        if not self.api_key:
            return None
        if self.anahtar_turu != "bilinmiyor":
            return None
        return (
            f"TMDB_API_KEY tanımlı ama beklenen biçimde değil "
            f"(uzunluk {len(self.api_key)}, nokta {self.api_key.count('.')}). "
            "Bu değer geçerli bir TMDB anahtarı olmayabilir — TMDB "
            "'Invalid API key' döner ve görseller eklentiden gelmeye devam eder. "
            "https://www.themoviedb.org/settings/api adresinden "
            "'API Key (v3 auth)' değerini (32 karakter) kopyalayın."
        )

    def devrede(self) -> bool:
        """Devre kesici açık mı (şu an istek atılmıyor mu)?"""
        return time.monotonic() < self._blocked_until

    def istatistik(self) -> dict[str, Any]:
        return {**self._sayac, "cache_boyutu": len(self._cache), "devrede": self.devrede()}

    def onbellek_temizle(self) -> None:
        self._cache.clear()

    # ── Düşük seviye istek ───────────────────────────────────────────────────

    def _basarisiz(self, mesaj: str, ek_bekleme: float = 0.0) -> None:
        self._sayac["basarisiz"] += 1
        self._ardik_basarisiz += 1
        if self._ardik_basarisiz >= self.devre_esik:
            bekle = max(ek_bekleme, self.devre_suresi)
            self._blocked_until = time.monotonic() + bekle
            self._ardik_basarisiz = 0
            _log(f"devre kesici açıldı ({bekle:.0f}s): {mesaj}")
        else:
            _log(f"başarısız: {mesaj}")

    async def _istek(self, yol: str, params: Optional[dict] = None) -> Optional[dict]:
        """Tek HTTP GET. Hata durumunda None döner, istisna atmaz."""
        if not self.enabled or self.devrede():
            return None

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"Accept": "application/json", "Accept-Language": "tr-TR,tr;q=0.9"},
            )

        sorgu = dict(params or {})
        if self.anahtar_turu == "v4":
            # Read Access Token (v4) → Authorization başlığı
            self._client.headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            # API Key (v3) → sorgu parametresi
            sorgu["api_key"] = self.api_key

        self._sayac["istek"] += 1
        try:
            yanit = await self._client.get(f"{self.base_url}{yol}", params=sorgu)
        except Exception as e:
            self._basarisiz(f"{yol} → {type(e).__name__}")
            return None

        # 401/403: anahtar hatası. Kendiliğinden düzelmez ve her denemede
        # tekrarlanırsa logu boğar; uzun süre durup TEK seferlik yol gösteririz.
        if yanit.status_code in (401, 403):
            self._yetki_hatasi(yol, yanit)
            return None

        if yanit.status_code == 429:
            self._sayac["429"] += 1
            self._basarisiz(f"{yol} → 429 (rate limit)", ek_bekleme=self._retry_after(yanit))
            return None

        if yanit.status_code >= 400:
            self._basarisiz(f"{yol} → HTTP {yanit.status_code}")
            return None

        try:
            veri = yanit.json()
        except Exception:
            self._basarisiz(f"{yol} → geçersiz JSON")
            return None

        if not isinstance(veri, dict):
            return None
        self._ardik_basarisiz = 0
        return veri

    def _yetki_hatasi(self, yol: str, yanit: httpx.Response) -> None:
        """
        401/403 → yapılandırma hatası.

        Tekrarlanan denemeler anlamsız (anahtar değişmeden hep aynı sonuç) ve
        logu boğar; bu yüzden uzun süre devreye alınır ve mesaj bir kez basılır.
        """
        self._sayac["basarisiz"] += 1
        self._blocked_until = time.monotonic() + self.yetki_hatasi_suresi

        if self._yetki_hatasi_bildirildi:
            return
        self._yetki_hatasi_bildirildi = True

        tür = {"v3": "API Key (v3 auth)", "v4": "Read Access Token (v4)"}.get(
            self.anahtar_turu, "tanınmayan biçimde bir değer"
        )
        tmdb_mesaji = ""
        try:
            tmdb_mesaji = str((yanit.json() or {}).get("status_message") or "")[:160]
        except Exception:
            pass

        _guvenli_yaz(
            "[tmdb] HTTP "
            f"{yanit.status_code} ({yol}) → TMDB_API_KEY geçersiz.\n"
            f"       Kullanılan değer: {tür}, uzunluk {len(self.api_key)}.\n"
            f"       TMDB yanıtı: {tmdb_mesaji or '(mesaj yok)'}\n"
            "       ÇÖZÜM: https://www.themoviedb.org/settings/api → 'API Key (v3 auth)'\n"
            "       değerini .env içindeki TMDB_API_KEY ile değiştirin.\n"
            "       Bu arada zenginleştirme devre dışı; görseller eklentiden geliyor.\n"
            f"       {self.yetki_hatasi_suresi:.0f}s sonra tekrar denenecek."
        )

    @staticmethod
    def _retry_after(yanit: httpx.Response) -> float:
        """`Retry-After` başlığı ya da TMDB'nin bilinen 1 sn kuralı."""
        try:
            deger = float(yanit.headers.get("Retry-After", "1"))
        except (TypeError, ValueError):
            deger = 1.0
        return max(1.0, min(deger, 120.0))

    # ── Önbellek + single-flight ─────────────────────────────────────────────

    async def _bellekli(self, anahtar: str, uretici: Callable[[], Any]) -> Any:
        """Önbellekli, eşzamanlı çağrıları tek isteğe indirgenmiş çalıştırma."""
        if not self.enabled:
            return None

        simdi = time.time()
        kayit = self._cache.get(anahtar)
        if kayit is not None:
            yas, deger = kayit
            if simdi - yas < (self.cache_ttl if deger is not None else self.negative_ttl):
                self._sayac["cache"] += 1
                return deger

        # Aynı anahtar için hâlihazırda bir istek uçuşta mı?
        uctan = self._inflight.get(anahtar)
        if uctan is not None:
            try:
                return await asyncio.shield(uctan)
            except Exception:
                return None

        async def _calistir():
            return await uretici()

        gorev = asyncio.ensure_future(_calistir())
        self._inflight[anahtar] = gorev
        try:
            sonuc = await asyncio.shield(gorev)
        except Exception:
            sonuc = None
        finally:
            self._inflight.pop(anahtar, None)

        self._cache[anahtar] = (time.time(), sonuc)
        return sonuc

    # ── TMDB uçları ──────────────────────────────────────────────────────────

    async def _medya_detay(self, media_type: str, tmdb_id: int, detay: bool) -> Optional[TMDBMedia]:
        """`/movie/{id}` veya `/tv/{id}` — detay isteniyorsa logo/cast de gelir."""
        params: dict[str, Any] = {"language": "tr-TR"}
        if detay:
            # images → logo, credits → oyuncu fotoğrafları, videos → fragman
            params["append_to_response"] = "images,credits,videos,external_ids"

        veri = await self._istek(f"/{media_type}/{tmdb_id}", params)
        if not veri:
            return None
        return self._medya_modeli(media_type, veri, detay=detay)

    def _medya_modeli(self, media_type: str, veri: dict, detay: bool) -> Optional[TMDBMedia]:
        tmdb_id = veri.get("id")
        if not tmdb_id:
            return None

        # Arama sonuçlarında alan `media_type` ile gelmez; ayrıca TV sonuçlarında
        # `name`, filmlerde `title` kullanılır.
        gercek_tip = veri.get("media_type") or media_type
        if gercek_tip not in ("movie", "tv"):
            gercek_tip = media_type

        imdb_id = None
        dis_kimlikler = veri.get("external_ids") or {}
        if isinstance(dis_kimlikler, dict):
            imdb_id = dis_kimlikler.get("imdb_id") or None

        logo_path = None
        if detay:
            gorseller = veri.get("images") or {}
            logolar = gorseller.get("logos") or []
            # Önce Türkçe/İngilizce logo, yoksa ilk uygun olan.
            for tercih in ("tr", "en", None):
                for logo in logolar:
                    dil = ((logo.get("iso_639_1") == "tr") if tercih == "tr"
                           else ((logo.get("iso_639_1") == "en") if tercih == "en" else True))
                    if dil and logo.get("file_path"):
                        logo_path = logo["file_path"]
                        break
                if logo_path:
                    break

        cast_images: dict[str, str] = {}
        if detay:
            # Filmlerde `credits.cast`; TV'de yeni sürümlerde `aggregate_credits.cast`.
            kaynak = ((veri.get("credits") or {}).get("cast")
                      or (veri.get("aggregate_credits") or {}).get("cast") or [])
            for oyuncu in kaynak[:12]:
                ad = (oyuncu.get("name") or "").strip()
                yol = oyuncu.get("profile_path")
                if ad and yol:
                    cast_images[ad] = yol

        trailer_key = None
        if detay:
            videolar = ((veri.get("videos") or {}).get("results")) or []
            for video in videolar:
                if video.get("site") == "YouTube" and video.get("key"):
                    trailer_key = video["key"]
                    break

        return TMDBMedia(
            media_type=gercek_tip,
            tmdb_id=int(tmdb_id),
            title=(veri.get("title") or veri.get("name") or "").strip(),
            original_title=veri.get("original_title") or veri.get("original_name"),
            year=parse_year(veri.get("release_date") or veri.get("first_air_date")),
            imdb_id=imdb_id,
            popularity=float(veri.get("popularity") or 0.0),
            poster_path=veri.get("poster_path"),
            backdrop_path=veri.get("backdrop_path"),
            logo_path=logo_path,
            cast_images=cast_images,
            trailer_key=trailer_key,
        )

    async def _find_by_imdb(self, imdb_id: str) -> Optional[tuple[str, dict]]:
        """`/find/{imdb_id}` → (media_type, ilk sonuç)."""
        veri = await self._istek(
            f"/find/{imdb_id}",
            {"external_source": "imdb_id", "language": "tr-TR"},
        )
        if not veri:
            return None
        for anahtar, tip in (("movie_results", "movie"), ("tv_results", "tv")):
            sonuclar = veri.get(anahtar) or []
            if sonuclar:
                return tip, sonuclar[0]
        return None

    async def _search_multi(self, title: str, year: Optional[int],
                            media_type: Optional[str], language: str) -> list[dict]:
        params: dict[str, Any] = {"query": title, "language": language}
        if year:
            params["year"] = year
        veri = await self._istek("/search/multi", params)
        if not veri:
            return []
        return [r for r in (veri.get("results") or []) if isinstance(r, dict)]

    # ── Eşleştirme ───────────────────────────────────────────────────────────

    def _skorla(self, aday: dict, arama: str, year: Optional[int],
                media_type: Optional[str]) -> float:
        """
        0-100 arası benzerlik skoru.

        Yalnız başlık benzerliği yanıltır: "The Last of Us" ↔ "The Last of Us Part II"
        ya da iki farklı film aynı adı taşıyabilir. Bu yüzden yıl ve medya tipi
        sapması puanı düşürür, popülerlik yalnızca eşitlik bozucudur.
        """
        aday_tipler = [
            normalize_title(aday.get("title")),
            normalize_title(aday.get("name")),
            normalize_title(aday.get("original_title") or aday.get("original_name")),
        ]
        aday_tipler = [t for t in aday_tipler if t]
        if not aday_tipler:
            return 0.0

        baslik_skoru = max(fuzz.token_set_ratio(arama, t) for t in aday_tipler)

        skor = float(baslik_skoru)

        aday_yil = parse_year(aday.get("release_date") or aday.get("first_air_date"))
        if year and aday_yil:
            fark = abs(aday_yil - year)
            if fark == 0:
                skor = min(100.0, skor * 1.05 + 3)
            elif fark == 1:
                skor *= 0.92
            else:
                skor *= 0.60          # 2 yıl ve üzeri sapma: büyük ceza
        elif year:
            skor *= 0.92               # aday yılı bilinmiyor

        if media_type and (aday.get("media_type") or media_type) != media_type:
            skor *= 0.70               # film/dizi karışması

        # Popülerlik en fazla +2 puan: başlık ve yıl eşitse sıralayıcı.
        skor += min(float(aday.get("popularity") or 0.0) / 100.0, 2.0)
        return skor

    @staticmethod
    def _sorgu_varyantlari(title: str) -> list[str]:
        """
        TMDB'ye gönderilecek sorgu biçimleri: **önce temizlenmiş**, sonra ham.

        Neden önemli? Eklenti başlıkları kalabalıktır: "Esaretin Bedeli izle",
        "The Matrix Full Film Türkçe", "Dune (2021) Dizi". Canlı ölçüm:
        `"Esaretin Bedeli izle"` → TMDB 0 sonuç, `"esaretin bedeli"` → 1 sonuç.
        Yani pazarlama kelimeleri sorguyu bozar; önce temizlenmiş hâli denenir.
        """
        temiz = normalize_title(title)
        ham = str(title).strip()
        varyantlar: list[str] = []
        gorulen: set[str] = set()
        for v in (temiz, ham):
            # Büyük/küçük harf farkı anlamsızdır; TMDB araması büyük/küçük harf
            # duyarsızdır, aynı sorguyu iki kez göndermek israf olur.
            anahtar = v.lower()
            if v and anahtar not in gorulen:
                gorulen.add(anahtar)
                varyantlar.append(v)
        return varyantlar

    async def _search_best(self, title: str, year: Optional[int],
                           media_type: Optional[str]) -> Optional[TMDBMedia]:
        """İsimle arama; bulanık eşleştirme. Temizlenmiş sorgu önce denenir."""
        arama = normalize_title(title)
        if not arama:
            return None

        diller = ["tr-TR", "en-US"] if any(ord(c) > 127 for c in str(title)) else ["tr-TR"]
        varyantlar = self._sorgu_varyantlari(title)

        en_iyi: Optional[tuple[float, dict]] = None
        for dil in diller:
            for sorgu in varyantlar:
                sonuclar = await self._search_multi(sorgu, year, media_type, dil)
                for aday in sonuclar:
                    if aday.get("media_type") not in ("movie", "tv"):
                        continue
                    skor = self._skorla(aday, arama, year, media_type)
                    if en_iyi is None or skor > en_iyi[0]:
                        en_iyi = (skor, aday)
                # Yeterince güçlü eşleşme bulundu: daha fazla sorgu harcanmaz.
                if en_iyi and en_iyi[0] >= self.eslesme_esigi:
                    return self._medya_modeli(
                        en_iyi[1].get("media_type", "movie"), en_iyi[1], detay=False
                    )

        if not en_iyi or en_iyi[0] < self.eslesme_esigi:
            return None
        return self._medya_modeli(en_iyi[1].get("media_type", "movie"), en_iyi[1], detay=False)

    # ── Genel arayüz ─────────────────────────────────────────────────────────

    async def ara(
        self,
        *,
        imdb_id: Optional[str] = None,
        tmdb_id: Optional[int] = None,
        media_type: Optional[str] = None,
        title: Optional[str] = None,
        year: Optional[int] = None,
        detay: bool = False,
    ) -> Optional[TMDBMedia]:
        """
        Tek giriş noktası: kimlik varsa onunla, yoksa isimle eşleştirir.

        Sıra: `tmdb_id` → `imdb_id` → isim/yıl. Hiçbiri yoksa veya TMDB
        cevap vermezse `None` döner (çağıran taraf plugin verisini korur).
        """
        if not self.enabled:
            return None

        tip = media_type if media_type in ("movie", "tv") else None

        # 1) TMDB kimliği
        if tmdb_id:
            sonuc = await self._bellekli(
                f"id:{tip}:{tmdb_id}:{'d' if detay else 'h'}",
                lambda: self._medya_detay(tip or "movie", int(tmdb_id), detay),
            )
            if sonuc:
                return sonuc
            # Tip bilinmiyorsa diğerini dene
            if tip is None:
                return await self._bellekli(
                    f"id:tv:{tmdb_id}:{'d' if detay else 'h'}",
                    lambda: self._medya_detay("tv", int(tmdb_id), detay),
                )
            return None

        # 2) IMDb kimliği
        if imdb_id:
            temiz = str(imdb_id).strip()
            if temiz:
                bulunan = await self._bellekli(
                    f"imdb:{temiz}", lambda: self._find_by_imdb(temiz)
                )
                if bulunan:
                    bulunan_tip, aday = bulunan
                    if detay:
                        # find sonucu logo/cast içermez → detay uç noktasına git.
                        detayli = await self._bellekli(
                            f"id:{bulunan_tip}:{aday.get('id')}:d",
                            lambda: self._medya_detay(bulunan_tip, int(aday["id"]), True),
                        )
                        return detayli or self._medya_modeli(bulunan_tip, aday, detay=False)
                    return self._medya_modeli(bulunan_tip, aday, detay=False)
                return None

        # 3) İsim (+ yıl, + tip)
        if title:
            yil = parse_year(year)
            anahtar = f"ara:{normalize_title(title)}:{yil}:{tip or '-'}:{'d' if detay else 'h'}"

            async def _uret() -> Optional[TMDBMedia]:
                ham = await self._search_best(title, yil, tip)
                if not ham:
                    return None
                if detay and ham.tmdb_id:
                    detayli = await self._bellekli(
                        f"id:{ham.media_type}:{ham.tmdb_id}:d",
                        lambda: self._medya_detay(ham.media_type, ham.tmdb_id, True),
                    )
                    return detayli or ham
                return ham

            return await self._bellekli(anahtar, _uret)

        return None

    # ── Yaşam döngüsü ───────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """HTTP bağlantılarını kapat (lifespan shutdown)."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        self._inflight.clear()

    async def __aenter__(self) -> "TMDBClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()