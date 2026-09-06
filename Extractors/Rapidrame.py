import base64
import json
import random
import re
import string
import urllib.parse
from typing import Any, Dict, List, Optional

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle
from Core.Helpers import debug_log, is_debug



class JsUnpacker:
    """Dean Edwards p.a.c.k.e.r şifreli JavaScript kodlarını çözer."""

    @staticmethod
    def unpack(packed: str) -> str:
        pattern = r"\}\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
        match = re.search(pattern, packed, re.DOTALL)
        if not match:
            pattern_alt = r"eval\(function\(p,a,c,k,e,[rd]\)\{.*return p\}\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
            match = re.search(pattern_alt, packed, re.DOTALL)
            if not match:
                return packed

        payload, radix, count, symtab = match.groups()
        radix = int(radix)
        count = int(count)
        words = symtab.split("|")

        def base_encode(num: int, b: int) -> str:
            chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if num == 0:
                return chars[0]
            res = []
            while num > 0:
                res.append(chars[num % b])
                num //= b
            return "".join(reversed(res))

        lookup = {}
        for i in range(count):
            key = base_encode(i, radix)
            lookup[key] = words[i] if i < len(words) and words[i] else key

        def replace_word(m):
            word = m.group(0)
            return lookup.get(word, word)

        return re.sub(r"\b\w+\b", replace_word, payload)


def execute_dc_pipeline(func_code: str, parts: list[str]) -> str:
    """Rapidrame ve HDFilmCehennemi dahili player'larındaki (dc_...) dinamik akış çözümleyiciyi yürütür."""
    result = "".join(parts)

    body_match = re.search(r'let result=value;(.*?)let unmix=', func_code, re.DOTALL)
    if not body_match:
        raise ValueError("Dönüştürme gövdesi bulunamadı")

    body = body_match.group(1)

    op_matches = re.finditer(r'result\s*=\s*(.*?);\s*(?=result\s*=|let\s+unmix|\Z)', body, re.DOTALL)

    for m in op_matches:
        expr = m.group(1).strip()
        if "reverse()" in expr:
            result = result[::-1]
        elif "replace" in expr:
            shift_match = re.search(r'\(o-base\+(\d+)\)%26\+base', expr)
            if shift_match:
                shift = int(shift_match.group(1))

                def rot(c, s=shift):
                    o = ord(c)
                    base = 65 if o <= 90 else 97
                    return chr((o - base + s) % 26 + base)

                result = re.sub(r"[a-zA-Z]", lambda ch: rot(ch.group(0)), result)
        elif "atob" in expr:
            result_bytes = result.encode("latin-1")
            result = base64.b64decode(result_bytes).decode("latin-1")

    unmix_match = re.search(r'\((\d+)%\(i\+(\d+)\)\)', func_code)
    if not unmix_match:
        raise ValueError("Unmix anahtar parametreleri bulunamadı")

    seed = int(unmix_match.group(1))
    offset = int(unmix_match.group(2))

    unmix = []
    for i, c in enumerate(result):
        char_code = ord(c)
        char_code = ((char_code - (seed % (i + offset))) % 256 + 256) % 256
        unmix.append(chr(char_code))

    return "".join(unmix)


