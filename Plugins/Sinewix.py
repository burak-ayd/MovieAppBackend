import re

from typing import Any, Dict, List, Optional, Union

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SearchResult, MainPageResult, MovieInfo, SeriesInfo, Episode


# Oluşturan: Burak Aydoğan
#
# Site saf API tabanlıdır; HTML sayfaları 403 döner. Tüm veriler
# /public/api/... uçlarından, `hash256` + `signature` başlıklarıyla gelir.
#
# Canlı doğrulama notları:
#   * Kategoriler `?page=N` ile gerçekten sayfalanıyor.
#   * Dizi detayı (`/series/show/{id}`) sezon -> bolum -> videos[0].link veriyor
#     ve bu linkler doğrudan `.mkv` dosyaları (Örn: Glitter.S01E01.mkv).
#   * "Yeni Bölümler" kayıtları `link` alanında doğrudan video adresi taşıyor.
#   * Film detay ucu (`/media/movie/info/{id}`) sunucuda YOK (404) ve film
#     kayıtlarında video alanı bulunmuyor; bu yüzden filmler oynatılamıyor.
#     Bu durum kaynak eklentide de aynı (Kotlin'daki film dalı çalışmıyor).

# API erişim belirteci
API_TOKEN = "9iQNC5HQwPlaFuJDkhncJ5XTJ8feGXOJatAA"

# /public/api uçlarının istediği sabit imza başlıkları
HASH256 = "711bff4afeb47f07ab08a0b07e85d3835e739295e8a6361db77eebd93d96306b"

SIGNATURE = (
    "3082058830820370a00302010202145bbfbba9791db758ad12295636e094ab4b07dc24300d06092a864886f70d01010b05003074310b30"
    "09060355040613025553311330110603550408130a43616c69666f726e6961311630140603550407130d4d6f756e7461696e2056696577"
    "31143012060355040a130b476f6f676c6520496e632e3110300e060355040b1307416e64726f69643110300e06035504031307416e6472"
    "6f69643020170d3231313231353232303433335a180f32303531313231353232303433335a3074310b3009060355040613025553311330"
    "110603550408130a43616c69666f726e6961311630140603550407130d4d6f756e7461696e205669657731143012060355040a130b476f"
    "6f676c6520496e632e3110300e060355040b1307416e64726f69643110300e06035504031307416e64726f696430820222300d06092a86"
    "4886f70d01010105000382020f003082020a0282020100a5106a24bb3f9c0aaf3a2b228f794b5eaf1757ba758b19736a39d1bdc73fc983"
    "a7237b8d5ca5156cfa999c1dab3418bbc2be0920e0ee001c8aa4812d1dae75d080f09e91e0abda83ff9a76e8384a4429f4849248069a59"
    "505b12ac2c14ba2e4d1a13afcdaf54e508697ff928a9f738e6f4a6fc27409c55329eb149b5ff89c5a2d7c06bf9e62086f955cad17d7be2"
    "623ee9d5ec56068eadc23cb0965a13ff97d49fe10ef41afc6eeca36b4ace9582097faff89f590bc831cdb3a69eec5d15b67c3f2cad49e3"
    "7ed053733e3d2d400c47755b932bdbe15d749fd6ad1dce30ba5e66094dfb6ee6f64cafb807e11b19a990c5d078c6d6701cda0bdeb21e99"
    "404ff166074f4c89b04c418f4e7940db5c78647c475bcfb85d4c4e836ee7d7c1d53e9e736b5d96d4b4d8b98209064b729ac6a682d55a6a"
    "930e518d849898bb28329ca0aaa133b5e5270a9d5940cac6af4802a57fd971efda91abb602882dd6aa6ce2b236b57b52ee2481498f0cac"
    "bcc2c36c238bc84becad7eaaf1125b9a1ca9ded6c79f3f283a52050377809b2a9995d66e1636b0ed426fdd8685c47cb18e82077f4aefcc"
    "07887e1dc58b4d64be1632f0e7b4625da6f40c65a8512a6454a4b96963e7f876136e6c0069a519a79ad632078ed965aa12482458060c03"
    "0ed50db706d854f88cb004630b49285d8af8b471ff8f6070687826412287b50049bcb7d1b6b62ef90203010001a310300e300c0603551d"
    "13040530030101ff300d06092a864886f70d01010b0500038202010051c0b7bd793181dc29ca777d3773f928a366c8469ecf2fa3cfb076"
    "e8831970d19bb2b96e44e8ccc647cf0696bb824ac61c23d958525d283cab26037b04d58aa79bf92192db843adf5c26a980f081d2f0e14f"
    "759fc5ff4c5bb3dce0860299bfe7b349a8155a2efaf731ba25ce796a80c1442c7bf80f8c1a7912ff0b6f6592264315337251a846460194"
    "fa594f81f38f9e5233a63201e931ad9cab5bf119f24025613f307194eaa6eb39a83f3c05a49ba34455b1aff7c6839bbb657d9392ffdf39"
    "7432af6e56ba9534a8b07d7060fe09691c6cf07cb5324f67b3cc0871a8c621d81fe71d71085c55206a4f57e25f774fd4b979b299e8bb07"
    "6b50fca42fa57da2d519fd35a4a7c0137babaed4345f8031b63b6a71f5e8268f709d658ccd7c2a58849379d25bfa598c3f4a2c3d9b7d89"
    "285fefeb7f0ec65137d38b08ce432a15688b624a179e6a4a505ebc3bcdfbc4d4330508ee2d8d0f016924dcec21a6838ef7d834c6f43bde"
    "4a5201ed0b3bb4e9bd377b470e36bcf5bc3d56169dbd8e39567aa7dce4d1a8a8a54a5e1aa6fb1a8aab0062669a966f96e15ccce6fe12ea"
    "5e6a8b8c8823bdc94988ca39759fd1cc8fd8ae5c3d74db50b174cf7d77655016c075c91d439ed01cc0a9f695c99fad3b5495fb6cb1e01a"
    "5fa020cc6022a85c07ec55f9eba89719f86e49d34ab5bd208c5f70cced2b7b7963c014f8404432979b506de29e"
)

