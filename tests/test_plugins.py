import pytest
import pytest_asyncio
import asyncio
from typing import List
from urllib.parse import urlparse

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginLoader import PluginLoader
from Core.Plugin.PluginManager import PluginManager
from Core.Helpers import konsol
from Core.Plugin.PluginModels import (
    SearchResult,
    MainPageResult,
    MovieInfo,
    SeriesInfo,
)



def get_plugin_classes():
    """Tüm eklenti sınıflarını dinamik olarak yükler."""
    loader = PluginLoader("Plugins")
    plugins_dict = loader.load_all()
    return plugins_dict


PLUGINS = get_plugin_classes()


@pytest.fixture(params=list(PLUGINS.keys()))
def plugin_name(request):
    return request.param


@pytest_asyncio.fixture
async def plugin_instance(plugin_name):
    """Her test için temiz ve bağımsız bir plugin örneği oluşturur ve kapatır."""
    plugin_class = PLUGINS[plugin_name].__class__
    plugin = plugin_class()
    yield plugin
    if hasattr(plugin, "close"):
        await plugin.close()



# =====================================================================
# 1. SÖZLEŞME VE MİMARİ UYUMLULUK TESTLERİ (CONTRACT & ARCHITECTURE)
# =====================================================================

class TestPluginContract:
    """Tüm eklentilerin PluginBase sözleşmesine tam uyduğunu doğrular."""

    def test_inherits_from_plugin_base(self, plugin_instance):
        """Eklentinin PluginBase sınıfından türediğini doğrular."""
        assert isinstance(plugin_instance, PluginBase), (
            f"{plugin_instance.__class__.__name__} PluginBase sınıfından türetilmelidir!"
        )

    def test_required_attributes(self, plugin_instance):
        """Eklentinin zorunlu sınıf niteliklerinin eksiksiz ve geçerli olduğunu doğrular."""
        # 1. name
        assert hasattr(plugin_instance, "name"), "Plugin 'name' niteliğine sahip olmalı."
        assert isinstance(plugin_instance.name, str) and len(plugin_instance.name) > 0, (
            "Plugin 'name' boş olmayan bir string olmalı."
        )

        # 2. main_url
        assert hasattr(plugin_instance, "main_url"), "Plugin 'main_url' niteliğine sahip olmalı."
        parsed_url = urlparse(plugin_instance.main_url)
        assert parsed_url.scheme in ("http", "https"), (
            f"Plugin 'main_url' geçerli bir HTTP/HTTPS adresi olmalı: {plugin_instance.main_url}"
        )
        assert parsed_url.netloc, f"Plugin 'main_url' geçerli bir domain içermeli: {plugin_instance.main_url}"

        # 3. language
        assert hasattr(plugin_instance, "language"), "Plugin 'language' niteliğine sahip olmalı."
        assert isinstance(plugin_instance.language, str) and len(plugin_instance.language) >= 2

        # 4. description
        assert hasattr(plugin_instance, "description"), "Plugin 'description' niteliğine sahip olmalı."
        assert isinstance(plugin_instance.description, str)

        # 5. main_page
        assert hasattr(plugin_instance, "main_page"), "Plugin 'main_page' niteliğine sahip olmalı."
        assert isinstance(plugin_instance.main_page, dict), "Plugin 'main_page' bir sözlük (dict) olmalı."
        assert len(plugin_instance.main_page) > 0, "Plugin 'main_page' en az 1 kategori içermelidir."

    def test_required_methods_exist_and_callable(self, plugin_instance):
        """Zorunlu metodların tanımlı ve çağrılabilir olduğunu doğrular."""
        methods = ["get_main_page", "search", "load_item", "load_links"]
        for method_name in methods:
            assert hasattr(plugin_instance, method_name), f"Plugin '{method_name}' metoduna sahip olmalı."
            method = getattr(plugin_instance, method_name)
            assert callable(method), f"Plugin '{method_name}' çağrılabilir (callable) olmalı."
            assert asyncio.iscoroutinefunction(method), f"Plugin '{method_name}' async bir metod olmalı."


# =====================================================================
# 2. YARDIMCI METOD TESTLERİ (HELPER UTILITIES)
# =====================================================================

