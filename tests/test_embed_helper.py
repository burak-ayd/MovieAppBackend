# Oluşturan: Burak Aydoğan
"""
Gömülü oynatıcı adresi çıkarma testleri (EmbedHelper).

Çalıştırma:
    pytest tests/test_embed_helper.py -v

Neden var?
    Canlı doğrulama: Plugins/DiziMom.py oynatıcı sayfasındaki
    `src="about:blank"` + `data-src="<gerçek>"` kalıbını `.get()` ile okuyordu
    ve API 200 ile `{links: ["about:blank"]}` döndürüyordu — hata loglanmıyor,
    kullanıcı yalnızca oynatıcının açılmadığını görüyordu. Bu testler o
    sessiz bozukluğun her varyantını kilitler.

Kapsam: parsel, BeautifulSoup, selectolax ve ham dict girdileri.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Core.Helpers.EmbedHelper import EmbedHelper

from bs4 import BeautifulSoup
from parsel import Selector
from selectolax.parser import HTMLParser


GERCEK = "https://hdplayersystem.com/embed/a3gsCGldxsCmaWE"

# Canlı DiziMom sayfasından alınan gerçek yapı: lazy iframe + çalışan iframe
LAZY_HTML = f"""
<html><body>
  <div class="video">
    <p>
      <iframe src="about:blank" data-src="{GERCEK}" data-lazyloaded="1" loading="lazy"
              width="700" height="400" allowfullscreen=""></iframe>
    </p>
  </div>
