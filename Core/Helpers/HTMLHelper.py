from selectolax.parser import HTMLParser, Node
import re
import os
import tempfile
import httpx
from curl_cffi.requests import AsyncSession
from typing import Optional, Dict

# Playwright İSTEĞE BAĞLIDIR. Yalnızca Cloudflare Turnstile challenge tespit
# edildiğinde tarayıcı açılır; tarayıcı binary'si de Dockerfile'da yoktur
# (~400 MB, `playwright install chromium` gerekir).
#
# İki nedenle import burada yutuluyor:
#   1) Bu dosya Core/Helpers/__init__.py üzerinden HER yerde import ediliyor.
#      Playwright kurulu değilse `import api.app` çöker ve container hiç
#      açılmaz — oysa asıl işlev (düz HTTP çekim) çalışabiliyor.
#   2) Sunucuda ekran/headless ortam yok; `headless=False` ile açılan tarayıcı
#      zaten başarısız olacak. Yükleme denemesini her seferinde tekrarlamak
#      yerine bir kez öğrenip yoluna devam etmek gerekir.
try:
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    PLAYWRIGHT_KURULU = True
except ImportError:
    async_playwright = None
    Stealth = None
    PLAYWRIGHT_KURULU = False

class HTMLHelper:
    """
    Selectolax ile HTML parsing işlemlerini temiz, kısa ve okunabilir hale getiren yardımcı sınıf.
    """

    # Cloudflare/Turnstile challenge işaretleri.
    # NOT: "challenge-platform" normal sayfalarda da CF'nin `/cdn-cgi/challenge-platform/
    # scripts/jsd/main.js` etiketi olarak geçtiği için bilerek kullanılmıyor.
    _CF_ISARETLER = (
        "Just a moment",
        "cf_chl_opt",
        "challenge-error-text",
        "cf-browser-verification",
        "Attention Required! | Cloudflare",
    )

    @staticmethod
    def _cf_challenge_mi(html: str, status: int = 200) -> bool:
        """Dönen içerik Cloudflare doğrulama sayfası mı?"""
        if status in (403, 503) and len(html) < 4000:
            return True
        return any(isaret in html for isaret in HTMLHelper._CF_ISARETLER)

    @staticmethod
    async def _hizli_get(url: str, headers: Optional[Dict[str, str]] = None) -> tuple[str, int]:
        """Tarayıcısız çekim: httpx -> curl_cffi (TLS parmak izi taklidi)."""
        istek_basliklari = dict(headers or {})
        istek_basliklari.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )

        # 1) httpx
        try:
            async with httpx.AsyncClient(
                headers=istek_basliklari, timeout=30, follow_redirects=True
            ) as client:
                yanit = await client.get(url)
                return yanit.text or "", yanit.status_code
        except Exception:
            pass

        # 2) curl_cffi — gerçek tarayıcı TLS/basamak izi
        try:
            async with AsyncSession(impersonate="chrome124") as oturum:
                yanit = await oturum.get(url, headers=istek_basliklari, timeout=30)
                return yanit.text or "", yanit.status_code
        except Exception:
            return "", 0

    @staticmethod
    async def fetch_cf(url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Sayfayı çeker.

        Sıra: (1) tarayıcısız hızlı çekim → (2) yalnızca Cloudflare challenge
        görülürse Playwright. Böylece normal isteklerde tarayıcı açılmaz ve
        Windows'ta alt süreç açılamayan ortamlarda (örn. uvicorn) hata
        oluşmaz; challenge yoksa tarayıcıya hiç gidilmez.
        """
        html, status = await HTMLHelper._hizli_get(url, headers)
        if html and not HTMLHelper._cf_challenge_mi(html, status):
            return html

        # Challenge var (ya da düz çekim tamamen başarısız) -> tarayıcı dene
        if not PLAYWRIGHT_KURULU:
            # Playwright yok: düz içerik elimizdeyse onu döndür, yoksa
            # challenge çözülemez. Tarayıcıyı hiç denemek anlamsız.
            if html:
                print("[!] HTMLHelper: Playwright kurulu değil, düz HTTP yanıtı döndürülüyor.")
                return html
            raise RuntimeError(
                "Cloudflare challenge var ve Playwright kurulu değil. "
                "Çözüm için: pip install playwright playwright-stealth "
                "&& playwright install chromium"
            )

        try:
            return await HTMLHelper._playwright_get(url, headers)
        except Exception as hata:
            if html:
                # Tarayıcı açılamadı ama düz içerik elimizde: onu kullan
                print(f"[!] HTMLHelper: Playwright açılamadı ({hata!r}), düz HTTP yanıtı döndürülüyor.")
                return html
            raise

    @staticmethod
    async def _playwright_get(url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Cloudflare Turnstile aşma (yalnızca challenge tespit edilirse çağrılır)."""
        async with async_playwright() as p:
            # Otomasyon tespit bayraklarını ezen Chromium argümanları
            args = [
                "--headless=new",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-browser-side-navigation",
                "--disable-gpu",
                "--window-size=1920,1080",
            ]

            user_data_dir = os.path.join(tempfile.gettempdir(), "cf_browser_session")
            
            # launch yerine persistent context: gerçek kullanıcı profili gibi davranır
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,  # Turnstile tespiti için ilk etapta pencereyi açık tutun
                args=args,
                user_agent=(
                    headers.get("User-Agent") if headers and "User-Agent" in headers
                    else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="tr-TR",
                timezone_id="Europe/Istanbul"
            )

            page = context.pages[0] if context.pages else await context.new_page()

            # navigator.webdriver bayrağını kesin olarak gizleme
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            # Turnstile veya Cloudflare bekleme döngüsü
            for _ in range(25):
                title = await page.title()
                content = await page.content()

                # Başlık "Just a moment..." değilse ve challenge elementi yoksa geçilmiştir
                if "Just a moment" not in title and "challenge-error-text" not in content and "cf_chl_opt" not in content:
                    await context.close()
                    return content

                # Eğer Turnstile iframe'i ekrandaysa checkbox'a tıklamayı dene
                try:
                    for frame in page.frames:
                        if "challenges.cloudflare.com" in frame.url:
                            checkbox = await frame.query_selector("input[type=checkbox], .ctp-checkbox-label, #challenge-stage")
                            if checkbox:
                                box = await checkbox.bounding_box()
                                if box:
                                    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                    break
                except Exception:
                    pass

                await page.wait_for_timeout(1000)

            await context.close()
            raise Exception("Cloudflare Turnstile aşılamadı (Zaman aşımı).")

    def __init__(self, html: str):
        self.parser = HTMLParser(html)
        self.html   = html

    # ========================
    # TEMEL SELECTOR İŞLEMLERİ
    # ========================

    def _target(self, element: Node | None) -> Node | HTMLParser:
        """İşlem yapılacak temel elementi döndürür."""
        return element if element is not None else self.parser

    def select(self, selector: str, element: Node | None = None) -> list[Node]:
        """CSS selector ile tüm eşleşen elementleri döndür."""
        return self._target(element).css(selector)

    def select_first(self, selector: str | None, element: Node | None = None) -> Node | None:
        """CSS selector ile ilk eşleşen elementi döndür."""
        if not selector:
            return element

        return self._target(element).css_first(selector)

    def select_text(self, selector: str | None = None, element: Node | None = None, strip: bool = True) -> str | None:
        """CSS selector ile element bul ve text içeriğini döndür."""
        el = self.select_first(selector, element)
        if not el:
            return None

        val = el.text(strip=strip)
        return val if val else None

    def select_attr(self, selector: str | None, attr: str, element: Node | None = None) -> str | None:
        """CSS selector ile element bul ve attribute değerini döndür."""
        el = self.select_first(selector, element)
        return el.attrs.get(attr) if el else None

    def select_all_text(self, selector: str, element: Node | None = None, strip: bool = True) -> list[str]:
        """CSS selector ile tüm eşleşen elementlerin text içeriklerini döndür."""
        return [
            txt for el in self.select(selector, element)
                if (txt := el.text(strip=strip))
        ]

    def select_all_attr(self, selector: str, attr: str, element: Node | None = None) -> list[str]:
        """CSS selector ile tüm eşleşen elementlerin attribute değerlerini döndür."""
        return [
            val for el in self.select(selector, element)
                if (val := el.attrs.get(attr))
        ]

    # ----------------------------------------------

    def select_poster(self, selector: str = "img", element: Node | None = None) -> str | None:
        """Poster URL'sini çıkar. Önce data-src, sonra src dener."""
        el = self.select_first(selector, element)
        if not el:
            return None

        return el.attrs.get("data-src") or el.attrs.get("src")

    # ========================
    # REGEX İŞLEMLERİ
    # ========================

    def _source(self, target: str | int | None) -> str:
        """Regex için kaynak metni döndürür."""
        return target if isinstance(target, str) else self.html

    def _flags(self, target: str | int | None, flags: int) -> int:
        """Regex flags değerini döndürür."""
        return target if isinstance(target, int) else flags

    def regex_first(self, pattern: str, target: str | int | None = None, flags: int = 0) -> str | None:
        """Regex ile arama yap, ilk grubu döndür (grup yoksa tamamını)."""
        match = re.search(pattern, self._source(target), self._flags(target, flags))
        if not match:
            return None

        try:
            return match.group(1)
        except IndexError:
            return match.group(0)

    def regex_all(self, pattern: str, target: str | int | None = None, flags: int = 0) -> list[str]:
        """Regex ile tüm eşleşmeleri döndür."""
        return re.findall(pattern, self._source(target), self._flags(target, flags))

    def regex_replace(self, pattern: str, repl: str, target: str | int | None = None, flags: int = 0) -> str:
        """Regex ile replace yap."""
        return re.sub(pattern, repl, self._source(target), flags)

    # ========================
    # ÖZEL AYIKLAYICILAR
    # ========================

    @staticmethod
    def extract_season_episode(text: str) -> tuple[int | None, int | None]:
        """Metin içinden sezon ve bölüm numarasını çıkar."""
        # S01E05 formatı
        if m := re.search(r"[Ss](\d+)[Ee](\d+)", text):
            return int(m.group(1)), int(m.group(2))

        # Ayrı ayrı ara
        s = re.search(r"(\d+)\.\s*[Ss]ezon|[Ss]ezon[- ]?(\d+)|-(\d+)-sezon", text, re.I)
        e = re.search(r"(\d+)\.\s*[Bb]ölüm|[Bb]olum[- ]?(\d+)|-(\d+)-bolum|[Ee](\d+)", text, re.I)

        # İlk bulunan grubu al (None değilse)
        s_val = next((int(g) for g in s.groups() if g), None) if s else None
        e_val = next((int(g) for g in e.groups() if g), None) if e else None

        return s_val, e_val

    def extract_year(self, *selectors: str, pattern: str = r"(\d{4})") -> int | None:
        """Birden fazla selector veya regex ile yıl bilgisini çıkar."""
        for selector in selectors:
            if text := self.select_text(selector):
                if m := re.search(r"(\d{4})", text):
                    return int(m.group(1))

        val = self.regex_first(pattern)
        return int(val) if val and val.isdigit() else None