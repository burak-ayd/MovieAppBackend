import asyncio


from Core.Extractor.ExtractorModels import ExtractResult
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Media.MediaManager import MediaManager
from Core.Helpers import konsol, debug_log, is_debug
from Core.Plugin.PluginManager import PluginManager
from Core.Plugin.PluginBase import PluginBase
from Core.Extractor.ExtractorBase import ExtractorBase
from InquirerPy import inquirer
from Core.Plugin.PluginModels import SeriesInfo, MovieInfo
from contextlib import suppress
from Core.Helpers.Kontrol import MainUrlGuncelleyici


async def select_from_fuzzy(message, choices):
    if not choices:
        return None
    return await inquirer.fuzzy(
        message    = message,
        choices    = choices,
        validate   = lambda result: result in [choice if isinstance(choice, str) else choice["value"] for choice in choices],
        filter     = lambda result: result,
        max_height = "75%"
    ).execute_async()

bolum_baslik = ""

medya_yonetici = MediaManager()
cikaricilar_yonetici = ExtractorManager()
secilen_data = [

]
eklentiler_yonetici        = PluginManager()


suanki_eklenti =eklentiler_yonetici.select_plugin("HDFilmCehennemi")

async def eklenti_ile_arama(eklenti:PluginBase):

    sorgu = input("Arama: ").strip()
    if not sorgu:
        return
    sonuclar = await eklenti.search(sorgu)

    if not sonuclar:
        konsol.print(f"[bold red]'{sorgu}' için hiçbir sonuç bulunamadı![/bold red]")
        return

    secilen_sonuc = await eklenti_sonuc_secimi("İçerik sonuçlarından birini seçin:", sonuclar)

    if secilen_sonuc:
        await sonuc_detaylari_goster({"plugin": eklenti.name, "url": secilen_sonuc})

async def get_main_page(eklenti:PluginBase):

    sonuclar = await eklenti.get_main_page()

    if not sonuclar:
        konsol.print(f"[bold red]Hiçbir sonuç bulunamadı![/bold red]")
        return

    secilen_sonuc = await eklenti_sonuc_secimi("İçerik sonuçlarından birini seçin:", sonuclar)

    if secilen_sonuc:
        await sonuc_detaylari_goster({"plugin": eklenti.name, "url": secilen_sonuc})
    
    
async def eklenti_sonuc_secimi(message, sonuclar: list):
    if not sonuclar:
        return None
    return await select_from_fuzzy(
        message = message,
        choices = [{"name": sonuc.title, "value": sonuc.url} for sonuc in sonuclar]
    )

async def __medya_bilgisi_yukle(url: str, deneme: int = 3):
        """
        Belirtilen URL için medya bilgilerini, belirlenen deneme sayısı kadar yüklemeye çalışır.
        """
        for _ in range(deneme):
            with suppress(Exception):
                return await suanki_eklenti.load_item(url)

        konsol.print("[bold red]Medya bilgileri yüklenemedi![/bold red]")
        return None

async def sonuc_detaylari_goster(secilen_sonuc):
    """
    Seçilen sonucun detaylarını gösterir; medya bilgilerini yükler, dizi ise bölüm seçimi sağlar.
    """
    secilen_sonuc = secilen_sonuc
    try:
        # Seçilen sonucun detaylarını al
        if isinstance(secilen_sonuc, dict) and "plugin" in secilen_sonuc:
            eklenti_adi = secilen_sonuc["plugin"]
            url         = secilen_sonuc["url"]

            suanki_eklenti = eklentiler_yonetici.select_plugin(eklenti_adi)
        else:
            url = secilen_sonuc

        medya_bilgi = await __medya_bilgisi_yukle(url)
        if not medya_bilgi:
            return konsol.print("[bold red]Medya bilgileri yüklenemedi![/bold red]")

    except Exception as hata:
        konsol.log(secilen_sonuc)
        konsol.print(f"[bold red]{hata}[/bold red]")
        return None

    # Medya bilgilerini göster ve başlığı ayarla
    medya_yonetici.set_title(f"{suanki_eklenti.name} | {medya_bilgi.title}")
    konsol.print(f"{suanki_eklenti.name} | {medya_bilgi.title}", medya_bilgi)

    # Eğer medya bilgisi dizi ise bölüm seçimi yapılır
    if isinstance(medya_bilgi, SeriesInfo):
        dizi = True
        # await dizi_bolum_secimi(medya_bilgi)
    else:
        dizi         = False
        bolum_baslik = ""
        baglantilar       = await suanki_eklenti.load_links(medya_bilgi.url)
        await baglanti_secenekleri_goster(baglantilar)