def decode_close_obfuscation(parts: list[str], key1: str, key2: str) -> str:
    """hdfilmcehennemi.mobi closeplayer obfuscasyonunu parametrik olarak çözer.
    Her istekte fonksiyon/degisken/anahtar isimleri yeniden üretildiği için
    anahtarlar çağrı yerinden dinamik olarak çıkarılır.

    Algoritma: key1'den seed türet → ters sıra key2 op'ları → Fisher-Yates
    karıştırma tersi → XOR.
    """
    xkqus = "".join(parts)

    rkt1 = 0
    x9k2 = 0
    for vpzl, ch in enumerate(key1):
        g80k = ord(ch)
        rkt1 = (rkt1 * 31 + g80k) % 251
        x9k2 = (x9k2 ^ (g80k + vpzl)) & 255
    fjx = (rkt1 + x9k2) % 256
    ywcif = (rkt1 % 13) + 3
    s47m = ((rkt1 * 256 + x9k2) % 65521) + 1

    # key2 ters sıra uygulama: 'b' → atob, 'v' → reverse, diğer → Caesar
    for ch in reversed(key2):
        if ch == "b":
            xkqus = base64.b64decode(xkqus).decode("latin-1")
        elif ch == "v":
            xkqus = xkqus[::-1]
        else:
            uio = (26 - ((ord(ch) - 64) % 26)) % 26
            xkqus = re.sub(
                r"[a-zA-Z]",
                lambda m: chr(
                    (ord(m.group(0))
                     - (65 if ord(m.group(0)) <= 90 else 97)
                     + uio)
                    % 26
                    + (65 if ord(m.group(0)) <= 90 else 97)
                ),
                xkqus,
            )

    tuu = len(xkqus)
    ywa85 = [0] * tuu
    for vpzl in range(tuu - 1, 0, -1):
        s47m = (s47m * 75 + 74) % 65537
        ywa85[vpzl] = s47m % (vpzl + 1)
    isct = list(xkqus)
    for vpzl in range(1, tuu):
        z0g9r = ywa85[vpzl]
        ak3 = isct[vpzl]
        isct[vpzl] = isct[z0g9r]
        isct[z0g9r] = ak3
    xkqus = "".join(isct)

    aansx = fjx
    u3uv_chars = []
    for vpzl in range(len(xkqus)):
        g80k = ord(xkqus[vpzl])
        aansx = (aansx + ywcif) % 256
        u3uv_chars.append(chr(g80k ^ aansx))
        aansx = (aansx + g80k) % 256
    return "".join(u3uv_chars)