</body></html>
"""


# ══════════════════════════════════════════════════════════════════════════════
#  1) En kritik senaryo: about:blank yer tutucusu
# ══════════════════════════════════════════════════════════════════════════════

class TestYerTutucu:
    """Eski davranışın sessizce bozuk döndüğü durumlar."""

    def test_about_blank_yerine_data_src_duser(self):
        """data-src önce bakılır → gerçek adres döner."""
        sel = Selector(LAZY_HTML)
        assert EmbedHelper.ilk_gomulu_adres(sel, "div.video p iframe") == GERCEK

    def test_eski_yontem_broken_donduruyordu(self):
        """
        REGRESYON ANKASI: eski kodun yaptığı gibi src okunursa
        'about:blank' gelir. Bu davranışın değiştiğini kanıtlar.
        """
        sel = Selector(LAZY_HTML)
        assert sel.css("div.video p iframe::attr(src)").get() == "about:blank"

    def test_hicbir_gecerli_adres_yoksa_none(self):
        """Yalnızca about:blank varsa None döner, 'about:blank' DEĞİL."""
        html = '<div class="video"><p><iframe src="about:blank"></iframe></p></div>'
        assert EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe") is None

    @pytest.mark.parametrize("yer_tutucu", [
        "about:blank", "about:srcdoc", "", "   ", "#", "null", "undefined",
        "none", "true", "false", "javascript:void(0)", "javascript:;",
        "data:text/html", "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
    ])
    def test_tum_yer_tutucular_elenir(self, yer_tutucu):
        assert EmbedHelper.temizle(yer_tutucu) is None

    @pytest.mark.parametrize("gecerli", [
        "https://ornek.com/e/1",
        "http://ornek.com/e/1",
        "//cdn.ornek.com/e/1",
        "/embed/abc",
    ])
    def test_gecerli_adresler_kalir(self, gecerli):
        assert EmbedHelper.temizle(gecerli) == gecerli

    def test_sema_adresleri_elenir(self):
        assert EmbedHelper.temizle("javascript:alert(1)") is None
        assert EmbedHelper.temizle("mailto:a@b.c") is None
        assert EmbedHelper.temizle("blob:https://x/y") is None


# ══════════════════════════════════════════════════════════════════════════════
#  2) Öznitelik öncelik sırası
# ══════════════════════════════════════════════════════════════════════════════

class TestOncelikSirasi:
    @pytest.mark.parametrize("ozellik", [
        "data-src", "data-original", "data-original-src", "data-lazy-src",
        "data-echo", "data-url", "data-href", "data-iframe-src", "data-embed",
        "data-player", "data-media", "data-video", "data-file",
    ])
    def test_tum_tembel_ozellikler_taninir(self, ozellik):
        """Kod tabanında dolaşan her tembel özellik adı desteklenmeli."""
        html = f'<div class="video"><p><iframe src="about:blank" {ozellik}="{GERCEK}"></iframe></p></div>'
        assert EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe") == GERCEK

    def test_sadece_src_varsa_src_doner(self):
        html = f'<div class="video"><p><iframe src="{GERCEK}"></iframe></p></div>'
        assert EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe") == GERCEK

    def test_data_src_yer_tutucuysa_sra_goer(self):
        """data-src de about:blank ise sıradaki adaya (src) geçilir."""
        html = (f'<div class="video"><p><iframe data-src="about:blank" '
                f'src="{GERCEK}"></iframe></p></div>')
        assert EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe") == GERCEK

    def test_en_iyi_sirali_adaylar(self):
        assert EmbedHelper.en_iyi("about:blank", GERCEK) == GERCEK
        assert EmbedHelper.en_iyi(None, "", GERCEK) == GERCEK
        assert EmbedHelper.en_iyi("about:blank", None, "javascript:void(0)") is None


# ══════════════════════════════════════════════════════════════════════════════
#  3) Kütüphane uyumu — parsel / BeautifulSoup / selectolax / dict
# ══════════════════════════════════════════════════════════════════════════════

class TestKutuphaneUyumu:
    def test_parsel(self):
        assert EmbedHelper.ilk_gomulu_adres(Selector(LAZY_HTML), "div.video p iframe") == GERCEK

    def test_beautifulsoup(self):
        soup = BeautifulSoup(LAZY_HTML, "html.parser")
        assert EmbedHelper.ilk_gomulu_adres(soup, "div.video p iframe") == GERCEK

    def test_selectolax(self):
        assert EmbedHelper.ilk_gomulu_adres(HTMLParser(LAZY_HTML), "div.video p iframe") == GERCEK

    def test_ham_sozluk(self):
        assert EmbedHelper.gomulu_adres({"src": "about:blank", "data-src": GERCEK}) == GERCEK

    def test_tekil_parsel_selector(self):
        oge = Selector(LAZY_HTML).css("div.video p iframe")[0]
        assert EmbedHelper.gomulu_adres(oge) == GERCEK

    def test_tekil_bs4_tag(self):
        oge = BeautifulSoup(LAZY_HTML, "html.parser").select_one("div.video p iframe")
        assert EmbedHelper.gomulu_adres(oge) == GERCEK

    def test_ogeler_listesi(self):
        ogeler = Selector(LAZY_HTML).css("div.video p iframe")
        assert EmbedHelper.gomulu_adresler(ogeler, "iframe") == [GERCEK]

    def test_bos_girdiler(self):
        assert EmbedHelper.gomulu_adresler(None, "iframe") == []
        assert EmbedHelper.gomulu_adresler(Selector(""), "iframe") == []
        assert EmbedHelper.gomulu_adres(None) is None


# ══════════════════════════════════════════════════════════════════════════════
#  4) srcset
# ══════════════════════════════════════════════════════════════════════════════

class TestSrcset:
    @pytest.mark.parametrize("srcset, beklenen", [
        ("a-320.jpg 320w, a-1280.jpg 1280w, a-640.jpg 640w", "a-1280.jpg"),
        ("a.m3u8 480w, a.m3u8 1080w", "a.m3u8"),               # eşitlikde son
        ("tek.m3u8", "tek.m3u8"),
        ("", None),
        ("   ", None),
    ])
    def test_en_yuksek_cozumurluk(self, srcset, beklenen):
        assert EmbedHelper.srcset_en_iyi(srcset) == beklenen

    def test_srcset_ozelligi_kullanilir(self):
        html = ('<div class="video"><p><iframe srcset="a.m3u8 480w, b.m3u8 1080w" '
                '></iframe></p></div>')
        assert EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe") == "b.m3u8"

    def test_data_srcset_tercih_edilir(self):
        html = ('<div class="video"><p><iframe srcset="eski.m3u8 100w" '
                f'data-srcset="yeni.m3u8 200w"></iframe></p></div>')
        assert EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe") == "yeni.m3u8"


# ══════════════════════════════════════════════════════════════════════════════
#  5) Varlık ayrımı (görsel/CSS/JS oynatıcı olamaz)
# ══════════════════════════════════════════════════════════════════════════════

class TestVarlikAyrimi:
    @pytest.mark.parametrize("varlik", [
        "https://cdn.ornek.com/kapak.jpg",
        "https://cdn.ornek.com/style.css?v=3",
        "https://cdn.ornek.com/app.js",
        "https://cdn.ornek.com/f.woff2",
    ])
    def test_varliklar_elenir(self, varlik):
        assert EmbedHelper.varlik_mi(varlik) is True

    @pytest.mark.parametrize("oynatici", [
        "https://x.com/embed/abc",
        "https://x.com/e/abc",
        "https://x.com/player/1",
        "https://cdn.ornek.com/master.m3u8",
    ])
    def test_oynaticilar_kalir(self, oynatici):
        assert EmbedHelper.varlik_mi(oynatici) is False

    def test_embed_modunda_gorsel_elenir(self):
        html = f'<div class="video"><p><iframe data-src="https://cdn.ornek.com/k.jpg"></iframe></p></div>'
        assert EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe") is None

    def test_gorsu_modunde_gorsel_serbest(self):
        """Poster gibi görsel arayan çağrılar varlık filtresini kapatabilir."""
        html = f'<div class="video"><p><iframe data-src="https://cdn.ornek.com/k.jpg"></iframe></p></div>'
        adres = EmbedHelper.ilk_gomulu_adres(Selector(html), "div.video p iframe", varliklari_atla=False)
        assert adres == "https://cdn.ornek.com/k.jpg"


# ══════════════════════════════════════════════════════════════════════════════
#  6) Çoklu adres, sıra ve tekilleştirme
# ══════════════════════════════════════════════════════════════════════════════

class TestCokluAdres:
    HTML = f"""
    <div class="sources">
      <a href="/kaynak-1">1</a>
      <a href="/kaynak-2">2</a>
    </div>
    <div class="video"><p><iframe src="about:blank" data-src="https://a.com/e/1"></iframe></p></div>
    <div class="video"><p><iframe src="https://b.com/e/2"></iframe></p></div>
    <div class="video"><p><iframe src="about:blank"></iframe></p></div>
    <div class="video"><p><iframe src="https://a.com/e/1"></iframe></p></div>
    """

    def test_sira_korunur_tekrar_atilir(self):
        assert EmbedHelper.gomulu_adresler(Selector(self.HTML), "div.video p iframe") == [
            "https://a.com/e/1",
            "https://b.com/e/2",
        ]

    def test_benzersiz_kapatilabilir(self):
        # 4 iframe var; bunlardan biri SAF about:blank olduğu için elenir,
        # geriye 3 geçerli adres kalır (biri a.com/e/1'in tekrarı).
        assert EmbedHelper.gomulu_adresler(Selector(self.HTML), "div.video p iframe", benzersiz=False) == [
            "https://a.com/e/1",
            "https://b.com/e/2",
            "https://a.com/e/1",
        ]

    def test_temizle_liste(self):
        ham = ["about:blank", None, "", "javascript:void(0)", "https://x.com/e/1",
               "https://x.com/e/1", "https://x.com/a.jpg"]
        assert EmbedHelper.temizle_liste(ham) == ["https://x.com/e/1"]


# ══════════════════════════════════════════════════════════════════════════════
#  7) PluginBase kısayolları (fix_url uygulanmış hâli)
# ══════════════════════════════════════════════════════════════════════════════

class TestPluginBaseKisayollari:
    @pytest.fixture
    def eklenti(self):
        from Plugins.Dizibox import DiziBox           # gerçek eklenti örneği
        p = DiziBox()
        yield p

    def test_gomulu_adres_mutlaklastirir(self, eklenti):
        """Göreli adres mutlaklaştırılır."""
        html = '<div class="video"><p><iframe data-src="/embed/kaynak"></iframe></p></div>'
        sonuc = eklenti.gomulu_adres(Selector(html), "div.video p iframe")
        assert sonuc.startswith("http")
        assert sonuc.endswith("/embed/kaynak")

    def test_gomulu_adresler_liste(self, eklenti):
        html = f'<div class="video"><p><iframe data-src="{GERCEK}"></iframe></p></div>'
        assert eklenti.gomulu_adresler(Selector(html), "div.video p iframe") == [GERCEK]

    def test_bulunamazsa_none(self, eklenti):
        assert eklenti.gomulu_adres(Selector("<p>merhaba</p>"), "div.video p iframe") is None

    def test_yer_tutucu_asla_donusmez(self, eklenti):
        """fix_url('about:blank') -> 'about:blank' olduğu için bu kritik."""
        html = '<div class="video"><p><iframe src="about:blank"></iframe></p></div>'
        assert eklenti.gomulu_adres(Selector(html), "div.video p iframe") is None