class TestPluginHelpers:
    """fix_url, clean_title, url_update gibi temel yardımcı metodları doğrular."""

    def test_fix_url(self, plugin_instance):
        """fix_url metodunun relative, protocol-relative ve absolute URL'leri doğru çevirdiğini doğrular."""
        # 1. Boş URL
        assert plugin_instance.fix_url("") == ""
        assert plugin_instance.fix_url(None) == ""

        # 2. Tam URL (değişmemeli)
        full_url = "https://cdn.example.com/images/poster.jpg"
        assert plugin_instance.fix_url(full_url) == full_url

        # 3. Protocol-relative URL (// ile başlayan)
        proto_rel = "//cdn.example.com/video.mp4"
        assert plugin_instance.fix_url(proto_rel) == "https://cdn.example.com/video.mp4"

        # 4. Root-relative URL (/ ile başlayan)
        root_rel = "/film/matrix-izle"
        fixed = plugin_instance.fix_url(root_rel)
        assert fixed.startswith(plugin_instance.main_url) or fixed.startswith("http")
        assert "/film/matrix-izle" in fixed

    def test_clean_title(self, plugin_instance):
        """clean_title metodunun gereksiz anahtar kelimeleri başarıyla temizlediğini doğrular."""
        dirty_titles = [
            ("The Matrix Türkçe Dublaj izle", "The Matrix"),
            ("Inception full film izle", "Inception"),
            ("Interstellar altyazılı 1080p", "Interstellar"),
            ("Avatar filmini full izle", "Avatar"),
        ]
        for dirty, expected_prefix in dirty_titles:
            cleaned = plugin_instance.clean_title(dirty)
            assert expected_prefix.lower() in cleaned.lower(), (
                f"Temizlenen başlık '{cleaned}' beklenen '{expected_prefix}' ifadesini içermelidir."
            )
            # 'izle' gibi çöpler kalmamalı
            assert "izle" not in cleaned.lower().split()

    @pytest.mark.asyncio
    async def test_url_update(self, plugin_instance):
        """url_update metodunun domain değişikliğinde tüm yolları senkronize ettiğini doğrular."""
        original_url = plugin_instance.main_url
        new_test_url = "https://yeni-ayna-domain.com"

        try:
            await plugin_instance.url_update(new_test_url)
            assert plugin_instance.main_url == new_test_url
            assert new_test_url in plugin_instance.favicon
        finally:
            # Test sonrası orijinal haline geri getir
            await plugin_instance.url_update(original_url)


# =====================================================================
# 3. FONKSİYONEL ARAMA TESTLERİ (SEARCH FUNCTIONALITY)
# =====================================================================

class TestPluginSearch:
    """Plugin search fonksiyonunun canlı ve sınır durum davranışlarını doğrular."""

    @pytest.mark.asyncio
    async def test_search_popular_query(self, plugin_instance):
        """Popüler bir film araması yaparak sonuçların model uyumunu ve içeriğini test eder."""
        query = "silo"
        try:
            results = await plugin_instance.search(query)
        except Exception as e:
            pytest.skip(f"{plugin_instance.name} arama isteğinde ağ/bağlantı hatası: {e}")

        assert isinstance(results, list), f"search() bir liste dönmeli, gelen tip: {type(results)}"

        # Eğer sonuç döndüyse her elemanı sıkı kontrolden geçir
        for item in results:
            assert isinstance(item, SearchResult), (
                f"Sonuç elemanı SearchResult modeli olmalıdır, gelen: {type(item)}"
            )
            assert item.title and len(item.title.strip()) > 0, "SearchResult.title boş olamaz."
            assert item.url and (item.url.startswith("http://") or item.url.startswith("https://")), (
                f"SearchResult.url geçerli bir tam HTTP URL olmalıdır: {item.url}"
            )
            if item.poster:
                assert item.poster.startswith("http://") or item.poster.startswith("https://"), (
                    f"SearchResult.poster tam URL olmalıdır: {item.poster}"
                )
        konsol.print(results)

    @pytest.mark.asyncio
    async def test_search_non_existent_query(self, plugin_instance):
        """Hiç var olmayan anlamsız bir kelime arandığında çökmeden boş liste dönmelidir."""
        nonsense_query = "zxq_nonexistent_film_999888777"
        try:
            results = await plugin_instance.search(nonsense_query)
        except Exception as e:
            pytest.skip(f"{plugin_instance.name} ağ hatası: {e}")

        assert isinstance(results, list), "Var olmayan aramada boş liste dönmeli."
        assert len(results) == 0, f"Var olmayan arama için sonuç dönmemeliydi, dönen: {results}"


