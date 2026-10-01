import sys
from pathlib import Path
import asyncio

# 1. Windows Import ve Kök Dizin Kilidi
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv()

from Core.Plugin.PluginManager import PluginManager
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Libs.TMDB import TMDBClient
from Core.Media.MediaHandler import MediaHandler

async def main():
    print("[*] STREAM Sistemi Başlatılıyor...")

    # Yöneticileri Başlat
    plugin_mgr = PluginManager()
    plugin_mgr.initialize()

    extractor_mgr = ExtractorManager()
    extractor_mgr.initialize()

    tmdb = TMDBClient()

    print(f"[+] Yüklenen Siteler: {list(plugin_mgr.plugins.keys())}")
    print(f"[+] Yüklenen Extractor'lar: {[ext.name for ext in extractor_mgr.extractors]}")

    # Örnek Arama ve JIT Çözümleme Testi
    query = "Matrix"
    print(f"[*] '{query}' için tüm sağlayıcılarda arama yapılıyor...")
    results = await plugin_mgr.search_all(query)

    if results:
        selected = results[0]
        print(f"[+] İlk sonuç seçildi: {selected.title} ({selected.provider})")
        plugin = plugin_mgr.get_plugin(selected.provider)

        print(f"[*] Sayfadan embed linkler alınıyor: {selected.url}")
        embed_links = await plugin.load_links(selected.url)

        for embed_url in embed_links:
            print(f"[*] Extractor çözüyor: {embed_url}")
            stream_info = await extractor_mgr.resolve(embed_url)
            if stream_info:
                print(f"[+] Akış hazır: {stream_info.stream_url}")
                MediaHandler.play(stream_info)
                break
    else:
        print("[!] Arama sonucu bulunamadı.")

if __name__ == "__main__":
    asyncio.run(main())
