"""
DiziBox bölüm kartı ayrıştırma testleri — çevrimdışı (gerçek HTML yapısıyla).

"/tum-bolumler/" sayfasındaki kartlarda `a[title]` ve `img[alt]` başlığa
"1.Sezon 2.Bölüm" ekliyor; temiz seri adı `b.series-name` içinde duruyor.
Bu kartlarda başlığın kirli gitmesi hem ekranda hem TMDB eşleştirmesinde
sorun yaratıyordu.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

parsel = pytest.importorskip("parsel")
from parsel import Selector  # noqa: E402

from Plugins.Dizibox import DiziBox  # noqa: E402

# Gerçek site HTML'inden birebir alınmış kart yapısı
KART = """
<article class="article-episode-card pull-left grid-five e_201195">
  <figure class="figure-link pull-left">
    <figcaption class="thumbnail-figcaption">
      <a href="https://www.dizibox.live/war-1-sezon-1-bolum-izle/"
         class="episode-card-title span-nine pull-left text-overflow link-unstyled"
         title="War 1.Sezon 1.Bölüm">
        <b class="series-name text-overflow">WAR</b>
        <span class="season text-muted">1.SEZON </span>
        <b class="episode primary-color">1.BÖLÜM</b>
      </a>
      <div class="poster-meta span-three pull-right">
        <div class="language text-right full-width pull-left">
          <img src="https://www.dizibox.live/altyazi.png" alt="Dil Seçeneği" class="language-flag">
        </div>
        <div class="publish-date pull-right">02 Eki</div>
      </div>
    </figcaption>
    <a href="https://www.dizibox.live/war-1-sezon-1-bolum-izle/" class="figure-link" title="">
      <img fetchpriority="high" loading="lazy"
           data-src="https://www.dizibox.live/wp-content/uploads/afisler/war-220x140.jpg"
           src="data:image/png;base64,AAAABBBB">
    </a>
  </figure>
</article>
"""

# Yıl parantezli seri adı (gerçek örnek: "DARK MATTER (2024)")
KART_YILLI = """
<article class="article-episode-card">
  <a href="https://www.dizibox.live/dark-matter-2024-2-sezon-6-bolum-izle/"
     class="episode-card-title" title="Dark Matter (2024) 2.Sezon 6.Bölüm">
    <b class="series-name">DARK MATTER (2024)</b>
    <span class="season">2.SEZON </span>
    <b class="episode">6.BÖLÜM</b>
  </a>
  <img class="afis" data-src="https://www.dizibox.live/wp-content/uploads/afisler/dark.jpg">
</article>
"""

# b.series-name YOK: yalnızca kirli başlık var (yedek yol)
KART_SERISIZ = """
<article class="article-episode-card">
  <a href="https://www.dizibox.live/zmora-1-sezon-1-bolum-izle/"
     class="episode-card-title" title="Zmora 1.Sezon 1.Bölüm">Zmorа</a>
</article>
"""


def _kart(html):
    return Selector(text=html).css("article.article-episode-card")[0]


def test_bolum_karti_temiz_seri_adi_dondurur():
    """Kirli `a[title]` yerine temiz `b.series-name` okunur."""
    seri, sezon, bolum = DiziBox._bolum_karti_basligi(_kart(KART))
    assert seri == "WAR"
    assert (sezon, bolum) == (1, 1)


def test_bolum_karti_bolum_numaralarini_ayiklar():
    _, sezon, bolum = DiziBox._bolum_karti_basligi(_kart(KART_YILLI))
    assert sezon == 2
    assert bolum == 6


def test_bolum_karti_yilli_seri_adini_korur():
    seri, _, _ = DiziBox._bolum_karti_basligi(_kart(KART_YILLI))
    assert seri == "DARK MATTER (2024)"


def test_serisiz_kartta_yedek_yol_temizler():
    """`b.series-name` yoksa kirli başlıktan bölüm ibaresi ayıklanır."""
    seri, sezon, bolum = DiziBox._bolum_karti_basligi(_kart(KART_SERISIZ))
    assert seri == "Zmora"
    assert (sezon, bolum) == (1, 1)


def test_bos_kartta_none_doner():
    seri, sezon, bolum = DiziBox._bolum_karti_basligi(Selector(text="<article></article>").css("article")[0])
    assert (seri, sezon, bolum) == (None, None, None)


def test_baslik_tmdb_icin_esleştirilebilir():
    """
    Uçtan uca beklenti: kart başlığı normalize edildiğinde saf dizi adı kalmalı.
    (TMDB eşleştirmesi bu değerle yapılır.)
    """
    from Core.Libs.TMDB import normalize_title

    seri, _, _ = DiziBox._bolum_karti_basligi(_kart(KART))
    assert normalize_title(seri) == "war"


def test_model_bolum_alanlarini_tasiyor():
    """MainPageResult bölüm bilgisini kaybetmemeli."""
    from Core.Plugin.PluginModels import MainPageResult

    oge = MainPageResult(
        title="WAR", url="https://dizibox.live/x", media_type="tv",
        season=1, episode=1,
    )
    assert oge.season == 1 and oge.episode == 1
    assert oge.media_type == "tv"