# Doğrudan video dosyası uzantıları (Kotlin loadLinks ile aynı)
DOGRUDAN_DOSYA = re.compile(r"\.(mkv|mp4|m3u8|webm|avi)(\?|$)", re.IGNORECASE)


class Sinewix(PluginBase):
    """Sinewix kaynak site kazıyıcısı."""

    name = "Sinewix"
    language = "tr"
    main_url = "https://ydfvfdizipanel.ru"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"
    description = "Sinewix - Dizi, film ve anime izleme platformu"

    headers = {
        "hash256": HASH256,
        "signature": SIGNATURE,
        "User-Agent": "EasyPlex (Android 14; SM-A546B; Samsung Galaxy A54 5G; tr)",
        "Accept": "application/json",
        "Referer": f"{main_url}/",
    }

    # (yol, görünen ad) — Kotlin mainPageOf listesi. Yorumda bırakılan film ve
    # anime uçları da canlıda veri döndürdüğü için etkinleştirildi.
    _KATEGORILER: tuple = (
        ("/public/api/media/seriesEpisodesAll/",              "Yeni Bölümler"),
        ("/public/api/genres/latestseries/all/",             "Son Diziler"),
        ("/public/api/genres/latestmovies/all/",             "Son Filmler"),
        ("/public/api/genres/latestanimes/all/",             "Son Animeler"),
        ("/public/api/genres/mediaLibrary/show/80/serie/",   "Suç Dizileri"),
        ("/public/api/genres/mediaLibrary/show/80/movie/",   "Suç Filmleri"),
        ("/public/api/genres/mediaLibrary/show/9648/serie/", "Gizem Dizileri"),
        ("/public/api/genres/mediaLibrary/show/9648/movie/", "Gizem Filmleri"),
        ("/public/api/genres/mediaLibrary/show/10769/serie/", "Kore Diziler"),
        ("/public/api/genres/mediaLibrary/show/16/movie/",   "Animasyonlar"),
    )

    @property
    def _kategoriler(self) -> Dict[str, str]:
        """Ana sayfa kategori uçları (kök 'Ana Sayfa' girdisi bilinçli olarak yok)."""
        sayfalar: Dict[str, str] = {}
        for yol, ad in self._KATEGORILER:
            sayfalar[ad] = f"{self.main_url}{yol}{API_TOKEN}"
        return sayfalar

    # `main_page` property olamaz: PluginBase.url_update() `self.main_page` ataması yapar.
    # NOT: Kök adres (eskiden "Ana Sayfa") ile "Yeni Bölümler" aynı ucu döndürdüğü için
    # ayrı kategori olarak tutulmuyor; ilk kategori doğrudan "Yeni Bölümler".
    main_page: Dict[str, str] = {
        "Yeni Bölümler": f"{main_url}/public/api/media/seriesEpisodesAll/{API_TOKEN}",
        "Son Diziler": f"{main_url}/public/api/genres/latestseries/all/{API_TOKEN}",
        "Son Filmler": f"{main_url}/public/api/genres/latestmovies/all/{API_TOKEN}",
        "Son Animeler": f"{main_url}/public/api/genres/latestanimes/all/{API_TOKEN}",
        "Suç Dizileri": f"{main_url}/public/api/genres/mediaLibrary/show/80/serie/{API_TOKEN}",
        "Suç Filmleri": f"{main_url}/public/api/genres/mediaLibrary/show/80/movie/{API_TOKEN}",
        "Gizem Dizileri": f"{main_url}/public/api/genres/mediaLibrary/show/9648/serie/{API_TOKEN}",
        "Gizem Filmleri": f"{main_url}/public/api/genres/mediaLibrary/show/9648/movie/{API_TOKEN}",
        "Kore Diziler": f"{main_url}/public/api/genres/mediaLibrary/show/10769/serie/{API_TOKEN}",
        "Animasyonlar": f"{main_url}/public/api/genres/mediaLibrary/show/16/movie/{API_TOKEN}",
    }

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    # Film detay ucu sunucuda olmadığı için liste/aramada gelen veriyi saklıyoruz
    _icerik_onbellek: Dict[int, Dict[str, Any]] = {}

    @staticmethod
    def _kimlik_bul(url: str) -> Optional[int]:
        """`.../info/{id}/{token}` -> id (yol içindeki ilk sayısal segment)"""
        m = re.search(r"/(\d+)/", url or "")
        return int(m.group(1)) if m else None

    def generate_slug(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
        return slug or str(id(title))

    async def _api(self, url: str, page: int = 1) -> Optional[Dict[str, Any]]:
        """`/public/api` ucunu çağırır. Sayfalama `?page=N` ile yapılır."""
        ayirici = "&" if "?" in url else "?"
        try:
            istek = await self.httpx.get(
                url=f"{url}{ayirici}page={page}",
                headers=self.headers,
                follow_redirects=True,
                timeout=30.0,
            )
            if istek.status_code != 200:
                print(f"[!] {self.name}: HTTP {istek.status_code} ({url})")
                return None
            return istek.json()
        except Exception as e:
            print(f"[!] {self.name} API hatası ({url}): {e}")
            return None

    @staticmethod
    def _poster(veri: Dict[str, Any]) -> Optional[str]:
        """poster_path -> backdrop_path -> backdrop_path_tv"""
        return (veri.get("poster_path")
                or veri.get("backdrop_path")
                or veri.get("backdrop_path_tv")
                or veri.get("still_path")
                or veri.get("still_path_tv")
                or None)

    @staticmethod
    def _yil(veri: Dict[str, Any]) -> Optional[str]:
        """release_date / first_air_date -> YYYY"""
        tarih = veri.get("release_date") or veri.get("first_air_date")
        if not tarih:
            return None
        parcalar = str(tarih).split("-")
        return parcalar[0] if parcalar and parcalar[0].isdigit() else None

    def _tur(self, veri: Dict[str, Any], url: str = "") -> str:
        """Kotlin'un TvType belirlemesi -> 'movie' / 'series'."""
        tip = str(veri.get("type") or "").lower()
        if tip == "serie" or "serie" in url or "series" in url or "animes" in url:
            return "series"
        if tip == "anime" or "anime" in url:
            return "series"
        return "movie"

    def _icerik_karti(self, veri: Dict[str, Any], category: str = "") -> Optional[MainPageResult]:
        """Liste/aranma kaydı -> MainPageResult"""
        if not isinstance(veri, dict):
            return None

        baslik = self.clean_title(veri.get("name") or veri.get("title") or "")
        kimlik = veri.get("id")
        if not baslik or not kimlik:
            return None

        # Film detay ucu 404 olduğu için veriyi saklıyoruz (load_item yedeği)
        self._icerik_onbellek[int(kimlik)] = veri

        tur = self._tur(veri)
        if tur == "series":
            href = f"{self.main_url}/public/api/series/show/{kimlik}/{API_TOKEN}"
        else:
            href = f"{self.main_url}/public/api/media/movie/info/{kimlik}/{API_TOKEN}"

        puan = veri.get("vote_average")
        return MainPageResult(
            category=category,
            title=baslik,
            url=self.fix_url(href),
            poster=self.fix_url(self._poster(veri) or ""),
            release_date=self._yil(veri),
            rating=str(puan) if puan else None,
            plugin=self.name,
            media_type=tur,
        )

    def _bolum_karti(self, veri: Dict[str, Any], category: str = "") -> Optional[MainPageResult]:
        """'Yeni Bölümler' kaydı -> MainPageResult (Kotlin SineWixYeniBolum)"""
        if not isinstance(veri, dict):
            return None

        dizi_adi = self.clean_title(veri.get("name") or "")
        sezon = veri.get("season_number")
        bolum = veri.get("episode_number")
        if not dizi_adi or sezon is None or bolum is None:
            return None

        baslik = f"{dizi_adi} S{sezon:02d}E{bolum:02d}"
        kimlik = veri.get("id") or veri.get("serie_id")
        if not kimlik:
            return None

        # Kart daima DİZİ DETAY sayfasına gider; bölümün doğrudan medya adresi
        # `episode_url` alanında taşınır (aksi halde tıklama detay sayfasını atlar).
        link = veri.get("link")
        href = f"{self.main_url}/public/api/series/show/{kimlik}/{API_TOKEN}"

        return MainPageResult(
            category=category,
            title=baslik,
            url=self.fix_url(href),
            poster=self.fix_url(self._poster(veri) or ""),
            release_date=self._yil(veri),
            rating=str(veri.get("vote_average")) if veri.get("vote_average") else None,
            plugin=self.name,
            media_type="series",
            episode_url=self.fix_url(link) if link else None,
        )

    # ================================================================== #
    # Zorunlu metotlar
    # ================================================================== #

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> list[MainPageResult]:
        # Ana sayfa kök adresi: HTML 403 döndüğü için en güncel bölüm akışı kullanılır
        if not url or url.rstrip("/") == self.main_url.rstrip("/"):
            url = f"{self.main_url}/public/api/media/seriesEpisodesAll/{API_TOKEN}"
            category = category or "Yeni Bölümler"

        veri = await self._api(url, page)
        if not veri:
            return []

        # "Yeni Bölümler" farklı bir şema kullanıyor (name + link)
        if "seriesEpisodesAll" in url:
            return [k for k in (self._bolum_karti(v, category) for v in (veri.get("data") or [])) if k]

        return [k for k in (self._icerik_karti(v, category) for v in (veri.get("data") or [])) if k]

    async def search(self, query: str) -> list[SearchResult]:
        veri = await self._api(f"{self.main_url}/public/api/search/{query.strip()}/{API_TOKEN}")
        if not veri:
            return []

        results = []
        for veri_kaydi in (veri.get("search") or []):
            kart = self._icerik_karti(veri_kaydi)
            if not kart:
                continue
            results.append(SearchResult(
                title=kart.title,
                url=kart.url,
                poster=kart.poster,
                year=kart.release_date,
                rating=kart.rating,
                media_type=kart.media_type,
                plugin=self.name,
            ))
        return results

    async def load_item(self, url: str) -> Union[MovieInfo, SeriesInfo]:
        if "/series/show/" in url:
            return await self.load_series(url)

        # Doğrudan medya adresi (.mkv vb.): API değildir, oynatılabilir kayıt olarak döner.
        if DOGRUDAN_DOSYA.search(url or ""):
            return MovieInfo(
                url=url,
                title=self.clean_title((url or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]),
                slug=self.generate_slug((url or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]),
                runtime_minutes=0,
                plugin=self.name,
            )

        # NOT: `/media/movie/info/{id}` ucu sunucuda YOK (her film id'sinde 404) ve
        # HTML sayfaları Cloudflare tarafından 403 ile kapatıldığı için film detayı
        # yalnızca liste/arama sırasında gelen kayıttan üretilebilir.
        kimlik = self._kimlik_bul(url)
        veri = self._icerik_onbellek.get(kimlik) if kimlik else None

        if not veri and "/movie/info/" not in url:
            veri = await self._api(url)

        if not veri:
            return None

        title = veri.get("name") or veri.get("title")
        if not title:
            return None

        puan = veri.get("vote_average")
        return MovieInfo(
            url=url,
            title=self.clean_title(title),
            slug=self.generate_slug(title),
            poster_url=self.fix_url(self._poster(veri) or ""),
            description=(veri.get("overview") or None),
            release_date=self._yil(veri),
            rating=str(puan) if puan else None,
            genre=[g for g in (veri.get("genreslist") or veri.get("genres") or []) if g] if isinstance(
                veri.get("genreslist") or veri.get("genres"), list) else ([veri["genresname"]] if veri.get("genresname") else []),
            runtime_minutes=0,
            plugin=self.name,
        )

    async def load_series(self, url: str) -> Optional[SeriesInfo]:
        veri = await self._api(url)
        if not veri:
            return None

        title = veri.get("name") or veri.get("title")
        if not title:
            return None

        # Sezon -> bölüm -> video linki
        seasons_dict: Dict[str, List[Episode]] = {}
        for sezon in (veri.get("seasons") or []):
            if not isinstance(sezon, dict):
                continue
            sezon_no = sezon.get("season_number") or 1
            s_key = str(sezon_no)
            # Sitede bazı sezonlarda `videos` boş geliyor (ör. Hell on Wheels S2-S5).
            # O sezonlar tamamen düşerse kullanıcı "sadece 1. sezon var" görüyor,
            # bu yüzden sezon anahtarı link bulunmasa da her zaman oluşturulur.
            if s_key not in seasons_dict:
                seasons_dict[s_key] = []

            for bolum in (sezon.get("episodes") or []):
                if not isinstance(bolum, dict):
                    continue
                videolar = bolum.get("videos") or []
                link = videolar[0].get("link") if videolar else None

                ep_no = bolum.get("episode_number") or 1
                bolum_adi = bolum.get("name") or ""
                # Episode modeli "sezon/bölüm" içeren başlıkları siliyor; sitedeki
                # isimler de "1. Bölüm" biçiminde olduğu için sonuç boş kalıyor.
                temiz_baslik = self.clean_title(
                    re.sub(r"\d+\s*\.?\s*B[öo]l[üu]m.*$", "", bolum_adi, flags=re.IGNORECASE).strip()
                )
                if not temiz_baslik:
                    temiz_baslik = self.clean_title(title)

                episode_obj = Episode(
                    season=sezon_no,
                    episode=ep_no,
                    season_number=sezon_no,
                    episode_number=ep_no,
                    title=temiz_baslik,
                    # Link yoksa dizi sayfasına düş; böylece bölüm listede görünür.
                    url=self.fix_url(link) if link else url,
                    has_stream=bool(link),
                )
                seasons_dict[s_key].append(episode_obj)

        puan = veri.get("vote_average")
        turler = veri.get("genreslist") or veri.get("genres") or []
        if not isinstance(turler, list):
            turler = [turler] if turler else []

        oyuncular = []
        for oyuncu in (veri.get("casterslist") or []):
            if isinstance(oyuncu, dict):
                isim = oyuncu.get("name") or oyuncu.get("title")
                if isim:
                    oyuncular.append(isim)
            elif isinstance(oyuncu, str):
                oyuncular.append(oyuncu)

        return SeriesInfo(
            content_type="series",
            url=url,
            poster=self.fix_url(self._poster(veri) or ""),
            title=self.clean_title(title),
            description=(veri.get("overview") or None),
            tags=turler,
            rating=str(puan) if puan else None,
            fragman_url=(veri.get("trailer_url") or None),
            year=self._yil(veri),
            actors=oyuncular,
            plugin=self.name,
            seasons=seasons_dict if seasons_dict else None,
        )

    async def load_links(self, url: str) -> List[str]:
        """Doğrudan video dosyası mı, extractor mı gerektiğini ayırır.

        Bu sitedeki linkler `.mkv` indirme adresleri olduğu için extractor
        zincirine gerek yok; adres doğrudan döndürülür. Filmlerde ise kayıtta
        video alanı bulunmadığı için oynatılabilir kaynak yoktur.
        """
        if not url:
            return []

        if DOGRUDAN_DOSYA.search(url):
            return [url]

        # Film detay adresi. Sitenin film uçları (media/movie/info) 404 dönüyor ve
        # HTML sayfaları Cloudflare 403 ile kapalı; bu nedenle film linki API'de
        # hiçbir şekilde dönmediği için oynatılabilir kaynak yoktur.
        if "/movie/info/" in url:
            kimlik = self._kimlik_bul(url)
            kayit = self._icerik_onbellek.get(kimlik) if kimlik else None
            ad = ((kayit or {}).get("name") or (kayit or {}).get("title") or "Film")
            print(f"[!] {self.name}: '{ad}' için sunucuda video kaynağı yok "
                  f"(film uçları 404, HTML sayfaları 403).")
            return []

        # Dizi detay adresi: bölüm linkleri zaten episode adresi olarak gelir.
        if "/series/show/" in url:
            return []

        # Gömülü oynatıcı adresi -> extractor zincirine bırakılır
        return [url]

    def get_extraction_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Extractor için ekstra veri sağlar (bu eklentide gerekmiyor)."""
        return None


if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = Sinewix()
        test = await plugin.get_main_page(1)
        print(test[0] if test else "Sonuç yok")
        # await plugin.search("aslan")
        # print((await plugin.load_item("https://ydfvfdizipanel.ru/public/api/series/show/1794/9iQNC5HQwPlaFuJDkhncJ5XTJ8feGXOJatAA")).model_dump_json(indent=4))
        await plugin.close()

    asyncio.run(main())