def find_close_decoder(unpacked_code: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Close iframe'inin obfuscasyon çağrısını bulur: var X = FN(["..."]) gibi.
    (FN, parts_str, var_name) döndürür veya bulamazsa (None, None, None).
    """
    pattern = r"var\s+(\w+)\s*=\s*(\w+)\s*\(\s*(\[[^\]]+\])\s*\)"
    m = re.search(pattern, unpacked_code)
    if not m:
        return None, None, None
    return m.group(2), m.group(3), m.group(1)



def extract_close_keys(unpacked_code: str, fn_name: str) -> tuple[Optional[str], Optional[str]]:
    """Fonksiyon gövdesinin içinden iki anahtar string'i çeker.
    Yapı: function FN(arg) { var X = "..."; var Y = "..."; ... }
    İlk iki string literal atanımı alınır.
    """
    body_match = re.search(
        r'function\s+' + re.escape(fn_name) + r'\s*\([^)]*\)\s*\{(.*?)\n\}',
        unpacked_code,
        re.DOTALL,
    )
    if not body_match:
        return None, None
    body = body_match.group(1)
    assigns = re.findall(r'''var\s+\w+\s*=\s*["']([^"']+)["']''', body)
    if len(assigns) < 2:
        return None, None
    return assigns[0], assigns[1]


class RapidrameExtractor(ExtractorBase):
    """
    HDFilmCehennemi & Rapidrame Video Barındırıcı Çözücüsü.
    Desteklenenler: hdfilmcehennemi.mobi (closeplayer + rplayer), rapidrame,
    cehennempass.pw, dahili player sekmeleri (playerr, rplayer).
    """

    name = "Rapidrame"
    main_url = "https://hdfilmcehennemi.mobi"
    domains = [
        "rapidrame",
        "hdfilmcehennemi.mobi",
        "hdfilmcehennemi.nl",
        "hdfilmcehennemi.cx",
        "cehennempass.pw",
        "playerr",
        "rplayer",
    ]

    def __init__(self):
        super().__init__()

    def can_handle_url(self, url: str) -> bool:
        """Taban sınıftaki tekil main_url kontrolünü çoklu domain desteği ile genişletir."""
        return any(domain in url for domain in self.domains)

    async def _fetch_page(self, url: str, headers: dict) -> str:
        """Embed/player sayfasını çeker. httpx → cloudscraper → curl_cffi sırasıyla dener.
        CF v3 challenge gibi zor korumalar için curl_cffi (TLS fingerprint) gerekiyor.
        """
        import asyncio
        _log = debug_log

        _log(f"[{self.name}] _fetch_page START url={url[:100]}")
        text = ""
        try:
            resp = await self.client.get(url, headers=headers, follow_redirects=True)
            text = resp.text or ""
            _log(f"[{self.name}] httpx status={resp.status_code} len={len(text)} markers: wbj9e={'wbj9e' in text} dc_={'function dc_' in text} player={'var player' in text} tracks={'tracks:' in text}")
            _log(f"[{self.name}] httpx first 500: {text[:500]!r}")
        except Exception as e:
            _log(f"[{self.name}] httpx exception: {e!r}")

        if text and len(text) > 200 and ("wbj9e" in text or "function dc_" in text or "var player" in text or "tracks:" in text):
            _log(f"[{self.name}] httpx yeterli, dönüyoruz")
            return text

        # 2. adım: cloudscraper (CF v1/v2 için yeterli)
        loop = asyncio.get_event_loop()
        try:
            cs_text = await loop.run_in_executor(
                None,
                lambda: self.cloudscraper.get(url, headers=headers, timeout=20).text,
            )
            _log(f"[{self.name}] cloudscraper len={len(cs_text)} has_wbj9e={'wbj9e' in cs_text}")
            if cs_text and len(cs_text) > 200 and ("wbj9e" in cs_text or "function dc_" in cs_text or "var player" in cs_text or "tracks:" in cs_text):
                return cs_text
            text = text or cs_text
        except Exception as e:
            _log(f"[{self.name}] cloudscraper exception: {e!r}")

        # 3. adım: curl_cffi (CF v3 / Turnstile için gerekli; TLS fingerprint taklidi)
        try:
            from curl_cffi.requests import Session as CffiSession
            def _do_cffi():
                with CffiSession(impersonate="chrome120") as s:
                    s.headers.update(headers)
                    r = s.get(url, timeout=20, allow_redirects=True)
                    return r.text
            cffi_text = await loop.run_in_executor(None, _do_cffi)
            _log(f"[{self.name}] curl_cffi len={len(cffi_text)} has_wbj9e={'wbj9e' in cffi_text}")
            if cffi_text and len(cffi_text) > 200:
                return cffi_text
        except Exception as e:
            _log(f"[{self.name}] curl_cffi exception: {e!r}")

        # Son çare olarak elimize geçen en iyi metni döndür
        _log(f"[{self.name}] _fetch_page END fallback text len={len(text)}")
        return text

    def get_source_label(self, url: str) -> str:
        """Picker için URL'den kısa, anlamlı bir kaynak etiketi üretir.
        Aynı extractor'a düşen farklı kaynakları (Close / Rapidrame / CehennemPass) ayırır.
        """
        if "cehennempass.pw" in url:
            return "CehennemPass"
        if "hdfilmcehennemi.mobi/video/embed/" in url:
            return "Close"
        if "rplayer/" in url or "playerr/" in url:
            return "Rapidrame"
        return self.name

    def _generate_random_cookie(self) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=16))

    async def _extract_cehennempass(self, url: str, referer: str) -> Optional[ExtractResult]:
        """CehennemPass download sayfasından video linklerini çıkarır."""
        video_id = url.split("/download/")[-1]
        if not video_id:
            return None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": f"https://cehennempass.pw/download/{video_id}",
            "X-Requested-With": "fetch",
            "authority": "cehennempass.pw",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        results = []
        for quality in ["high", "low"]:
            try:
                cookie = f"PHPSESSID={self._generate_random_cookie()}"
                resp = await self.client.post(
                    url="https://cehennempass.pw/process_quality_selection.php",
                    headers={**headers, "Cookie": cookie},
                    data={"video_id": video_id, "selected_quality": quality},
                    follow_redirects=True,
                )
                data = resp.json()
                video_url = data.get("download_link")
                if video_url:
                    video_url = video_url.replace(r"\/", "/")
                    quality_label = "Yüksek Kalite" if quality == "high" else "Düşük Kalite"
                    results.append({
                        "name": f"HDFilmCehennemi | CehennemPass ({quality_label})",
                        "url": video_url,
                        "referer": f"https://cehennempass.pw/download/{video_id}",
                        "headers": {
                            "User-Agent": headers["User-Agent"],
                            "Referer": f"https://cehennempass.pw/download/{video_id}",
                        },
                    })
            except Exception as e:
                print(f"[!] CehennemPass {quality} kalite hatası: {e}")

        if not results:
            return None

        r = results[0]
        return ExtractResult(
            name=r["name"],
            url=r["url"],
            referer=r["referer"],
            headers=r["headers"],
            subtitles=[],
        )

    async def extract(
        self, url: str, referer: Optional[str] = None, **kwargs: Any
    ) -> Optional[ExtractResult]:
        base_referer = referer or "https://www.hdfilmcehennemi.nl/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": base_referer,
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # CehennemPass download sayfası ise özel işleme
        if "cehennempass.pw/download/" in url:
            return await self._extract_cehennempass(url, base_referer)

        # Close iframe (hdfilmcehennemi.mobi/video/embed/...) kendi closeplayer sayfasını kullanır;
        # rapidrame_id parametresi burada Rapidrame playerr'ına değil, closeplayer içeriğine işaret eder.
        is_close = "hdfilmcehennemi.mobi/video/embed/" in url

        # rapidrame_id parametresi varsa playerr URL'sine dönüştür (Close hariç)
        if not is_close and "?rapidrame_id=" in url:
            rapidrame_id = url.split("?rapidrame_id=")[1].split("&")[0].strip()
            url = f"https://www.hdfilmcehennemi.nl/playerr/{rapidrame_id}/"
        elif "playerr/" in url and not url.endswith("/"):
            url += "/"
        elif "rplayer/" in url and not url.endswith("/"):
            url += "/"

        # 1. Aşama: Link bir ara sekme ise (/152613 gibi), içindeki asıl iframe'i al
        if not is_close and "video/embed" not in url and "playerr" not in url and "rplayer" not in url:
            try:
                resp = await self.client.get(url, headers=headers, follow_redirects=True)
                iframe_match = re.search(
                    r'<iframe[^>]+(?:data-src|src)=["\']([^"\']+)["\']', resp.text
                )
                if iframe_match:
                    url = self.fix_url(iframe_match.group(1))
                    if "?rapidrame_id=" in url and "hdfilmcehennemi.mobi/video/embed/" not in url:
                        rapidrame_id = url.split("?rapidrame_id=")[1].split("&")[0].strip()
                        url = f"https://www.hdfilmcehennemi.nl/playerr/{rapidrame_id}/"
                    elif ("playerr/" in url or "rplayer/" in url) and not url.endswith("/"):
                        url += "/"
                else:
                    return None
            except Exception as e:
                print(f"[!] {self.name} ara sekme çözümleme hatası ({url}): {e}")
                return None

        # 2. Aşama: Embed / Player sayfasına git
        embed_domain = urllib.parse.urlparse(url).netloc or "rapidrame.com"
        embed_headers = headers.copy()
        embed_headers["Referer"] = base_referer

        try:
            html_content = await self._fetch_page(url, embed_headers)

            # Dean Edwards Packer JS kontrolü ve açma
            # NOT: html_content (tüm HTML) üzerinde arama yapılır; unpacked_code sadece
            # dc_ pipeline'ı gibi eval-block içi kodlar için kullanılır. Close gibi
            # başka script bloklarında obfuscation yapan siteler için tüm HTML gerekli.
            unpacked_code = html_content
            if "eval(function(p,a,c,k,e," in html_content:
                eval_match = re.search(
                    r'eval\(function\(p,a,c,k,e,[rd]\)\{.*return p\}\(.*?\)\.split\(\'\|\'\)\)',
                    html_content,
                    re.DOTALL,
                )
                if eval_match:
                    unpacked_code = JsUnpacker.unpack(eval_match.group(0))
                else:
                    unpacked_code = JsUnpacker.unpack(html_content)

            # 3. Aşama: Akış (.m3u8 veya doğrudan video) linkini ayıkla
            stream_url = None

            # Metot 0: Close (hdfilmcehennemi.mobi) obfuscasyon çözümleyici
            # html_content üzerinde arama yapılır; unpacked_code sadece eval-block içindeki
            # kod için (dc_ pipeline), Close gibi başka script bloklarında gizlenen obfuscation'ı
            # kaçırmamak için tüm HTML'i taramak gerekiyor.
            fn_name, parts_str, var_name = find_close_decoder(html_content)
            if not fn_name:
                debug_log(f"[DEBUG {self.name}] Metot 0: call site bulunamadı")
                matches = list(re.finditer(r'var\s+\w+\s*=\s*\w+\s*\(\s*\[', unpacked_code))
                debug_log(f"[DEBUG {self.name}] var=X=Y([ pattern sayısı: {len(matches)}")
                # Tüm "var X = Y" atamalarını yaz (çağrı yerleri farklı biçimde olabilir)
                all_vars = list(re.finditer(r'var\s+(\w+)\s*=\s*(\w+)', unpacked_code))
                debug_log(f"[DEBUG {self.name}] toplam var ataması: {len(all_vars)}")
                for m in all_vars[:10]:
                    debug_log(f"[DEBUG {self.name}]   var {m.group(1)} = {m.group(2)}...")
                # Sayfada herhangi bir master.txt/master.m3u8 URL var mı?
                urls = re.findall(r'https?://[^\s\'"<>]+\.(?:m3u8|txt)', unpacked_code)
                debug_log(f"[DEBUG {self.name}] master URL'leri: {urls[:3]}")
                # Hash rate / contentUrl gibi JSON-LD URL'leri
                ld_urls = re.findall(r'"contentUrl"\s*:\s*"([^"]+)"', unpacked_code)
                debug_log(f"[DEBUG {self.name}] JSON-LD contentUrl: {ld_urls[:2]}")
                # Sayfayı diske kaydet debug için
                if is_debug():
                    try:
                        import os
                        os.makedirs(r"D:\Projeler\MovieAppNew\debug_dumps", exist_ok=True)
                        with open(rf"D:\Projeler\MovieAppNew\debug_dumps\close_{int(__import__('time').time())}.html", "w", encoding="utf-8") as f:
                            f.write(html_content)
                        debug_log(f"[DEBUG {self.name}] html kaydedildi")
                    except Exception as e:
                        debug_log(f"[DEBUG {self.name}] kaydetme hatası: {e}")
            debug_log(f"[DEBUG {self.name}] Metot 0: fn={fn_name} var={var_name} has_parts={parts_str is not None}")
            if fn_name and parts_str:
                try:
                    parts = json.loads(parts_str)
                except Exception:
                    try:
                        import ast
                        parts = ast.literal_eval(parts_str)
                    except Exception as e:
                        debug_log(f"[DEBUG {self.name}] parse parts başarısız: {e}")
                        parts = re.findall(r'["\']([a-zA-Z0-9+/=]+)["\']', parts_str)
                key1, key2 = extract_close_keys(html_content, fn_name)
                debug_log(f"[DEBUG {self.name}] extract_close_keys: key1={key1!r} key2={key2!r}")
                if key1 and key2:
                    try:
                        stream_url = decode_close_obfuscation(parts, key1, key2)
                        debug_log(f"[DEBUG {self.name}] close decoder OK: var={var_name} fn={fn_name} url={stream_url[:80]}")
                    except Exception as e:
                        debug_log(f"[!] {self.name} close decoder hatası: {e}")
                else:
                    debug_log(f"[DEBUG {self.name}] close decoder anahtarları bulunamadı (fn={fn_name})")

            # Metot A: Dinamik dc_ pipeline çözümleyici (playerr / rplayer)
            dc_func_match = re.search(r'function\s+(dc_[a-zA-Z0-9_]+)\s*\(', unpacked_code)
            if dc_func_match:
                func_name = dc_func_match.group(1)
                call_match = re.search(func_name + r'\s*\(\s*(\[.*?\])\s*\)', unpacked_code, re.DOTALL)
                if call_match:
                    try:
                        parts = json.loads(call_match.group(1))
                    except Exception:
                        parts = re.findall(r'["\']([a-zA-Z0-9+/=]+)["\']', call_match.group(1))

                    func_code_match = re.search(
                        r'(function\s+' + func_name + r'\(.*?return\s+unmix\s*\}?)',
                        unpacked_code,
                        re.DOTALL,
                    )
                    if func_code_match:
                        try:
                            stream_url = execute_dc_pipeline(func_code_match.group(1), parts)
                        except Exception as e:
                            print(f"[!] {self.name} dc_ pipeline çalıştırma hatası: {e}")

            # Metot B: file: "..." veya source: "..."
            if not stream_url:
                file_match = re.search(
                    r'(?:file|source|src)\s*:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
                    unpacked_code,
                )
                if file_match:
                    stream_url = file_match.group(1)

            # Metot C: JSON sources dizisi
            if not stream_url:
                sources_match = re.search(
                    r'sources\s*:\s*(\[.*?\])\s*(?:,|\n|;)', unpacked_code, re.DOTALL
                )
                if sources_match:
                    try:
                        sources = json.loads(sources_match.group(1))
                        if sources and isinstance(sources, list):
                            stream_url = sources[0].get("file")
                    except Exception:
                        pass

            # Metot D: HTML5 <source> etiketi
            if not stream_url:
                source_tag = re.search(
                    r'<source[^>]+src=["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
                    unpacked_code,
                )
                if source_tag:
                    stream_url = source_tag.group(1)

            # Metot E: Metin içerisindeki saf m3u8 adresi
            if not stream_url:
                raw_m3u8 = re.search(
                    r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', unpacked_code
                )
                if raw_m3u8:
                    stream_url = raw_m3u8.group(1)

            # Metot F: Base64 kodlu file_link
            if not stream_url:
                b64_match = re.search(r'file_link=\\"(.*?)\\"\;', unpacked_code)
                if b64_match:
                    try:
                        stream_url = base64.b64decode(b64_match.group(1)).decode("utf-8")
                    except Exception:
                        pass

            if not stream_url:
                return None

            # 4. Aşama: Altyazıları ayıkla
            subtitles: List[Subtitle] = []
            tracks_match = re.search(
                r'tracks\s*:\s*(\[.*?\])\s*(?:,|\n|;)', html_content, re.DOTALL
            )
            if tracks_match:
                try:
                    tracks = json.loads(tracks_match.group(1))
                    for t in tracks:
                        if t.get("kind") in ["captions", "subtitles"] and t.get("file"):
                            sub_path = t.get("file").replace(r"\/", "/").replace("\\", "")
                            if sub_path.startswith("/"):
                                sub_url = f"https://www.hdfilmcehennemi.nl{sub_path}"
                            else:
                                sub_url = sub_path
                            subtitles.append(
                                Subtitle(
                                    name=t.get("label") or t.get("language") or "Türkçe",
                                    url=sub_url,
                                )
                            )
                except Exception as e:
                    print(f"[!] {self.name} altyazı ayrıştırma hatası: {e}")

            # Oynatıcı için HTTP başlıkları
            # Close iframe'leri için referer kaynak domain olmalı (rapidrame.com değil)
            if is_close:
                stream_referer = f"https://{embed_domain}/"
                source_label = "Close"
            else:
                stream_referer = "https://rapidrame.com/"
                source_label = "Rapidrame"

            stream_headers = {
                "User-Agent": headers["User-Agent"],
                "Referer": stream_referer,
                "Origin": stream_referer.rstrip("/"),
            }

            return ExtractResult(
                name=f"HDFilmCehennemi | {source_label}",
                url=stream_url.replace(r"\/", "/"),
                referer=stream_referer,
                headers=stream_headers,
                subtitles=subtitles,
            )

        except Exception as e:
            print(f"[!] {self.name} extract hatası ({url}): {e}")
            return None


# Geriye dönük uyumluluk için alias
Rapidrame = RapidrameExtractor