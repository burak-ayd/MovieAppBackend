import asyncio


from Core.Extractor.ExtractorModels import ExtractResult
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Media.MediaManager import MediaManager
from Core.Helpers import konsol

class PluginBase:
    name:str

suanki_eklenti = PluginBase()
suanki_eklenti.name = "DiziBox"
bolum_baslik = "Silo - 1. Sezon 1. Bölüm"

medya_yonetici = MediaManager()
secilen_data = [
    ExtractResult(
        name='King',
        url='https://dbx.molystream.org/embed/sheila/11093-64548cfdbd7ecf42a58a0946',
        referer='https://dbx.molystream.org/embed/sheila/11093-64548cfdbd7ecf42a58a0946',
        headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0',
            'Cookie': {'LockUser': 'true', 'isTrustedUser': 'true', 'dbxu': '1722403730363'}
        },
        subtitles=[]
    ),
    ExtractResult(
        name='Moly',
        url='https://vidmoly.biz/embed-ssty1czfl752.html',
        referer='',
        headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0'},
        subtitles=[]
    )
    # ExtractResult(
    #     name='Okru',
    #     url='http://ok.ru/video/5485323881007',
    #     referer='',
    #     headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0'},
    #     subtitles=[]
    # )
]



async def main():
    ext = ExtractorManager()
    data_ext = ext.find_extractor("https://dbx.molystream.org/embed/sheila/11093-64548cfdbd7ecf42a58a0946")
    print(data_ext)
    sonuc = await data_ext.extract("https://dbx.molystream.org/embed/sheila/11093-64548cfdbd7ecf42a58a0946/q/1")
    konsol.print(sonuc)
    medya_yonetici.play_media(sonuc)

# if __name__ == "__main__":    
#     asyncio.run(main())

def __medya_ayarla(secilen_data):
    """
    Medya bilgilerini ayarlar.
    """

    medya_yonetici.set_headers(secilen_data.headers)

    if secilen_data.referer and not secilen_data.headers.get("Referer"):
        medya_yonetici.set_headers({"Referer": secilen_data.referer})

    if suanki_eklenti.name not in medya_yonetici.get_title():
        medya_yonetici.set_title(f"{suanki_eklenti.name}")

    if bolum_baslik:
        medya_yonetici.set_title(f"{medya_yonetici.get_title()} | {bolum_baslik}")

    if secilen_data.name not in medya_yonetici.get_title():
        medya_yonetici.set_title(f"{medya_yonetici.get_title()} | {secilen_data.name}")


for data in secilen_data:
    __medya_ayarla(data)
    medya_yonetici.play_media(data)
