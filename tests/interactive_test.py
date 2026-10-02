"""
Interactive Plugin Test Runner (Konsol Tabanlı Eklenti Test Sistemi)
-------------------------------------------------------------------
Bu script, eklentileri (Plugins) ve çıkarıcıları (Extractors) gerçek
kullanım senaryoları üzerinden konsoldan yönlendirmeli ve etkileşimli
olarak adım adım test etmek için tasarlanmıştır.

Kullanım:
    python tests/interactive_test.py
"""

import asyncio
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Windows konsol UTF-8 çıktı desteği (cp1254 çökmesini önler)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Proje kök dizinini sys.path'e ekle
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from Core.Helpers import is_debug, set_debug, debug_log
from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Extractor.ExtractorModels import ExtractResult
from Core.Media.MediaManager import MediaManager
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginManager import PluginManager
from Core.Plugin.PluginModels import (
    Episode,
    MainPageResult,
    MovieInfo,
    SearchResult,
    SeriesInfo,
)

konsol = Console()


class InteractiveTestRunner:
    def __init__(self):
        self.plugin_mgr = PluginManager()
        self.extractor_mgr = ExtractorManager()
        self.media_mgr = MediaManager()
        self.plugins: Dict[str, PluginBase] = self.plugin_mgr.plugins
        self.active_plugin: Optional[PluginBase] = None
        self.active_plugin_name: str = ""

    # =========================================================================
    # YARDIMCI GÖRSELLEŞTİRME METOTLARI
    # =========================================================================

    def print_banner(self, title: str, subtitle: str = ""):
        konsol.print()
        konsol.rule(f"[bold cyan]{title}[/bold cyan]", style="cyan")
        if subtitle:
            konsol.print(f"[dim]{subtitle}[/dim]", justify="center")
        konsol.print()

    def print_plugin_info(self, plugin: PluginBase):
        cat_count = len(plugin.main_page) if getattr(plugin, "main_page", None) else 0
        info_text = (
            f"[bold green]Adı:[/bold green] {plugin.name} | "
            f"[bold green]Dil:[/bold green] {plugin.language} | "
            f"[bold green]URL:[/bold green] [underline cyan]{plugin.main_url}[/underline cyan]\n"
            f"[bold green]Açıklama:[/bold green] {plugin.description}\n"
            f"[bold green]Tanımlı Kategori Sayısı:[/bold green] {cat_count}"
        )
        konsol.print(
            Panel(
                info_text,
                title=f"[bold gold1]Aktif Eklenti: {plugin.name}[/bold gold1]",
                border_style="gold1",
                box=box.ROUNDED,
            )
        )

    # =========================================================================
    # ANA MENÜ & NAVİGASYON
    # =========================================================================

    async def run(self):
        """Etkileşimli test döngüsünün ana giriş noktası."""
        while True:
            self.print_banner("Eklenti Etkileşimli Test Konsolu")
            plugin_count = len(self.plugins)
            extractor_count = len(self.extractor_mgr.extractors)

            debug_status = "[bold green]AÇIK[/bold green]" if is_debug() else "[dim]KAPALI[/dim]"
            konsol.print(
                f"  [bold]Durum:[/bold] [green]{plugin_count}[/green] Eklenti, "
                f"[green]{extractor_count}[/green] Extractor yüklü | Debug Modu: {debug_status}\n"
            )

            table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 2))
            table.add_column("Seçenek", style="bold yellow")
            table.add_column("Açıklama", style="white")

            table.add_row("[1]", "Plugin Seç ve Test Et (Tekil Eklenti Testi)")
            table.add_row("[2]", "Toplu Arama Yap (Tüm Eklentilerde Eşzamanlı Arama)")
            table.add_row("[3] ", "Yüklü Eklentiler ve Extractor'lar Özeti")
            table.add_row("[4] ", "Doğrudan URL Testi (load_item / load_links / Extractor)")
            table.add_row("[d] ", f"Debug Modunu Aç/Kapat (Şu an: {'Açık' if is_debug() else 'Kapalı'})")
            table.add_row("[0] ", "Çıkış")

            konsol.print(table)
            konsol.print()

            secim = Prompt.ask("[bold cyan]Seçiminiz[/bold cyan]", choices=["1", "2", "3", "4", "d", "D", "0"], default="1")

            if secim == "1":
                await self.menu_select_and_test_plugin()
            elif secim == "2":
                await self.menu_collective_search()
            elif secim == "3":
                self.menu_show_system_overview()
            elif secim == "4":
                await self.menu_direct_url_test()
            elif secim.lower() == "d":
                new_state = not is_debug()
                set_debug(new_state)
                konsol.print(f"\n[bold gold1]Debug modu {'AÇILDI' if new_state else 'KAPATILDI'}.[/bold gold1]\n")
            elif secim == "0":
                konsol.print("\n[bold yellow]Oturumlar kapatılıyor...[/bold yellow]")
                await self.plugin_mgr.close_plugins()
                konsol.print("[bold green]Başarıyla çıkış yapıldı. İyi çalışmalar![/bold green]\n")
                break

    # =========================================================================
    # 1. TEKİL PLUGIN SEÇİMİ VE TESTİ
    # =========================================================================

    async def menu_select_and_test_plugin(self):
        """Kullanıcının tek bir eklenti seçip onun özelliklerini test ettiği alt menü."""
        plugin_names = self.plugin_mgr.get_plugin_names()
        if not plugin_names:
            konsol.print("[bold red]Yüklü hiçbir eklenti bulunamadı![/bold red]")
            return

        self.print_banner("Yüklü Eklentiler Listesi")
        table = Table(box=box.ROUNDED, header_style="bold magenta")
        table.add_column("#", style="dim", width=4, justify="center")
        table.add_column("Eklenti Adı", style="bold green")
        table.add_column("Dil", width=6, justify="center")
        table.add_column("Ana URL", style="cyan")
        table.add_column("Açıklama", style="dim")

        for idx, name in enumerate(plugin_names, 1):
            plugin = self.plugins[name]
            table.add_row(
                str(idx),
                plugin.name,
                getattr(plugin, "language", "-"),
                getattr(plugin, "main_url", "-"),
                getattr(plugin, "description", "-")[:45] + "...",
            )

        konsol.print(table)
        konsol.print("[dim]0: Ana Menüye Dön[/dim]\n")

        valid_choices = [str(i) for i in range(len(plugin_names) + 1)]
        secim = Prompt.ask("[bold cyan]Test etmek istediğiniz eklentiyi seçin[/bold cyan]", choices=valid_choices, default="1")

        if secim == "0":
            return

        selected_name = plugin_names[int(secim) - 1]
        self.active_plugin_name = selected_name
        self.active_plugin = self.plugins[selected_name]

        await self.plugin_test_loop(self.active_plugin)

    async def plugin_test_loop(self, plugin: PluginBase):
        """Seçilen eklenti için test işlemlerini barındıran döngü."""
        while True:
            self.print_banner(f"{plugin.name} Test Alanı")
            self.print_plugin_info(plugin)

            table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 2))
            table.add_column("Seçenek", style="bold yellow")
            table.add_column("İşlem", style="white")

            table.add_row("[1]", "Arama Yap (search)")
            table.add_row("[2]", "Ana Sayfa / Kategori İçeriklerini Çek (get_main_page)")
            table.add_row("[3]", "URL ile İçerik Detayı Çek (load_item)")
            table.add_row("[4]", "URL ile Video Linklerini Çek (load_links)")
            table.add_row("[0]", "Üst Menüye Dön")

            konsol.print(table)
            konsol.print()

            secim = Prompt.ask("[bold cyan]İşlem Seçiniz[/bold cyan]", choices=["1", "2", "3", "4", "0"], default="1")

            if secim == "1":
                await self.action_search_in_plugin(plugin)
            elif secim == "2":
                await self.action_main_page_in_plugin(plugin)
            elif secim == "3":
                url = Prompt.ask("[bold cyan]İçerik URL'sini girin[/bold cyan]").strip()
                if url:
                    await self.action_load_item(plugin, url)
            elif secim == "4":
                url = Prompt.ask("[bold cyan]İzleme / Bölüm URL'sini girin[/bold cyan]").strip()
                if url:
                    await self.action_load_links(plugin, url)
            elif secim == "0":
                break

    # =========================================================================
    # ARAMA (SEARCH) İŞLEMLERİ
    # =========================================================================

    async def action_search_in_plugin(self, plugin: PluginBase):
        query = Prompt.ask(f"[bold cyan]'{plugin.name}' içinde aranacak kelime[/bold cyan]").strip()
        if not query:
            return

        with konsol.status(f"[bold green]'{plugin.name}' üzerinde aranıyor...[/bold green]"):
            try:
                results = await plugin.search(query)
            except Exception as e:
                konsol.print(f"[bold red]Arama hatası:[/bold red] {e}")
                konsol.print(f"[dim]{traceback.format_exc()}[/dim]")
                return

        if not results:
            konsol.print(f"[yellow]'{query}' için sonuç bulunamadı.[/yellow]")
            return

        await self.display_and_handle_search_results(results, plugin=plugin)

    async def display_and_handle_search_results(
        self, results: List[SearchResult], plugin: Optional[PluginBase] = None
    ):
        """Arama sonuçlarını listeler ve kullanıcının seçip detay/link akışına gitmesini sağlar."""
        self.print_banner(f"Arama Sonuçları ({len(results)} Adet)")

        table = Table(box=box.ROUNDED, header_style="bold cyan")
        table.add_column("#", style="dim", width=4, justify="center")
        table.add_column("Eklenti", style="magenta", width=16)
        table.add_column("Başlık", style="bold white")
        table.add_column("Yıl", width=8, justify="center")
        table.add_column("Tür", width=8, justify="center")
        table.add_column("URL", style="dim cyan")

        for idx, item in enumerate(results, 1):
            p_name = getattr(item, "plugin", None) or (plugin.name if plugin else "Bilinmiyor")
            year = str(getattr(item, "year", "") or "-")
            m_type = str(getattr(item, "media_type", "") or "-")
            url = getattr(item, "url", "")
            table.add_row(str(idx), p_name, item.title, year, m_type, url)

        konsol.print(table)
        konsol.print("[dim]Detayını görmek istediğiniz numara (1-N) veya 'b' (Geri)[/dim]")

        secim = Prompt.ask("[bold cyan]İşlem yapılacak içerik no[/bold cyan]", default="b").strip()
        if secim.lower() in ("b", "q", "0", ""):
            return

        if not secim.isdigit() or not (1 <= int(secim) <= len(results)):
            konsol.print("[red]Geçersiz seçim.[/red]")
            return

        selected_item = results[int(secim) - 1]
        target_plugin = plugin
        if not target_plugin:
            p_name = getattr(selected_item, "plugin", None)
            if p_name and p_name in self.plugins:
                target_plugin = self.plugins[p_name]
            else:
                target_plugin = self.active_plugin

        if not target_plugin:
            konsol.print("[red]Eklenti tespit edilemedi![/red]")
            return

        konsol.print(f"[bold green]Seçildi:[/bold green] {selected_item.title} ({target_plugin.name})")
        await self.action_load_item(target_plugin, selected_item.url)

    # =========================================================================
    # 2. TOPLU ARAMA (COLLECTIVE SEARCH)
    # =========================================================================

    async def menu_collective_search(self):
        """Tüm eklentilerde eşzamanlı (asyncio.gather) arama yapar."""
        query = Prompt.ask("[bold cyan]Tüm eklentilerde aranacak kelime[/bold cyan]").strip()
        if not query:
            return

        plugin_list = list(self.plugins.values())
        self.print_banner(f"Toplu Arama: '{query}' ({len(plugin_list)} Eklenti)")

        with konsol.status(f"[bold green]Tüm eklentiler sorgulanıyor...[/bold green]"):
            tasks = [p.search(query) for p in plugin_list]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

        combined_results: List[SearchResult] = []
        for p, resp in zip(plugin_list, responses):
            if isinstance(resp, Exception):
                konsol.print(f"[red][-] {p.name}: Hata ({resp})[/red]")
            elif isinstance(resp, list):
                konsol.print(f"[green][+] {p.name}: {len(resp)} sonuç bulundu[/green]")
                for item in resp:
                    if isinstance(item, SearchResult):
                        if not item.plugin:
                            item.plugin = p.name
                        combined_results.append(item)
            else:
                konsol.print(f"[yellow]! {p.name}: Beklenmeyen dönüş tipi ({type(resp)})[/yellow]")

        if not combined_results:
            konsol.print(f"[yellow]'{query}' için hiçbir eklentide sonuç bulunamadı.[/yellow]")
            return

        await self.display_and_handle_search_results(combined_results, plugin=None)

    # =========================================================================
    # 3. ANA SAYFA / KATEGORİ LİSTELEME
    # =========================================================================

    async def action_main_page_in_plugin(self, plugin: PluginBase):
        """Eklentinin ana sayfa ve kategorilerini çeker ve listeler."""
        categories = getattr(plugin, "main_page", {}) or {}
        cat_names = list(categories.keys())

        table = Table(box=box.ROUNDED, header_style="bold magenta")
        table.add_column("#", style="dim", width=4, justify="center")
        table.add_column("Kategori / Bölüm Adı", style="bold white")
        table.add_column("Hedef URL", style="dim cyan")

        table.add_row("1", "[bold cyan]* Varsayılan Ana Sayfa (Home) *[/bold cyan]", plugin.main_url)
        for idx, cat_name in enumerate(cat_names, 2):
            table.add_row(str(idx), cat_name, categories[cat_name])

        konsol.print(table)
        konsol.print("[dim]0: İptal / Geri[/dim]\n")

        valid_choices = [str(i) for i in range(len(cat_names) + 2)]
        secim = Prompt.ask("[bold cyan]Listelemek istediğiniz kategoriyi seçin[/bold cyan]", choices=valid_choices, default="1")

        if secim == "0":
            return

        page = IntPrompt.ask("[bold cyan]Sayfa No[/bold cyan]", default=1)

        selected_cat_name = ""
        selected_cat_url = plugin.main_url

        if secim != "1":
            selected_cat_name = cat_names[int(secim) - 2]
            selected_cat_url = categories[selected_cat_name]

        with konsol.status(f"[bold green]'{plugin.name}' içerikleri çekiliyor (Sayfa {page})...[/bold green]"):
            items = await self.fetch_plugin_main_or_category(plugin, page, selected_cat_name, selected_cat_url)

        if not items:
            konsol.print("[yellow]Hiçbir içerik bulunamadı veya sayfa boş döndü.[/yellow]")
            return

        self.print_banner(f"{plugin.name} - İçerik Listesi ({len(items)} Adet)")
        res_table = Table(box=box.ROUNDED, header_style="bold cyan")
        res_table.add_column("#", style="dim", width=4, justify="center")
        res_table.add_column("Başlık", style="bold white")
        res_table.add_column("Kategori / Tarih", width=20, style="dim")
        res_table.add_column("IMDb", width=6, justify="center", style="gold1")
        res_table.add_column("URL", style="dim cyan")

        for idx, item in enumerate(items, 1):
            title = getattr(item, "title", "-") or "-"
            extra = getattr(item, "release_date", "") or getattr(item, "category", "") or "-"
            imdb = getattr(item, "imdb", "") or "-"
            url = getattr(item, "url", "-") or "-"
            res_table.add_row(str(idx), title, extra, imdb, url)

        konsol.print(res_table)
        konsol.print("[dim]Detayını görmek istediğiniz numara (1-N) veya 'b' (Geri)[/dim]")

        item_choice = Prompt.ask("[bold cyan]İşlem yapılacak içerik no[/bold cyan]", default="b").strip()
        if item_choice.lower() in ("b", "q", "0", ""):
            return

        if not item_choice.isdigit() or not (1 <= int(item_choice) <= len(items)):
            konsol.print("[red]Geçersiz seçim.[/red]")
            return

        selected_item = items[int(item_choice) - 1]
        target_url = getattr(selected_item, "url", "")
        if target_url:
            await self.action_load_item(plugin, target_url)

    async def fetch_plugin_main_or_category(
        self, plugin: PluginBase, page: int, category_name: str, category_url: str
    ) -> List[MainPageResult]:
        """Farklı eklentilerin get_main_page / get_category_page imzalarını güvenle çağıran adaptör."""
        items: List[MainPageResult] = []
        try:
            # Dizibox özel durumu
            if hasattr(plugin, "get_category_page") and category_name:
                raw_items = await plugin.get_category_page(page=page, category=category_name)
            else:
                # Standart get_main_page
                raw_items = await plugin.get_main_page(page=page, url=category_url, category=category_name)

            # Dizibox dictionary döner: {"popular_series": [...], "new_episodes": [...]}
            if isinstance(raw_items, dict):
                for sec_name, sec_items in raw_items.items():
                    if isinstance(sec_items, list):
                        for sub in sec_items:
                            if isinstance(sub, MainPageResult):
                                if not sub.category:
                                    sub.category = sec_name
                                items.append(sub)
            elif isinstance(raw_items, list):
                items.extend([i for i in raw_items if isinstance(i, MainPageResult)])
        except Exception as e:
            konsol.print(f"[bold red]Sayfa çekme hatası:[/bold red] {e}")
            konsol.print(f"[dim]{traceback.format_exc()}[/dim]")

        return items

    # =========================================================================
    # 4. İÇERİK DETAYI (LOAD_ITEM) VE BÖLÜM SEÇİMİ
    # =========================================================================

    async def action_load_item(self, plugin: PluginBase, url: str):
        """load_item ile film/dizi detayını çeker ve bölümleri/videoları listeler."""
        self.print_banner(f"İçerik Detayı Çekiliyor: {plugin.name}")
        konsol.print(f"[dim cyan]{url}[/dim cyan]\n")

        with konsol.status("[bold green]İçerik bilgileri ayrıştırılıyor...[/bold green]"):
            try:
                info = await plugin.load_item(url)
            except Exception as e:
                konsol.print(f"[bold red]load_item hatası:[/bold red] {e}")
                konsol.print(f"[dim]{traceback.format_exc()}[/dim]")
                return

        if not info:
            konsol.print("[yellow]İçerik bulunamadı veya boş döndü (404/Engelleme olabilir).[/yellow]")
            return

        # Film Bilgisi Görünümü
        if isinstance(info, MovieInfo):
            self.display_movie_info(info)
            if Confirm.ask("\n[bold green]Bu filmin video linklerini çekmek istiyor musunuz?[/bold green]", default=True):
                await self.action_load_links(plugin, info.url, content_title=info.title or "Film")

        # Dizi Bilgisi Görünümü
        elif isinstance(info, SeriesInfo):
            await self.display_series_info_and_select_episode(plugin, info)

        else:
            konsol.print(f"[yellow]Bilinmeyen içerik tipi:[/yellow] {type(info)}")
            konsol.print(info)
            if Confirm.ask("\n[bold green]Bu URL'nin video linklerini çekmek istiyor musunuz?[/bold green]", default=True):
                await self.action_load_links(plugin, url)

    def display_movie_info(self, movie: MovieInfo):
        genres = ", ".join(movie.genre) if movie.genre else "-"
        actors = ", ".join(movie.cast_members[:8]) if movie.cast_members else "-"
        details = (
            f"[bold cyan]Başlık:[/bold cyan] {movie.title or '-'} "
            f"([dim]{movie.original_title or '-'}[/dim])\n"
            f"[bold cyan]Puan (IMDb):[/bold cyan] [gold1]{movie.rating or '-'}[/gold1] ({movie.vote_count or '-'} oy) | "
            f"[bold cyan]Yıl:[/bold cyan] {movie.release_date or '-'} | "
            f"[bold cyan]Süre:[/bold cyan] {movie.runtime_minutes or '-'} dk\n"
            f"[bold cyan]Türler:[/bold cyan] {genres}\n"
            f"[bold cyan]Ülke:[/bold cyan] {movie.country or '-'} | "
            f"[bold cyan]IMDb ID:[/bold cyan] {movie.imdb_id or '-'}\n"
            f"[bold cyan]Oyuncular:[/bold cyan] {actors}\n"
            f"[bold cyan]Afiş:[/bold cyan] [dim cyan]{movie.poster_url or '-'}[/dim cyan]\n\n"
            f"[bold white]Özet:[/bold white]\n{movie.description or 'Açıklama bulunamadı.'}"
        )
        konsol.print(Panel(details, title=f"[bold green]Film: {movie.title}[/bold green]", border_style="green", box=box.ROUNDED))

    async def display_series_info_and_select_episode(self, plugin: PluginBase, series: SeriesInfo):
        details = (
            f"[bold cyan]Dizi Adı:[/bold cyan] {series.title or '-'}\n"
            f"[bold cyan]Puan:[/bold cyan] [gold1]{series.rating or '-'}[/gold1] | "
            f"[bold cyan]Yıl:[/bold cyan] {series.year or '-'} | "
            f"[bold cyan]Türler:[/bold cyan] {series.tags or '-'}\n"
            f"[bold cyan]Oyuncular:[/bold cyan] {series.actors or '-'}\n"
            f"[bold cyan]Afiş:[/bold cyan] [dim cyan]{series.poster or '-'}[/dim cyan]\n\n"
            f"[bold white]Özet:[/bold white]\n{series.description or 'Açıklama bulunamadı.'}"
        )
        konsol.print(Panel(details, title=f"[bold green]Dizi: {series.title}[/bold green]", border_style="green", box=box.ROUNDED))

        # Bölümleri topla (Dizibox: series.episodes, Dizilla: series.seasons)
        all_episodes: List[Episode] = []
        if series.episodes:
            all_episodes.extend(series.episodes)
        elif series.seasons and isinstance(series.seasons, dict):
            for s_num, eps in sorted(series.seasons.items(), key=lambda x: str(x[0])):
                if isinstance(eps, list):
                    all_episodes.extend(eps)

        if not all_episodes:
            konsol.print("[yellow]Bu diziye ait listelenmiş bölüm bulunamadı.[/yellow]")
            if Confirm.ask("Yine de dizi ana URL'si üzerinden video linki aransın mı?", default=False):
                await self.action_load_links(plugin, series.url or "", content_title=series.title or "Dizi")
            return

        self.print_banner(f"Mevcut Bölümler ({len(all_episodes)} Bölüm)")
        ep_table = Table(box=box.ROUNDED, header_style="bold cyan")
        ep_table.add_column("#", style="dim", width=4, justify="center")
        ep_table.add_column("Sezon", width=8, justify="center")
        ep_table.add_column("Bölüm", width=8, justify="center")
        ep_table.add_column("Bölüm Başlığı", style="bold white")
        ep_table.add_column("URL", style="dim cyan")

        for idx, ep in enumerate(all_episodes, 1):
            s_val = str(ep.season if ep.season is not None else (ep.season_number or "-"))
            e_val = str(ep.episode if ep.episode is not None else (ep.episode_number or "-"))
            ep_table.add_row(str(idx), f"{s_val}. Sezon", f"{e_val}. Bölüm", ep.title or "-", ep.url or "-")

        konsol.print(ep_table)
        konsol.print("[dim]Linklerini çıkarmak istediğiniz bölümün numarası (1-N) veya 'b' (Geri)[/dim]")

        secim = Prompt.ask("[bold cyan]İzlenecek Bölüm No[/bold cyan]", default="1").strip()
        if secim.lower() in ("b", "q", "0", ""):
            return

        if not secim.isdigit() or not (1 <= int(secim) <= len(all_episodes)):
            konsol.print("[red]Geçersiz bölüm numarası.[/red]")
            return

        selected_ep = all_episodes[int(secim) - 1]
        ep_label = f"{series.title} - S{selected_ep.season}E{selected_ep.episode}"
        konsol.print(f"[bold green]Seçildi:[/bold green] {ep_label} ([cyan]{selected_ep.url}[/cyan])")
        await self.action_load_links(plugin, selected_ep.url or "", content_title=ep_label)

    # =========================================================================
    # 5. VİDEO LİNKLERİ (LOAD_LINKS) & EXTRACTOR & OYNATMA
    # =========================================================================

    async def action_load_links(self, plugin: PluginBase, url: str, content_title: str = ""):
        """load_links çağırır, çıkan embed linklerini Extractor'larla eşleştirir ve oynatma seçeneği sunar."""
        self.print_banner(f"Video Linkleri Çekiliyor: {plugin.name}")
        konsol.print(f"[dim cyan]{url}[/dim cyan]\n")

        with konsol.status("[bold green]Video oynatıcı/embed linkleri taranıyor...[/bold green]"):
            try:
                raw_links = await plugin.load_links(url)
            except Exception as e:
                konsol.print(f"[bold red]load_links hatası:[/bold red] {e}")
                konsol.print(f"[dim]{traceback.format_exc()}[/dim]")
                return

        if not raw_links:
            konsol.print("[yellow]Sayfada hiçbir video/iframe linki bulunamadı.[/yellow]")
            return

        # Linkleri normalize et
        parsed_links = []
        for item in raw_links:
            if isinstance(item, ExtractResult):
                parsed_links.append({
                    "name": item.name or "Varsayılan",
                    "url": item.url,
                    "referer": item.referer or url,
                    "headers": item.headers or {},
                    "extract_obj": item,
                })
            elif isinstance(item, str):
                parsed_links.append({
                    "name": "Iframe/Embed",
                    "url": item,
                    "referer": url,
                    "headers": {},
                    "extract_obj": None,
                })
            elif isinstance(item, dict):
                parsed_links.append({
                    "name": item.get("name", "Bilinmiyor"),
                    "url": item.get("url", ""),
                    "referer": item.get("referer", url),
                    "headers": item.get("headers", {}),
                    "extract_obj": None,
                })

        self.print_banner(f"Bulunan Kaynaklar & Extractor Eşleşmeleri ({len(parsed_links)} Adet)")
        table = Table(box=box.ROUNDED, header_style="bold cyan")
        table.add_column("#", style="dim", width=4, justify="center")
        table.add_column("Kaynak Adı", style="bold white", width=16)
        table.add_column("Eşleşen Extractor", width=22)
        table.add_column("Embed / Video Linki", style="dim cyan")

        for idx, item in enumerate(parsed_links, 1):
            ext = self.extractor_mgr.find_extractor(item["url"])
            item["extractor"] = ext
            if ext:
                ext_label = getattr(ext, "get_source_label", lambda u: ext.name)(item["url"])
                ext_col = f"[bold green][+] {ext_label}[/bold green]"
            else:
                ext_col = "[dim yellow]Extractor Yok (Direkt)[/dim yellow]"
            table.add_row(str(idx), item["name"], ext_col, item["url"])

        konsol.print(table)
        konsol.print("[dim]Çözümlemek (Extract) ve Oynatmak istediğiniz numara (1-N) veya 'b' (Geri)[/dim]")

        secim = Prompt.ask("[bold cyan]İşlem yapılacak link no[/bold cyan]", default="1").strip()
        if secim.lower() in ("b", "q", "0", ""):
            return

        if not secim.isdigit() or not (1 <= int(secim) <= len(parsed_links)):
            konsol.print("[red]Geçersiz seçim.[/red]")
            return

        selected = parsed_links[int(secim) - 1]
        await self.execute_extraction_and_playback(selected, plugin, content_title)

    async def execute_extraction_and_playback(
        self, link_data: Dict[str, Any], plugin: PluginBase, content_title: str = ""
    ):
        """Seçilen linki extractor ile çözer ve MPV ile oynatır."""
        extractor: Optional[ExtractorBase] = link_data.get("extractor")
        raw_url = link_data["url"]
        referer = link_data.get("referer", "")
        headers = link_data.get("headers", {})

        self.print_banner(f"Çözümleme (Extraction): {link_data['name']}")
        konsol.print(f"[bold]Hedef URL:[/bold] [cyan]{raw_url}[/cyan]")
        konsol.print(f"[bold]Referer:[/bold] [dim]{referer or '-'}[/dim]")
        konsol.print(f"[bold]Extractor:[/bold] {extractor.name if extractor else 'Bulunamadı'}\n")

        final_extract_result: Optional[ExtractResult] = None

        if extractor:
            with konsol.status(f"[bold green]'{extractor.name}' akışı çözümlüyor...[/bold green]"):
                try:
                    final_extract_result = await extractor.extract(raw_url, referer=referer)
                except Exception as e:
                    konsol.print(f"[bold red]Extractor hatası:[/bold red] {e}")
                    konsol.print(f"[dim]{traceback.format_exc()}[/dim]")
                    return
                finally:
                    if hasattr(extractor, "close"):
                        await extractor.close()
        else:
            # Extractor yoksa ve zaten ExtractResult ise
            if link_data.get("extract_obj"):
                final_extract_result = link_data["extract_obj"]
            else:
                final_extract_result = ExtractResult(
                    name=link_data["name"],
                    url=raw_url,
                    referer=referer,
                    headers=headers,
                )

        if not final_extract_result or not final_extract_result.url:
            konsol.print("[bold red]Akış linki çözümlenemedi (Boş URL)![/bold red]")
            return

        # Çözümleme Sonucu Paneli
        subtitles_str = ", ".join(f"{s.name}: {s.url}" for s in final_extract_result.subtitles) if final_extract_result.subtitles else "Yok"
        res_info = (
            f"[bold green]Çözümlenen Akış (Stream URL):[/bold green]\n[cyan]{final_extract_result.url}[/cyan]\n\n"
            f"[bold green]Kullanılacak Referer:[/bold green] {final_extract_result.referer or '-'}\n"
            f"[bold green]Özel Başlıklar (Headers):[/bold green] {final_extract_result.headers or '-'}\n"
            f"[bold green]Altyazılar:[/bold green] {subtitles_str}"
        )
        konsol.print(Panel(res_info, title="[bold gold1]Akış Hazır[/bold gold1]", border_style="gold1", box=box.ROUNDED))

        # Oynatma Sorusu
        if Confirm.ask("\n[bold cyan]Bu akışı MPV / Oynatıcı ile başlatmak istiyor musunuz?[/bold cyan]", default=True):
            # Medya Başlığını Dinamik Olarak Ayarla
            play_title = f"{plugin.name}"
            if content_title:
                play_title += f" | {content_title}"
            if final_extract_result.name:
                play_title += f" | {final_extract_result.name}"

            self.media_mgr.set_title(play_title)
            if final_extract_result.headers:
                self.media_mgr.set_headers(final_extract_result.headers)
            if final_extract_result.referer:
                self.media_mgr.set_headers({"Referer": final_extract_result.referer})

            konsol.print(f"[bold green]Oynatıcı başlatılıyor:[/bold green] [white]{play_title}[/white]")
            try:
                self.media_mgr.play_media(final_extract_result)
            except Exception as e:
                konsol.print(f"[bold red]Oynatma sırasında hata:[/bold red] {e}")

    # =========================================================================
    # 6. SİSTEM GENEL BAKIŞI VE DOĞRUDAN URL TESTİ
    # =========================================================================

    def menu_show_system_overview(self):
        """Yüklü tüm eklenti ve extractor'ların tablosunu gösterir."""
        self.print_banner("Sistem Genel Özeti")

        # Eklentiler Tablosu
        p_table = Table(title="Yüklü Eklentiler (Plugins)", box=box.ROUNDED, header_style="bold green")
        p_table.add_column("Eklenti", style="bold white")
        p_table.add_column("Dil", width=6, justify="center")
        p_table.add_column("Ana URL", style="cyan")
        p_table.add_column("Kategori Sayısı", width=16, justify="center")
        p_table.add_column("Açıklama", style="dim")

        for name, p in sorted(self.plugins.items()):
            cat_count = len(getattr(p, "main_page", {}))
            p_table.add_row(name, getattr(p, "language", "-"), getattr(p, "main_url", "-"), str(cat_count), getattr(p, "description", "-")[:40] + "...")

        konsol.print(p_table)
        konsol.print()

        # Extractor'lar Tablosu
        e_table = Table(title="Yüklü Çıkarıcılar (Extractors)", box=box.ROUNDED, header_style="bold gold1")
        e_table.add_column("Extractor Adı", style="bold white")
        e_table.add_column("Hedef / Tanımlı URL Deseni", style="cyan")

        for ext_cls in self.extractor_mgr.extractors:
            try:
                instance = ext_cls()
                e_table.add_row(instance.name, instance.main_url)
            except Exception:
                e_table.add_row(str(ext_cls), "Yüklenemedi")

        konsol.print(e_table)
        konsol.print()
        Prompt.ask("[dim]Devam etmek için Enter'a basın[/dim]", default="")

    async def menu_direct_url_test(self):
        """Kullanıcının elindeki herhangi bir URL'yi doğrudan test etmesini sağlar."""
        self.print_banner("Doğrudan URL Test Aracı")
        url = Prompt.ask("[bold cyan]Test edilecek URL'yi yapıştırın[/bold cyan]").strip()
        if not url:
            return

        # Otomatik eklenti tespiti dene
        detected_plugin: Optional[PluginBase] = None
        for p in self.plugins.values():
            if getattr(p, "main_url", "") and p.main_url in url:
                detected_plugin = p
                break

        if detected_plugin:
            konsol.print(f"[green]Otomatik tespit edilen eklenti:[/green] [bold]{detected_plugin.name}[/bold]")
        else:
            konsol.print("[yellow]URL herhangi bir eklentinin main_url'si ile tam eşleşmedi.[/yellow]")
            p_names = self.plugin_mgr.get_plugin_names()
            p_choice = Prompt.ask(
                "[bold cyan]Hangi eklenti ile işlensin?[/bold cyan]",
                choices=p_names + ["Extractor Doğrudan"],
                default=p_names[0],
            )
            if p_choice != "Extractor Doğrudan":
                detected_plugin = self.plugins[p_choice]

        konsol.print("\nNe yapmak istiyorsunuz?")
        konsol.print(" [1] load_item (İçerik/Film/Dizi Detayı Çek)")
        konsol.print(" [2] load_links (Sayfadaki Video/Embed Linklerini Çöz)")
        konsol.print(" [3] Extractor Testi (URL'yi doğrudan Extractor ile çöz ve oynat)")
        konsol.print(" [0] İptal")

        islem = Prompt.ask("[bold cyan]Seçiminiz[/bold cyan]", choices=["1", "2", "3", "0"], default="1")

        if islem == "1" and detected_plugin:
            await self.action_load_item(detected_plugin, url)
        elif islem == "2" and detected_plugin:
            await self.action_load_links(detected_plugin, url)
        elif islem == "3":
            ext = self.extractor_mgr.find_extractor(url)
            link_data = {
                "name": "Direkt URL",
                "url": url,
                "referer": "",
                "headers": {},
                "extractor": ext,
                "extract_obj": None,
            }
            dummy_plugin = detected_plugin or PluginBase
            await self.execute_extraction_and_playback(link_data, dummy_plugin, content_title="Doğrudan URL")


# =========================================================================
# GİRİŞ NOKTASI (ENTRYPOINT)
# =========================================================================

async def main():
    runner = InteractiveTestRunner()
    try:
        await runner.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        konsol.print("\n[yellow]Kullanıcı tarafından durduruldu. Oturumlar kapatılıyor...[/yellow]")
        await runner.plugin_mgr.close_plugins()
        konsol.print("[green]Temizlendi ve çıkıldı.[/green]\n")
    except Exception as e:
        konsol.print(f"\n[bold red]Beklenmeyen bir hata oluştu:[/bold red] {e}")
        konsol.print(f"[dim]{traceback.format_exc()}[/dim]")
        await runner.plugin_mgr.close_plugins()


if __name__ == "__main__":
    asyncio.run(main())