async def baglanti_secenekleri_goster(baglantilar):
        """
        Bağlantı seçeneklerini kullanıcıya sunar ve seçilen bağlantıya göre oynatma işlemini gerçekleştirir.
        """
        if not baglantilar:
            konsol.print("[bold red]Hiçbir bağlantı bulunamadı![/bold red]")
            return konsol.print("[bold red]Bağlantı bulunamadı![/bold red]")

        # Doğrudan oynatma seçeneği
        # if hasattr(suanki_eklenti, "play") and callable(getattr(suanki_eklenti, "play", None)):
        #     return await direkt_oynat(baglantilar)

        # Bağlantıları çıkarıcılarla eşleştir
        haritalama = cikaricilar_yonetici.map_links_to_extractors(baglantilar)

        # Uygun çıkarıcı kontrolü
        if not haritalama:
            konsol.print("[bold red]Hiçbir Extractor bulunamadı![/bold red]")
            konsol.print(baglantilar)
            return konsol.print("[bold red]Bağlantı bulunamadı![/bold red]")

        # Kullanıcı seçenekleri
        secim = await select_from_fuzzy(
            message = "Ne yapmak istersiniz?",
            choices = ["İzle", "Tüm Eklentilerde Ara", "Ana Menü"]
        )

        match secim:
            case "İzle":
                secilen_link = await select_from_fuzzy(
                    message = "İzlemek için bir bağlantı seçin:",
                    choices = [{"name": cikarici_adi, "value": link} for link, cikarici_adi in haritalama.items()]
                )
                if secilen_link:
                    await extractor_ile_oynat(secilen_link)

            case "Tüm Eklentilerde Ara":
                # await tum_eklentilerde_arama()
                pass

            case _:
                pass


async def extractor_ile_oynat( secilen_link: str):
        """
        Seçilen bağlantıya göre medya oynatma işlemini gerçekleştirir.
        """
        # Uygun çıkarıcıyı bul
        cikarici: ExtractorBase = cikaricilar_yonetici.find_extractor(secilen_link)
        if not cikarici:
            return konsol.print("[bold red]Uygun Extractor bulunamadı.[/bold red]")

        try:
            # Medya bilgilerini çıkar
            extract_data = await cikarici.extract(secilen_link, referer=suanki_eklenti.main_url)
        except Exception as hata:
            konsol.print(f"[bold red]{cikarici.name} » hata oluştu: {hata}[/bold red]")
            return 0
        debug_log(extract_data)

        secilen_data = await __baglanti_secimi_yap(extract_data)
        debug_log("secilen_data : ", secilen_data)
        if not secilen_data:
            return 0

        await __medya_ayarla(secilen_data)
        debug_log("medya ayarlandı, oynatılıyor...", secilen_data)
        medya_yonetici.play_media(secilen_data)
    
        konsol.print("[bold green]İçerik bitti![/bold green]")

async def __baglanti_secimi_yap( extract_data):
    """
    Birden fazla bağlantı varsa seçim yapar.
    """
    if isinstance(extract_data, list):
        return await select_from_fuzzy(
            message = "Birden fazla bağlantı bulundu, lütfen birini seçin:",
            choices = [{"name": data.name, "value": data} for data in extract_data]
        )
    return extract_data


    

async def __medya_ayarla(secilen_data):
    """
    Medya bilgilerini ayarlar.
    """

    medya_yonetici.set_headers(secilen_data.headers)

    if secilen_data.referer and not secilen_data.headers.get("Referer"):
        medya_yonetici.set_headers({"Referer": secilen_data.referer})

    if suanki_eklenti.name not in medya_yonetici.get_title():
        medya_yonetici.set_title(f"{suanki_eklenti.name} | {medya_yonetici.get_title()}")

    if bolum_baslik:
        medya_yonetici.set_title(f"{medya_yonetici.get_title()} | {bolum_baslik}")

    if secilen_data.name not in medya_yonetici.get_title():
        medya_yonetici.set_title(f"{medya_yonetici.get_title()} | {secilen_data.name}")


# for data in secilen_data:
#     __medya_ayarla(data)
#     medya_yonetici.play_media(data)

if __name__ == "__main__":
    # asyncio.run(eklenti_ile_arama(suanki_eklenti))
    guncelleyici = MainUrlGuncelleyici()
    guncelleyici.guncelle()
    asyncio.run(get_main_page(suanki_eklenti))