# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
"""Tek dosyadan tüm eklentileri test etme / oynatma aracı.

    python tests/EklentiTestAraci.py                    # eklenti listesinden seç, menüyle test et
    python tests/EklentiTestAraci.py --eklenti Dizilla  # eklentiyi doğrudan seç
    python tests/EklentiTestAraci.py --eklenti Dizibox --arama "silo"
    python tests/EklentiTestAraci.py --url "<bölüm linki>"          # eklenti URL'den tespit edilir
    python tests/EklentiTestAraci.py --url "<embed linki>" --coz    # sadece extractor çözümü
    python tests/EklentiTestAraci.py --eklenti HDFilmCehennemi --kategori "Aksiyon" --sayfa 2
    python tests/EklentiTestAraci.py --eklenti Dizilla --url "<link>" --otomatik --saniye 20

Akış:
    eklenti seçimi -> ana sayfa / kategori / arama -> içerik detayı -> (dizi) sezon + bölüm
    -> load_links -> (str ise) extractor -> ExtractResult -> mpv
"""

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Proje kökünü sys.path'e ekle (tests/ klasöründen ya da repo kökünden çalıştırılabilsin)
_KOK = Path(__file__).resolve().parent.parent
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from InquirerPy import inquirer

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Extractor.ExtractorModels import ExtractResult
from Core.Helpers import debug_log, konsol
from Core.Media.MediaManager import MediaManager
from Core.Plugin.PluginManager import PluginManager
from Core.Plugin.PluginModels import MovieInfo, SeriesInfo


# ===================================================================== #
# Ortak yardımcılar
# ===================================================================== #

async def select_from_fuzzy(message, choices):
    if not choices:
        return None
    return await inquirer.fuzzy(
        message    = message,
        choices    = choices,
        validate   = lambda result: result in [c if isinstance(c, str) else c["value"] for c in choices],
        filter     = lambda result: result,
        max_height = "75%",
    ).execute_async()


def play_media_sinirli(medya_yonetici: MediaManager, extract_data: ExtractResult, saniye: int) -> None:
    """MediaHandler ile aynı mpv komutunu kurar ama `--length` ile sınırlar.

    Test/CI'da oynatıcıyı sonsuza kadar açık bırakmamak için kullanılır.
    Not: mpv parametreli seçeneklerde "=" biçimini şart koşar ("--length 15" hata verir).
    """
    handler = medya_yonetici.media_handler

    header_fields: List[str] = []
    for key, value in handler.headers.items():
        if isinstance(value, dict):
            header_fields.append(f"{key}: " + "; ".join(f"{k}={v}" for k, v in value.items()))
        else:
            val_str = str(value).replace(",", ";") if key.lower() == "cookie" else str(value)
            header_fields.append(f"{key}: {val_str}")

    mpv_command = ["mpv", f"--length={saniye}"]
    if handler.title:
        mpv_command.append(f"--force-media-title={handler.title}")
    if header_fields:
        mpv_command.append(f"--http-header-fields={','.join(header_fields)}")
    if extract_data.subtitles:
        mpv_command.append("--slang=tr,tur,Turkish,en,eng,English")
        for altyazi in extract_data.subtitles:
            mpv_command.append(f"--sub-file={altyazi.url}")
    mpv_command.append(extract_data.url)

    konsol.log(f"[yellow][»] MPV (sınırlı, {saniye} sn): {extract_data.url[:90]}[/yellow]")
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="ignore") as err_file:
        with open(os.devnull, "w") as devnull:
            try:
                subprocess.run(mpv_command, stdout=devnull, stderr=err_file, check=True)
            except subprocess.CalledProcessError as hata:
                err_file.seek(0)
                konsol.print(f"[red]mpv oynatma hatası: {hata}[/red]")
                konsol.print(err_file.read()[-1500:])
            except FileNotFoundError:
                konsol.print("[red]mpv bulunamadı! PATH'te mpv olmalı.[/red]")