# =====================================================================
# 4. ANA SAYFA VE KATEGORİ LİSTELEME TESTLERİ (MAIN PAGE)
# =====================================================================

class TestPluginMainPage:
    """get_main_page fonksiyonunun kategori ve sayfalama davranışını doğrular."""

    @pytest.mark.asyncio
    async def test_get_main_page_first_category(self, plugin_instance):
        """İlk kategoriden 1. sayfayı çekerek MainPageResult nesnelerini doğrular."""
        category_name = list(plugin_instance.main_page.keys())[0]
        category_url = plugin_instance.main_page[category_name]

        try:
            results = await plugin_instance.get_main_page(page=1, url=category_url, category=category_name)
        except Exception as e:
            pytest.skip(f"{plugin_instance.name} ana sayfa çekme hatası: {e}")

        assert isinstance(results, list), f"get_main_page() liste dönmeli, gelen: {type(results)}"

        for item in results:
            assert isinstance(item, MainPageResult), (
                f"Dönen eleman MainPageResult olmalı, gelen: {type(item)}"
            )
            assert item.title and len(item.title.strip()) > 0, "MainPageResult.title boş olamaz."
            assert item.url and (item.url.startswith("http://") or item.url.startswith("https://")), (
                f"MainPageResult.url tam HTTP URL olmalı: {item.url}"
            )
        konsol.print(results)


# =====================================================================
# 5. İÇERİK DETAY YÜKLEME TESTLERİ (LOAD ITEM)
# =====================================================================

class TestPluginLoadItem:
    """load_item fonksiyonunun meta veri ayıklamasını ve hata dayanıklılığını doğrular."""

    @pytest.mark.asyncio
    async def test_load_item_from_search(self, plugin_instance):
        """Arama sonucundan gelen bir filmin detay sayfasını yükler ve alanları doğrular."""
        try:
            results = await plugin_instance.search("Matrix")
        except Exception as e:
            pytest.skip(f"Arama aşaması atlandı: {e}")

        if not results:
            # Arama sonuç vermediyse ana sayfadan bir link deneyelim
            category_name = list(plugin_instance.main_page.keys())[0]
            category_url = plugin_instance.main_page[category_name]
            try:
                main_items = await plugin_instance.get_main_page(1, category_url, category_name)
                target_url = main_items[0].url if main_items else None
            except Exception:
                target_url = None
        else:
            target_url = results[0].url

        if not target_url:
            pytest.skip(f"{plugin_instance.name} için test edilecek içerik URL'si bulunamadı.")

        try:
            item = await plugin_instance.load_item(target_url)
        except Exception as e:
            pytest.fail(f"load_item({target_url}) beklenmeyen bir hata fırlattı: {e}")

        assert item is not None, f"load_item({target_url}) None dönemez."
        assert isinstance(item, (MovieInfo, SeriesInfo)), (
            f"load_item sonucu MovieInfo veya SeriesInfo olmalı, gelen: {type(item)}"
        )
        assert item.title and len(item.title.strip()) > 0, "Yüklenen içeriğin başlığı (title) boş olamaz."
        assert item.url and item.url.startswith("http"), "İçerik url'si tam olmalı."
        konsol.print(item)

    @pytest.mark.asyncio
    async def test_load_item_404_resilience(self, plugin_instance):
        """Geçersiz veya 404 dönen bir URL verildiğinde eklentinin çökmediğini doğrular."""
        bogus_url = f"{plugin_instance.main_url}/bu-film-kesinlikle-yok-404-test-hdf"
        try:
            item = await plugin_instance.load_item(bogus_url)
            # Hata durumunda None dönebilir veya default nesne, ancak unhandled exception atmamalıdır
            assert item is None or isinstance(item, (MovieInfo, SeriesInfo))
        except Exception as e:
            pytest.fail(f"load_item 404 URL için unhandled exception fırlattı: {e}")


