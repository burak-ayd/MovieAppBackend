"""
TMDB görsel zenginleştirme — plugin verisi ile TMDB arasındaki köprü.

AKIŞ (kullanıcı isteği)
-----------------------
1. Önce TMDB'ye istek atılır.
2. TMDB cevap verirse (poster/arka plan/logo/oyuncu fotoğrafı) bu görseller
   eklenti verisinin **yerine** yazılır.
3. TMDB çöker, rate limit'e takılır, eşleşme bulunamaz veya anahtar tanımlı
   değilse **hiçbir şey değişmez** — eklentinin kendi görselleri aynen kalır.

Eşleştirme sırası:
    `tmdb_id` → `imdb_id` → (isim + yıl) bulanık arama.
    Orijinal başlık (`original_title`) yabancı filmlerde Türkçe başlıktan
    daha isabetlidir; ilk deneme tutmazsa ona da bakılır.

KURAL
-----
* **Görsel alanlarda TMDB kazanır.** TMDB bir görsel döndürürse eklentinin
  değeri **değiştirilir** (kullanıcı isteği: "cevap alınırsa eklenti kaynağından
  çekilen veri ile değiştirilecek"). Eklenti görseli yalnızca TMDB boş döndüğünde
  devreye girer.
* **Görsel olmayan alanlarda eklenti korunur.** Kimlik ve fragman gibi alanlar
  yalnızca boşsa doldurulur — çalışan bir fragmanı TMDB'ninkiyle bozmak
  kazanç değil, kayıptır.
* Hiçbir alan **boşaltılmaz**.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable, Optional, Sequence

from Core.Libs.TMDB import (
    BACKDROP_BOYUT,
    LOGO_BOYUT,
    POSTER_BUYUK,
    POSTER_ORTA,
    TMDBClient,
    TMDBMedia,
    parse_year,
)


def _alan(nesne: Any, *isimler: str) -> Any:
    """Modelden (veya `extra="allow"` alanlarından) ilk bulunan değer."""
    for isim in isimler:
        deger = getattr(nesne, isim, None)
        if deger not in (None, "", [], {}):
            return deger
    return None


def _gorsel_ayarla(nesne: Any, alan: str, deger: Any) -> bool:
    """
    GÖRSEL alan: TMDB döndürdüyse **değer değiştirilir** (öncelik TMDB'de).

    Boşaltma yok: `deger` None/"" ise alan olduğu gibi bırakılır.
    """
    if not deger:
        return False
    try:
        setattr(nesne, alan, deger)
        return True
    except Exception:
        # Pydantic `extra="allow"` modellerinde alan tanımlı değilse yazamayız;
        # sessizce geçmek plugin verisinin bozulmasını engeller.
        return False


def _bosmu_ayarla(nesne: Any, alan: str, deger: Any) -> bool:
    """GÖRSEL OLMAYAN alan: yalnızca boşsa doldurur (koruyucu)."""
    if not deger:
        return False
    mevcut = getattr(nesne, alan, None)
    if mevcut:
        return False
    try:
        setattr(nesne, alan, deger)
        return True
    except Exception:
        return False


class TMDBEnricher:
    """
    Plugin modellerini TMDB görselleriyle zenginleştirir.

    `TMDB_API_KEY` tanımlı değilse tüm metotlar hızlıca no-op olur; API
    uçları bu durumda tamamen eklenti verisiyle çalışır.
    """

    def __init__(
        self,
        client: Optional[TMDBClient] = None,
        eszamanlilik: int = 5,
        zorunlu: bool = False,
    ) -> None:
        self.client = client or TMDBClient()
        self.eszamanlilik = max(1, int(eszamanlilik))
        self.zorunlu = zorunlu
        self._semaphore = asyncio.Semaphore(self.eszamanlilik)
        self.istatistik = {"islenen": 0, "zenginlesen": 0, "basarisiz": 0, "atlandi": 0}

    @property
    def aktif(self) -> bool:
        return self.client.enabled

    # ── Eşleştirme girdileri ────────────────────────────────────────────────

    @staticmethod
    def _medya_tipi(nesne: Any) -> Optional[str]:
        """Modelden TMDB medya tipi ipucu ('movie' | 'tv') çıkarır."""
        ham = (
            _alan(nesne, "media_type")
            or _alan(nesne, "content_type")
            or ""
        )
        ham = str(ham).lower()
        if ham in ("series", "tv", "dizi", "show", "anime"):
            return "tv"
        if ham in ("movie", "film"):
            return "movie"
        return None

    @staticmethod
    def _kimlikler(nesne: Any) -> tuple[Optional[int], Optional[str]]:
        tmdb_id = _alan(nesne, "tmdb_id")
        imdb_id = _alan(nesne, "imdb_id")
        try:
            tmdb_id = int(tmdb_id) if tmdb_id else None
        except (TypeError, ValueError):
            tmdb_id = None
        if imdb_id:
            imdb_id = str(imdb_id).strip() or None
        return tmdb_id, imdb_id

    @staticmethod
    def _yil(nesne: Any) -> Optional[int]:
        return parse_year(_alan(nesne, "year", "release_date", "first_air_date", "date"))

    @staticmethod
    def _basliklar(nesne: Any) -> list[str]:
        """Denenecek başlıklar: ana başlık, sonra orijinal başlık."""
        basliklar = []
        for ad in ("title", "original_title", "name"):
            deger = _alan(nesne, ad)
            if isinstance(deger, str) and deger.strip():
                basliklar.append(deger.strip())
        # yinelenenleri koru
        tekil = []
        for b in basliklar:
            if b not in tekil:
                tekil.append(b)
        return tekil

    # ── Tek öğe ──────────────────────────────────────────────────────────────

    async def _tekil_ara(self, nesne: Any, detay: bool) -> Optional[TMDBMedia]:
        """Kimlik varsa onunla, yoksa başlıkla TMDB'den medya bulur."""
        tmdb_id, imdb_id = self._kimlikler(nesne)
        tip = self._medya_tipi(nesne)
        yil = self._yil(nesne)

        async with self._semaphore:
            if tmdb_id or imdb_id:
                return await self.client.ara(
                    imdb_id=imdb_id, tmdb_id=tmdb_id, media_type=tip, detay=detay
                )

            for baslik in self._basliklar(nesne):
                sonuc = await self.client.ara(
                    title=baslik, year=yil, media_type=tip, detay=detay
                )
                if sonuc:
                    return sonuc
            return None

    # ── Görsel alanlarının uygulanması ───────────────────────────────────────

    @staticmethod
    def _liste_gorselleri(nesne: Any, media: TMDBMedia) -> int:
        """
        `SearchResult` / `MainPageResult` görselleri.

        Liste kartlarında w342 kullanılır: 3-4× daha hafif, ekranda w500 ile
        ayırt edilemiyor.
        """
        dolu = 0
        dolu += _gorsel_ayarla(nesne, "poster", media.poster_url(POSTER_ORTA))
        dolu += _gorsel_ayarla(nesne, "backdrop_url", media.backdrop_url())
        dolu += _gorsel_ayarla(nesne, "logo_url", media.logo_url(LOGO_BOYUT))
        dolu += _bosmu_ayarla(nesne, "imdb_id", media.imdb_id)
        dolu += _bosmu_ayarla(nesne, "tmdb_id", media.tmdb_id)
        return dolu

    @staticmethod
    def _detay_gorselleri(nesne: Any, media: TMDBMedia) -> int:
        """
        `MovieInfo` / `SeriesInfo` görselleri.

        Seriler `poster` alanını kullanır, filmler `poster_url`; ikisi de doldurulur.
        """
        dolu = 0
        poster = media.poster_url(POSTER_BUYUK)
        dolu += _gorsel_ayarla(nesne, "poster_url", poster)
        dolu += _gorsel_ayarla(nesne, "poster", poster)
        dolu += _gorsel_ayarla(nesne, "backdrop_url", media.backdrop_url(BACKDROP_BOYUT))
        dolu += _gorsel_ayarla(nesne, "logo_url", media.logo_url(LOGO_BOYUT))

        cast = media.cast_urls()
        if cast:
            dolu += _gorsel_ayarla(nesne, "cast_images", cast)

        dolu += _bosmu_ayarla(nesne, "imdb_id", media.imdb_id)
        dolu += _bosmu_ayarla(nesne, "tmdb_id", media.tmdb_id)

        # Fragman görsel değil ama aynı uçtan geliyor; plugin'in bulduğu korunur.
        if media.trailer_key:
            _bosmu_ayarla(
                nesne,
                "fragman_url",
                f"https://www.youtube.com/watch?v={media.trailer_key}",
            )
        return dolu

    async def zenginlestir(self, nesne: Any, detay: bool = False) -> Any:
        """
        Tek bir modeli zenginleştirir ve aynı nesneyi döndürür.

        TMDB kapalıysa/başarısızsa `nesne` olduğu gibi döner — çağıran taraf için
        hata ayırt etmesi gerekmez.
        """
        self.istatistik["islenen"] += 1

        if not self.aktif:
            self.istatistik["atlandi"] += 1
            return nesne

        try:
            media = await self._tekil_ara(nesne, detay=detay)
        except Exception:
            # Fail-open: zenginleştirme asla isteği düşüremez.
            if self.zorunlu:
                raise
            self.istatistik["basarisiz"] += 1
            return nesne

        if not media:
            self.istatistik["atlandi"] += 1
            return nesne

        try:
            dolu = (
                self._detay_gorselleri(nesne, media)
                if detay
                else self._liste_gorselleri(nesne, media)
            )
            if dolu:
                self.istatistik["zenginlesen"] += 1
        except Exception:
            if self.zorunlu:
                raise
            self.istatistik["basarisiz"] += 1

        return nesne

    async def zenginlestir_liste(self, ogeler: Sequence[Any], detay: bool = False) -> list[Any]:
        """Bir liste/dict sonucunu paralel olarak zenginleştirir."""
        if not ogeler:
            return list(ogeler)

        if not self.aktif:
            self.istatistik["atlandi"] += len(ogeler)
            return list(ogeler)

        sonuclar = await asyncio.gather(
            *(self.zenginlestir(oge, detay=detay) for oge in ogeler),
            return_exceptions=True,
        )

        # gather(hata) dönerse öğeyi olduğu gibi bırak: tek bir öğe tüm listeyi
        # düşürmemeli.
        duzeltilmis = []
        for oge, sonuc in zip(ogeler, sonuclar):
            if isinstance(sonuc, BaseException):
                self.istatistik["basarisiz"] += 1
                duzeltilmis.append(oge)
            else:
                duzeltilmis.append(sonuc)
        return duzeltilmis