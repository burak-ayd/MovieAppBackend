# Oluşturan: Burak Aydoğan
"""
Gömülü oynatıcı (embed) adresi çıkarma yardımcıları.

## Sorun

Oynatıcı siteleri iframe'i tembel yükleme (lazy load) ile gömer:

    <iframe src="about:blank" data-src="https://hdplayersystem.com/embed/xxx"></iframe>

Ziyaretçi JS çalıştırınca `data-src` → `src` olur. Ham HTML'i okuyan bir
scraper için `src` **her zaman** `about:blank` yer tutucusudur.

`about:blank`, `fix_url()` tarafından da bozulmadan geçer (`urljoin`
şemayı tanır), API 200 döner, `{links: ["about:blank"]}` üretilir ve kullanıcı
oynatıcıyı açamaz — **hiçbir hata loglanmaz**.

Bu, `Plugins/DiziMom.py` üzerinde canlı olarak doğrulandı: site, eski UA'ya
basit varyantı, yeni tarayıcı UA'sına ise lazy-load varyantını veriyordu.

## Çözüm

Tek bir doğru sıra, tek bir temizleme kuralı:

    1. Tembel öncelikli özellikler: data-src → data-original → data-lazy-src
       → data-echo → data-url → ... → src → srcset
    2. Her aday temizlenir: yer tutucular, javascript:/data: şemaları,
       boş değerler elenir
    3. Hiçbiri kalmazsa None döner (sessizce `about:blank` DÖNMEZ)

Kullanım — üç tarz, hepsi geçerli:

    from Core.Helpers.EmbedHelper import EmbedHelper

    # 1) CSS seçici (parsel / selectolax / BeautifulSoup)
    gomululer = EmbedHelper.gomulu_adresler(secici, "div.video p iframe")

    # 2) Tek element (parsel Selector, bs4 Tag, selectolax Node, dict)
    adres = EmbedHelper.gomulu_adres(iframe)

    # 3) Zaten ham aday listesi olan kod (mevcut eklentilerin çoğu)
    adres = EmbedHelper.en_iyi(iframe.get("src"), iframe.get("data-src"))

Eklenti yazarları için kısayol `PluginBase`'te tanımlıdır (fix_url uygulanmış):

    embed_urls = self.gomulu_adresler(secici, "div.video p iframe")
    ana        = self.gomulu_adres(secici, "div.video p iframe")
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional


class EmbedHelper:
    """Lazy-load destekli gömülü oynatıcı adresi çıkarır."""

    # ── 1) Yer tutucu değerler ──────────────────────────────────────────────
    # Bunlar geçerli bir adres DEĞİLDİR; JS çalışınca değişir.
    YER_TUTUCU = frozenset({
        "",
        "#",
        "about:blank",
        "about:srcdoc",
        "null",
        "undefined",
        "none",
        "true",
        "false",
        "javascript:void(0)",
        "javascript:void(0);",
        "javascript:;",
        "javascript:",
        "data:text/html",
        "data:text/html;charset=utf-8",
        "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",  # 1px gif
    })

    # ── 2) Özellik arama sırası ─────────────────────────────────────────────
    # Tembel yüklenen siteler gerçek adresi data-* içinde tutar; bu yüzden
    # src'ye EN SON bakılır. `src` önce bakılırsa about:blank'a takılır.
    OZELLIK_ONCELIGI = (
        "data-src",
        "data-original",
        "data-original-src",
        "data-lazy-src",
        "data-lazy",
        "data-echo",
        "data-url",
        "data-href",
        "data-vsrc",          # Plugins/SinemaCX.py (base64 kodlanmış oynatıcı)
        "data-iframe-src",
        "data-iframe",
        "data-embed",
        "data-embed-src",
        "data-embed-url",
        "data-player",
        "data-player-url",
        "data-media",
        "data-video",
        "data-file",
        "data-hls",
        "data-m3u8",
        "src",
    )

    # srcset benzeri çoklu aday taşıyan özellikler
    SRCSET_ONCELIGI = ("data-srcset", "data-lazy-srcset", "srcset")

    # ── 3) Oynatıcı olmayan varlık uzantıları ────────────────────────────────
    # Bir <img>/<script>/<link> kaynağı embed adresi olamaz.
    VARLIK_UZANTILARI = frozenset({
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif",
        ".css", ".js", ".mjs", ".map", ".json",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
    })

    # ── 4) Oynatıcı sayfalarında geçen yararlı yol işaretleri ───────────────
    # Uzantısı olmayan gömülü adresleri (ör. /e/abc123) varlık sanılmasın.
    GOMULU_ISARETLERI = ("/embed", "/e/", "/player", "/video", "/play", "/watch", "/stream")

    _SRCSET_DESCRIPTOR = re.compile(r"\s*(\d+(?:\.\d+)?)([wx])\s*$", re.IGNORECASE)

    # ══════════════════════════════════════════════════════════════════════
    #  Temizleme
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def temizle(adres: Optional[str]) -> Optional[str]:
        """
        Bir aday adresi kullanılabilir mi diye sınar.

        Reddedilenler: yer tutucular, javascript:/data: şemaları, boş değerler.
        Kabul edilenler: http(s), //host (protokol-relative), /göreli-yol.
        """
        if not adres or not isinstance(adres, str):
            return None

        adres = adres.strip()
        if not adres or adres.lower() in EmbedHelper.YER_TUTUCU:
            return None

        # javascript: ve data: gerçek bir kaynak değildir
        if adres.lower().startswith(("javascript:", "data:", "blob:", "mailto:", "tel:", "#")):
            return None

        return adres

    @staticmethod
    def varlik_mi(adres: str) -> bool:
        """Görsel/CSS/JS/font gibi oynatıcı olmayan bir kaynak mı?"""
        temiz = adres.split("?", 1)[0].split("#", 1)[0].lower()
        if any(temiz.endswith(uzanti) for uzanti in EmbedHelper.VARLIK_UZANTILARI):
            return True
        return False

    @staticmethod
    def gomulu_mu(adres: str) -> bool:
        """Oynatıcı sayfasına işaret ediyor mu? (uzantısız /embed/... gibi)"""
        temiz = adres.lower()
        return any(isaret in temiz for isaret in EmbedHelper.GOMULU_ISARETLERI)

    # ══════════════════════════════════════════════════════════════════════
    #  srcset
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def srcset_en_iyi(deger: str) -> Optional[str]:
        """
        `srcset` değerinden en yüksek çözünürlüklü adresi seçer.

        srcset  = "a-320.jpg 320w, a-1280.jpg 1280w, a-640.jpg 640w"
        sonuç   = "a-1280.jpg"

        Tanımlayıcı yoksa son aday seçilir (kaynaklarda en büyük en sonda
        yazılır).
        """
        if not deger:
            return None

        en_iyi = None
        en_iyi_puan = -1.0

        for parca in deger.split(","):
            parca = parca.strip()
            if not parca:
                continue

            bolunmus = parca.split(None, 1)
            aday = bolunmus[0].strip()
            if not aday:
                continue

            puan = 0.0
            if len(bolunmus) > 1:
                eslesme = EmbedHelper._SRCSET_DESCRIPTOR.search(bolunmus[1])
                if eslesme:
                    puan = float(eslesme.group(1))

            # Büyükten küçüğe ilk gördüğümüzü tut; eşitlikte sondakini seç
            if puan >= en_iyi_puan:
                en_iyi, en_iyi_puan = aday, puan

        return EmbedHelper.temizle(en_iyi)

    # ══════════════════════════════════════════════════════════════════════
    #  Çekirdek
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def nitelikler(oge: Any) -> dict:
        """
        Bir elementin özniteliklerini sözlük olarak döndürür.

        Desteklenen tipler: parsel (`attrib`), selectolax (`attributes`),
        BeautifulSoup (`attrs`), ham `dict`.
        """
        if oge is None:
            return {}

        if isinstance(oge, dict):
            return oge

        for ozellik in ("attrib", "attributes", "attrs"):
            deger = getattr(oge, ozellik, None)
            if isinstance(deger, dict):
                return deger

        # Metin düğümleri (::text ile gelenler) öznitelik taşımaz
        return {}

    @staticmethod
    def en_iyi(*adaylar: Optional[str]) -> Optional[str]:
        """
        Verilen aday adresleri arasından ilk KULLANILIR olanı döndürür.

            en_iyi(iframe.get("src"), iframe.get("data-src"))

        `src="about:blank"` olduğu için `data-src`ye düşer. Hiçbiri
        kullanılamazsa None döner.
        """
        for aday in adaylar:
            temiz = EmbedHelper.temizle(aday)
            if temiz:
                return temiz
        return None

    @staticmethod
    def gomulu_adres(oge: Any, *, varliklari_atla: bool = True) -> Optional[str]:
        """
        TEK bir elementten gerçek gömülü adresi çıkarır.

        `oge`: parsel Selector, bs4 Tag, selectolax Node veya dict olabilir.
        """
        nitelikler = EmbedHelper.nitelikler(oge)
        if not nitelikler:
            return None

        # 1) Tembel öncelikli özellikler + src
        for ozellik in EmbedHelper.OZELLIK_ONCELIGI:
            aday = EmbedHelper.temizle(nitelikler.get(ozellik))
            if not aday:
                continue
            if varliklari_atla and EmbedHelper.varlik_mi(aday):
                continue
            return aday

        # 2) srcset
        for ozellik in EmbedHelper.SRCSET_ONCELIGI:
            aday = EmbedHelper.srcset_en_iyi(nitelikler.get(ozellik, ""))
            if not aday:
                continue
            if varliklari_atla and EmbedHelper.varlik_mi(aday):
                continue
            return aday

        return None

    @staticmethod
    def gomulu_adresler(
        secici: Any,
        css: str,
        *,
        varliklari_atla: bool = True,
        benzersiz: bool = True,
    ) -> list[str]:
        """
        CSS seçicisiyle eşleşen TÜM elementlerin gömülü adreslerini döndürür.

        `secici` şunlardan biri olabilir:
          • parsel.Selector          (`.css()` → SelectorList)
          • selectolax HTMLParser   (`.css()` → Node listesi)
          • BeautifulSoup           (`.select()` → Tag listesi)
          • doğrudan element listesi

        Sıra korunur, tekrarlar atılır.
        """
        ogeler = EmbedHelper._eslestir(secici, css)

        adresler: list[str] = []
        for oge in ogeler:
            adres = EmbedHelper.gomulu_adres(oge, varliklari_atla=varliklari_atla)
            if not adres:
                continue
            if benzersiz and adres in adresler:
                continue
            adresler.append(adres)

        return adresler

    @staticmethod
    def ilk_gomulu_adres(secici: Any, css: str, *, varliklari_atla: bool = True) -> Optional[str]:
        """Eşleşen ilk kullanılabilir gömülü adresi döndürür (yoksa None)."""
        adresler = EmbedHelper.gomulu_adresler(secici, css, varliklari_atla=varliklari_atla)
        return adresler[0] if adresler else None

    @staticmethod
    def temizle_liste(adresler: Iterable[Optional[str]], *, varliklari_atla: bool = True) -> list[str]:
        """
        Ham adres listesini temizler: yer tutucuları, şema adreslerini,
        varlıkları siler; tekrarları atar.
        """
        sonuc: list[str] = []
        for aday in adresler:
            temiz = EmbedHelper.temizle(aday)
            if not temiz:
                continue
            if varliklari_atla and EmbedHelper.varlik_mi(temiz):
                continue
            if temiz not in sonuc:
                sonuc.append(temiz)
        return sonuc

    # ══════════════════════════════════════════════════════════════════════
    #  İç araçlar
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _eslestir(secici: Any, css: str) -> list:
        """Farklı kütüphaneleri tek arayüze indirger."""
        if secici is None:
            return []

        # Zaten liste/tuple ise doğrudan kullan
        if isinstance(secici, (list, tuple)):
            return list(secici)

        # parsel: .css() -> SelectorList
        css_metodu = getattr(secici, "css", None)
        if callable(css_metodu):
            try:
                return list(css_metodu(css))
            except Exception:
                return []

        # BeautifulSoup: .select() -> Tag listesi
        select_metodu = getattr(secici, "select", None)
        if callable(select_metodu):
            try:
                return list(select_metodu(css))
            except Exception:
                return []

        return []