# =====================================================================
# 6. VİDEO KAYNAK / EMBED LİNK ÇÖZÜMLEME TESTLERİ (LOAD LINKS)
# =====================================================================

class TestPluginLoadLinks:
    """load_links fonksiyonunun oynatıcı / embed linklerini çıkarma başarısını doğrular."""

    @pytest.mark.asyncio
    async def test_load_links_returns_valid_urls(self, plugin_instance):
        """Gerçek bir içerik sayfasından embed linkleri çeker ve doğrular."""
        try:
            results = await plugin_instance.search("silo")
        except Exception as e:
            pytest.skip(f"Arama aşaması atlandı: {e}")

        if not results:
            category_name = list(plugin_instance.main_page.keys())[0]
            category_url = plugin_instance.main_page[category_name]
            try:
                main_items = await plugin_instance.get_main_page(1, category_url, category_name)
                target_url = main_items[0].url if main_items else None
            except Exception:
                target_url = None
        else:
            target_url = results[0].url

        if not target_url:
            pytest.skip(f"{plugin_instance.name} için test edilecek içerik URL'si bulunamadı.")

        try:
            links = await plugin_instance.load_links(target_url)
            
        except Exception as e:
            pytest.fail(f"load_links({target_url}) beklenmeyen bir hata fırlattı: {e}")

        assert isinstance(links, list), f"load_links() liste dönmelidir, gelen tip: {type(links)}"

        for link in links:
            assert isinstance(link, str), f"Embed link string olmalı, gelen: {type(link)}"
            assert link.startswith("http://") or link.startswith("https://"), (
                f"Embed link tam HTTP/HTTPS URL olmalıdır: {link}"
            )
        konsol.print(links)


# =====================================================================
# 7. PLUGIN MANAGER ENTEGRASYON TESTİ
# =====================================================================

class TestPluginManagerIntegration:
    """PluginManager üzerinden toplu arama ve eklenti yönetimini test eder."""

    async def tum_eklentilerde_arama_sorgula(self, manager: PluginManager, sorgu: str) -> list:
        """
        Tüm eklentilerde arama yapar ve bulunan sonuçları listeler.
        """
        tum_sonuclar = []
        # Her eklentide arama yap
        for eklenti_adi, eklenti in manager.plugins.items():
            # Eklenti türü kontrolü
            if not isinstance(eklenti, PluginBase):
                konsol.print(f"[yellow][!] {eklenti_adi} geçerli bir PluginBase değil, atlanıyor...[/yellow]")
                continue

            if eklenti_adi in ["Shorten"]:
                continue

            konsol.log(f"[yellow][~] {eklenti_adi:<19} aranıyor...[/]")
            try:
                sonuclar = await eklenti.search(sorgu)
                if sonuclar:
                    # Sonuçları listeye ekle
                    tum_sonuclar.extend(
                        [
                            {
                                "plugin" : eklenti_adi,
                                "title"  : sonuc.title,
                                "url"    : sonuc.url,
                                "poster" : sonuc.poster
                            }
                            for sonuc in sonuclar
                        ]
                    )
            except Exception as hata:
                konsol.print(f"[bold red]{eklenti_adi} » hata oluştu: {hata}[/bold red]")

        if not tum_sonuclar:
            konsol.print("[bold red]Hiçbir sonuç bulunamadı![/bold red]")
        return tum_sonuclar

    @pytest.mark.asyncio
    async def test_manager_loads_and_searches(self):
        manager = PluginManager("Plugins")
        names = manager.get_plugin_names()
        assert len(names) > 0, "PluginManager en az bir eklenti yüklemelidir."

        # Toplu arama testi
        try:
            tum_sonuclar = await self.tum_eklentilerde_arama_sorgula(manager, "Matrix")
            assert isinstance(tum_sonuclar, list), "Dönen sonuçlar bir liste olmalıdır."
            for item in tum_sonuclar:
                assert "plugin" in item and item["plugin"]
                assert "title" in item and item["title"]
                assert "url" in item and item["url"]
        finally:
            await manager.close_plugins()