# ===================================================================== #
# Harness
# ===================================================================== #

class EklentiTestAraci:
    """Seçilen eklenti için arama -> detay -> bölüm -> extractor -> mpv akışını yürütür.

    Eklenti adı verilmezse menüden sorulur; tek giriş noktası bütün eklentileri test eder.
    """

    def __init__(self, eklenti_adi: str = "", aciklama: str = ""):
        self.eklenti_adi = eklenti_adi
        self.aciklama = aciklama
        self.medya_yonetici = MediaManager()
        self.cikaricilar_yonetici = ExtractorManager()
        self.eklentiler_yonetici = PluginManager()
        self.eklenti = None
        self.bolum_baslik = ""
        self.otomatik = False
        self.oynat = False
        self.saniye: Optional[int] = None

        if eklenti_adi:
            self._eklenti_yukle(eklenti_adi)

    # ------------------------------------------------------------------ #
    # Eklenti seçimi
    # ------------------------------------------------------------------ #

    def _eklenti_listesi(self) -> List[str]:
        return self.eklentiler_yonetici.get_plugin_names()

    def _eklenti_yukle(self, ad: str, sessiz: bool = False) -> bool:
        """Adla (ya da domainle) eklentiyi seçer. `sessiz=True` ise (URL tespiti) hata basmaz."""
        eklenti = self.eklentiler_yonetici.select_plugin(ad)
        if eklenti is None:
            eklenti = self.eklentiler_yonetici.find_plugin_by_url(ad)

        if eklenti is None:
            if not sessiz:
                konsol.print(f"[bold red]'{ad}' eklentisi yüklenemedi![/bold red]")
            return False

        self.eklenti = eklenti
        self.eklenti_adi = eklenti.name
        self.bolum_baslik = ""
        return True

    async def _eklenti_sec(self) -> bool:
        """Menüden eklenti seçimi."""
        isimler = self._eklenti_listesi()
        if not isimler:
            konsol.print("[bold red]Yüklenmiş eklenti bulunamadı![/bold red]")
            return False

        secim = await select_from_fuzzy(
            message = "Hangi eklentiyi test etmek istiyorsunuz?",
            choices = [{"name": self._eklenti_etiket(ad), "value": ad} for ad in isimler],
        )
        if secim is None:
            return False

        if not self._eklenti_yukle(secim):
            return False

        konsol.print(f"[green]Seçilen eklenti:[/green] {self.eklenti.name} ({self.eklenti.main_url})")
        return True

    def _eklenti_etiket(self, ad: str) -> str:
        """Seçim listesinde okunabilir etiket: `Dizilla — dizi izleme (dizilla.now)`."""
        eklenti = self.eklentiler_yonetici.select_plugin(ad)
        if not eklenti:
            return ad
        parcalar = [ad]
        if getattr(eklenti, "description", None):
            parcalar.append(eklenti.description)
        if getattr(eklenti, "main_url", None):
            parcalar.append(eklenti.main_url.replace("https://", ""))
        return " — ".join(parcalar)

    def _eklenti_listesini_yaz(self) -> None:
        """Terminalsiz modda eklenti seçilmediyse kullanılabilir listeyi gösterir."""
        konsol.print("[bold red]Eklenti seçilmedi. --eklenti <ad> kullan ya da şunlardan birini seç:[/bold red]")
        for ad in self._eklenti_listesi():
            konsol.print(f"   [cyan]{ad}[/cyan] — {self._eklenti_etiket(ad)}")

    # ------------------------------------------------------------------ #
    # Yaşam döngüsü
    # ------------------------------------------------------------------ #

    async def calistir(self) -> None:
        """Tek event loop içinde çalıştırıp kaynakları kapatır."""
        try:
            await self._ana_dongu()
        finally:
            with suppress(Exception):
                await self.eklentiler_yonetici.close_plugins()

    def _argumanlari_cozumle(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description="Eklenti test / oynatma aracı",
            epilog="Örnek: python tests/EklentiTestAraci.py --eklenti Dizilla --arama \"breaking bad\"",
        )
        parser.add_argument("--eklenti", default="", help="Test edilecek eklenti (verilmezse menüden sorulur)")
        parser.add_argument("--arama", help="Arama sorgusu")
        parser.add_argument("--kategori", help="Ana sayfa kategorisi")
        parser.add_argument("--sayfa", type=int, default=1, help="Kategori sayfası")
        parser.add_argument("--url", help="Doğrudan dizi / bölüm / embed linki (eklenti URL'den tespit edilir)")
        parser.add_argument("--coz", action="store_true",
                            help="Sadece extractor'ı çalıştır, mpv açma (varsayılan: oynatır)")
        parser.add_argument("--oynat", action="store_true",
                            help="Extractor sonrası mpv'de oynat (varsayılan davranış)")
        parser.add_argument("--saniye", type=int, help="Oynatma süresi (saniye)")
        parser.add_argument("--otomatik", action="store_true",
                            help="Terminalsiz kullanım: seçim sorulmaz, ilk çözülebilir kaynak kullanılır")
        parser.add_argument("--url-guncelle", action="store_true", help="MainUrlGuncelleyici'yi çalıştır")
        return parser.parse_args()

    async def _ana_dongu(self) -> None:
        args = self._argumanlari_cozumle()

        if args.url_guncelle:
            from Core.Helpers.Kontrol import MainUrlGuncelleyici
            MainUrlGuncelleyici().guncelle()

        self.otomatik = args.otomatik
        self.saniye = args.saniye
        # Varsayılan: oynat. Oynatma yalnızca --coz ile kapatılır (menüden "İzle"
        # seçildiğinde de mpv açılmalı).
        self.oynat = not args.coz

        # Eklenti çözümü: --eklenti > URL'den tespit > menüden sor
        if args.eklenti:
            self._eklenti_yukle(args.eklenti)
        elif args.url and not self.eklenti:
            self._eklenti_yukle(args.url, sessiz=True)   # domain eşleşmesi

        # Eklenti zorunlu: extractor'a gönderilen Referer çözümün şartı.
        # Örn. pichive kendi origin'ini (four.pichive.online) reddediyor, yalnızca
        # dizilla.now refererini kabul ediyor; bu yüzden plugin olmadan link çözülemez.
        if not self.eklenti:
            if self.otomatik:                      # menü açılamaz
                self._eklenti_listesini_yaz()
                return
            if not await self._eklenti_sec():
                return

        # 1) Doğrudan link
        if args.url:
            if "/iframe.php" in args.url or "/embed" in args.url or "/q/" in args.url:
                await self._baglanti_ile_oynat(args.url, oynat=self.oynat)
            else:
                await self._detay_goster(args.url)
            return

        # 2) Arama
        if args.arama:
            await self._arama_yap(args.arama)
            return

        # 3) Kategori / ana sayfa
        if args.kategori is not None:
            await self._kategori_yukle(args.kategori, args.sayfa)
            return

        # 4) Etkileşimli menü
        while True:
            secim = await select_from_fuzzy(
                message = f"{self.eklenti.name} test aracı - ne yapmak istersiniz?",
                choices = [
                    "Ana Sayfa / Kategori",
                    "Arama",
                    "Ham Embed Linki (Extractor Testi)",
                    "Eklenti Değiştir",
                    "Çıkış",
                ],
            )
            match secim:
                case "Ana Sayfa / Kategori":
                    await self._kategori_secimi()
                case "Arama":
                    sorgu = input("Arama: ").strip()
                    if sorgu:
                        await self._arama_yap(sorgu)
                case "Ham Embed Linki (Extractor Testi)":
                    await self._ham_link_istene()
                case "Eklenti Değiştir":
                    await self._eklenti_sec()
                case _:
                    break

    async def _ham_link_istene(self) -> None:
        """Extractor'ı tek başına denemek için ham embed linki ister."""
        link = input("Embed linki (örn. https://four.pichive.online/iframe.php?v=...): ").strip()
        if not link:
            return

        # Link başka bir eklentiye aitse kullanıcıyı bilgilendir: referer seçili
        # eklentiden geliyor (pichive sadece dizilla.now refererini kabul eder).
        tespit = self.eklentiler_yonetici.find_plugin_by_url(link)
        if tespit and self.eklenti and tespit is not self.eklenti:
            konsol.print(f"[yellow]Link {tespit.name} eklentisine ait; "
                         f"şu anki {self.eklenti.name} refereri kullanılacak.[/yellow]")

        await self._baglanti_ile_oynat(link, oynat=self.oynat)

    # ------------------------------------------------------------------ #
    # Adım adım akış
    # ------------------------------------------------------------------ #

    async def _arama_yap(self, sorgu: str) -> None:
        sonuclar = await self.eklenti.search(sorgu)
        if not sonuclar:
            konsol.print(f"[bold red]'{sorgu}' için sonuç bulunamadı![/bold red]")
            return

        secilen = await self._sonuc_secimi("Arama sonuçlarından birini seçin:", sonuclar)
        if secilen:
            await self._detay_goster(secilen)

    async def _sonuc_secimi(self, mesaj: str, sonuclar: list) -> Optional[str]:
        if not sonuclar:
            return None
        if self.otomatik:                     # terminalsiz kullanım: ilk sonuç
            return sonuclar[0].url
        return await select_from_fuzzy(
            message = mesaj,
            choices = [{"name": self._baslik(sonuc), "value": sonuc.url} for sonuc in sonuclar],
        )

    @staticmethod
    def _baslik(sonuc) -> str:
        yil = getattr(sonuc, "year", None)
        return f"{sonuc.title} ({yil})" if yil else sonuc.title

    async def _kategori_secimi(self) -> None:
        kategoriler = list(self.eklenti.main_page.keys())
        secilen = await select_from_fuzzy(
            message = "Hangi kategoriyi denemek istersiniz?",
            choices = [{"name": ad, "value": ad} for ad in kategoriler]
                    + [{"name": "Ana sayfa (kategorisiz)", "value": ""}],
        )
        if secilen is None:
            return
        await self._kategori_yukle("" if secilen == "" else secilen, 1)

    async def _kategori_yukle(self, kategori: str, sayfa: int = 1) -> None:
        url = self.eklenti.main_page.get(kategori, "") if kategori else ""
        try:
            ham = await self.eklenti.get_main_page(page=sayfa, url=url, category=kategori or "")
        except Exception as hata:
            konsol.print(f"[bold red]Ana sayfa hatası: {hata}[/bold red]")
            return

        # Bazı eklentiler dict döner: {"kategori": [MainPageResult, ...]}
        sonuclar: List[Any] = []
        if isinstance(ham, dict):
            for bolum, liste in ham.items():
                if isinstance(liste, list):
                    for item in liste:
                        konsol.log(f"[dim]{bolum} » {getattr(item, 'title', '?')}[/dim]")
                    sonuclar.extend(liste)
        elif isinstance(ham, list):
            sonuclar = ham

        if not sonuclar:
            konsol.print("[bold yellow]Sonuç bulunamadı![/bold yellow]")
            return

        secilen = await self._sonuc_secimi("İçeriklerden birini seçin:", sonuclar)
        if secilen:
            await self._detay_goster(secilen)

    async def _detay_goster(self, url: str) -> None:
        medya = await self._medya_yukle(url)
        if not medya:
            return

        self.medya_yonetici.set_title(f"{self.eklenti.name} | {medya.title}")
        konsol.print(f"{self.eklenti.name} | {medya.title}", medya)

        if isinstance(medya, SeriesInfo):
            await self._sezon_bolum_secimi(medya, hedef_url=url)
        else:
            self.bolum_baslik = ""
            baglantilar = await self._linkleri_al(medya.url)
            await self._link_secimi(baglantilar)

    async def _medya_yukle(self, url: str, deneme: int = 3):
        for _ in range(deneme):
            with suppress(Exception):
                return await self.eklenti.load_item(url)
        konsol.print(f"[bold red]Medya bilgileri yüklenemedi: {url}[/bold red]")
        return None

    async def _sezon_bolum_secimi(self, medya: SeriesInfo, hedef_url: Optional[str] = None) -> None:
        """Dizi -> sezon -> bölüm. (Dizilla'da bölüm linkinden dizi çözülür.)"""
        self.bolum_baslik = ""
        sezonlar = medya.seasons or {}

        if not sezonlar:
            konsol.print("[bold yellow]Sezon bilgisi yok; doğrudan bağlantılara bakılıyor.[/bold yellow]")
            await self._link_secimi(await self._linkleri_al(medya.url))
            return

        if self.otomatik:
            secilen_bolum = None
            if hedef_url:      # verilen URL bir bölüm sayfasıysa onu seç
                for bolumler in sezonlar.values():
                    secilen_bolum = next(
                        (b for b in bolumler if b.url and b.url.rstrip("/") == hedef_url.rstrip("/")), None
                    )
                    if secilen_bolum:
                        break
            if secilen_bolum is None:
                ilk_sezon = sorted(sezonlar.keys())[0]
                secilen_bolum = sezonlar[ilk_sezon][0]
        else:
            secilen_sezon = await select_from_fuzzy(
                message = "Hangi sezon?",
                choices = [{"name": f"{sezon}. Sezon ({len(bolumler)} bölüm)", "value": sezon}
                           for sezon, bolumler in sorted(sezonlar.items())],
            )
            if secilen_sezon is None:
                return

            secilen_bolum = await select_from_fuzzy(
                message = f"{secilen_sezon}. Sezon - bölüm seçin:",
                choices = [{"name": f"{b.episode}. Bölüm" + (f" - {b.title}" if b.title else ""), "value": b}
                           for b in sezonlar[secilen_sezon]],
            )
            if secilen_bolum is None:
                return

        self.bolum_baslik = f"{secilen_bolum.season or '?'}x{secilen_bolum.episode}"
        konsol.print(f"[green]Seçilen bölüm:[/green] {self.bolum_baslik} » {secilen_bolum.url}")
        await self._link_secimi(await self._linkleri_al(secilen_bolum.url))

    async def _linkleri_al(self, url: str) -> List[Union[str, ExtractResult]]:
        try:
            ham = await self.eklenti.load_links(url)
        except Exception as hata:
            konsol.print(f"[bold red]Bağlantı alınamadı: {hata}[/bold red]")
            return []
        if not ham:
            return []
        # Bazı eklentiler ExtractResult listesi döner (DiziBox), bazıları ham link (str)
        return [i for i in ham if isinstance(i, (str, ExtractResult))]

    async def _link_secimi(self, baglantilar: List[Union[str, ExtractResult]]) -> None:
        if not baglantilar:
            konsol.print("[bold red]Hiçbir bağlantı bulunamadı![/bold red]")
            return

        if self.otomatik:
            for aday in baglantilar:
                if isinstance(aday, ExtractResult):
                    return await self._oynat_extract(aday, oynat=self.oynat)
                sonuc = await self._baglanti_ile_oynat(aday, oynat=self.oynat)
                if sonuc:
                    return sonuc
            konsol.print("[bold red]Hiçbir bağlantı çözülemedi (token süreleri dolmuş olabilir).[/bold red]")
            return

        # NOT: ExtractResult pydantic modelidir, hashlenemez; bu yüzden sözlük (dict)
        # anahtarı olarak kullanılamaz. Liste halinde {name, value} çiftleri kurulur.
        secenekler: List[Dict[str, Any]] = []
        for aday in baglantilar:
            if isinstance(aday, ExtractResult):
                etiket = f"{aday.name} (plugin) » {aday.url[:70]}"
            else:
                cikarici = self.cikaricilar_yonetici.find_extractor(aday)
                etiket = f"{cikarici.name} » {aday[:70]}" if cikarici else f"{aday} (çıkarıcı yok)"
            secenekler.append({"name": etiket, "value": aday})

        secim = await select_from_fuzzy(message = "Ne yapmak istersiniz?", choices = ["İzle", "Geri"])
        if secim != "İzle":
            return

        secilen = await select_from_fuzzy(message = "İzlemek için bir bağlantı seçin:", choices=secenekler)
        if secilen is None:
            return
        if isinstance(secilen, ExtractResult):
            await self._oynat_extract(secilen, oynat=self.oynat)
        else:
            await self._baglanti_ile_oynat(secilen, oynat=self.oynat)

    async def _baglanti_ile_oynat(self, link: str, oynat: bool = True) -> Optional[ExtractResult]:
        """Ham linki uygun çıkarıcıyla çözer (bazı çıkarıcılar liste döner)."""
        cikarici: Optional[ExtractorBase] = self.cikaricilar_yonetici.find_extractor(link)
        if not cikarici:
            konsol.print(f"[bold red]Uygun Extractor bulunamadı:[/bold red] {link}")
            return None

        referer = f"{self.eklenti.main_url}/" if self.eklenti else ""
        try:
            veri = await cikarici.extract(link, referer=referer)
        except Exception as hata:
            konsol.print(f"[bold red]{cikarici.name} » hata: {hata}[/bold red]")
            return None

        if not veri:
            konsol.print(f"[bold red]{cikarici.name} » bağlantı çözülemedi (token süresi dolmuş olabilir).[/bold red]")
            return None

        debug_log(veri)
        secilen = await self._kaynak_secimi(veri)
        if not secilen:
            return None

        return await self._oynat_extract(secilen, oynat=oynat)

    async def _kaynak_secimi(self, veri) -> Optional[ExtractResult]:
        if isinstance(veri, list):
            if self.otomatik:
                return veri[0]
            secim = await select_from_fuzzy(
                message = "Birden fazla kaynak bulundu, seçin:",
                choices = [{"name": d.name, "value": d} for d in veri],
            )
            return secim
        return veri

    async def _oynat_extract(self, veri: ExtractResult, oynat: bool = True) -> Optional[ExtractResult]:
        self._medya_ayarla(veri)

        if not oynat:
            konsol.print("[bold green]Extractor çözümü başarılı (oynatma kapalı).[/bold green]")
            konsol.print({"name": veri.name, "url": veri.url, "referer": veri.referer})
            for altyazi in veri.subtitles:
                konsol.print(f"   altyazı » {altyazi.name}: {altyazi.url}")
            return veri

        debug_log("oynatılıyor...", veri)
        if self.saniye:
            play_media_sinirli(self.medya_yonetici, veri, self.saniye)
        else:
            self.medya_yonetici.play_media(veri)
        konsol.print("[bold green]İçerik bitti![/bold green]")
        return veri

    def _medya_ayarla(self, veri: ExtractResult) -> None:
        self.medya_yonetici.set_headers(veri.headers or {})
        if veri.referer and not (veri.headers or {}).get("Referer"):
            self.medya_yonetici.set_headers({"Referer": veri.referer})

        eklenti_adi = self.eklenti.name if self.eklenti else "Extractor"
        baslik = self.medya_yonetici.get_title() or eklenti_adi
        if eklenti_adi not in baslik:
            baslik = f"{eklenti_adi} | {baslik}"
        if self.bolum_baslik:
            baslik = f"{baslik} | {self.bolum_baslik}"
        if veri.name not in baslik:
            baslik = f"{baslik} | {veri.name}"
        self.medya_yonetici.set_title(baslik)


def calistir(eklenti_adi: str = "", aciklama: str = "") -> None:
    """Tek giriş noktası: eklenti verilmezse menüden sorulur."""
    asyncio.run(EklentiTestAraci(eklenti_adi, aciklama).calistir())


if __name__ == "__main__":
    calistir()
