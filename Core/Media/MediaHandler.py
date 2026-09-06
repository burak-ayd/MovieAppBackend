
import os
import subprocess
import tempfile
import uuid

from Core.Helpers import konsol, is_debug, debug_log
from Core.Extractor.ExtractorModels import ExtractResult

# Browser User-Agent — segment CDN User-Agent filtresini geçer
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

class MediaHandler:
    def __init__(self, title: str = "", headers: dict = None):
        # Varsayılan HTTP başlıklarını ayarla
        if headers is None:
            headers = {"User-Agent": BROWSER_USER_AGENT}

        self.headers = headers
        self.title   = title

    def _materialize_subtitle(self, subtitle, headers: dict) -> str | None:
        """Altyazı URL'sini indirip geçici dosyaya yazar, mpv'ye lokal yol döndürür.
        CF korumalı domain'ler (hdfilmcehennemi.mobi gibi) için cloudscraper fallback.
        Başarısız olursa URL'yi doğrudan döndürür (mpv kendi TLS fingerprint'iyle dener).
        """
        import sys
        from urllib.parse import urlparse
        path = urlparse(subtitle.url).path
        ext = os.path.splitext(path)[1] or ".vtt"
        # Güvenli dosya adı: subtitle.name slug + unique id
        safe_name = "".join(c if c.isalnum() else "_" for c in (subtitle.name or "sub"))
        tmp_path = os.path.join(tempfile.gettempdir(), f"omnirule_sub_{safe_name}_{uuid.uuid4().hex[:8]}{ext}")

        request_headers = {
            "User-Agent": headers.get("User-Agent", BROWSER_USER_AGENT),
            "Referer": headers.get("Referer", ""),
            "Origin": headers.get("Origin", ""),
        }

        _log = debug_log

        _log(f"[SUB] '{subtitle.name}' indiriliyor: {subtitle.url[:80]}")

        try:
            import httpx
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(subtitle.url, headers=request_headers)
                _log(f"[SUB] httpx status={r.status_code} bytes={len(r.content)}")
                if r.status_code == 200 and r.content:
                    with open(tmp_path, "wb") as f:
                        f.write(r.content)
                    _log(f"[SUB] httpx OK → {tmp_path}")
                    return tmp_path
        except Exception as e:
            _log(f"[SUB] httpx exception: {e!r}")

        # CF fallback (sync cloudscraper)
        try:
            from cloudscraper import CloudScraper
            with CloudScraper() as s:
                r = s.get(subtitle.url, headers=request_headers, timeout=15)
                _log(f"[SUB] cloudscraper status={r.status_code} bytes={len(r.content)}")
                if r.status_code == 200 and r.content:
                    with open(tmp_path, "wb") as f:
                        f.write(r.content)
                    _log(f"[SUB] cloudscraper OK → {tmp_path}")
                    return tmp_path
        except Exception as e:
            _log(f"[SUB] cloudscraper exception: {e!r}")

        _log(f"[SUB] '{subtitle.name}' indirilemedi, URL doğrudan kullanılacak")
        return subtitle.url

    def play_media(self, extract_data: ExtractResult):
        # Referer varsa headers'a ekle
        if extract_data.referer:
            self.headers.update({"Referer": extract_data.referer})

        # ExtractResult'tan gelen headers'ları ekle
        if extract_data.headers:
            self.headers.update(extract_data.headers)

        # Google Drive gibi özel durumlar için yt-dlp kullan
        # if self.headers.get("User-Agent") in ["googleusercontent", "Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0"]:
        #     return self.play_with_ytdlp(extract_data)

        # # İşletim sistemine göre oynatıcı seç
        # if subprocess.check_output(['uname', '-o']).strip() == b'Android':
        #     return self.play_with_android_mxplayer(extract_data)

        # Cookie veya alt yazılar varsa mpv kullan
        # if "Cookie" in self.headers or extract_data.subtitles:
        #     return self.play_with_mpv(extract_data)
        return self.play_with_mpv(extract_data)
        # return self.play_with_vlc(extract_data)

    def play_with_vlc(self, extract_data: ExtractResult):    

        konsol.log(f"[yellow][»] VLC ile Oynatılıyor : {extract_data.url}")
        konsol.print(self.headers)
        try:
            vlc_command = ["vlc", "--quiet"]

            if self.title:
                vlc_command.extend([
                    f"--meta-title={self.title}",
                    f"--input-title-format={self.title}"
                ])

            user_agent = self.headers.get("User-Agent") or BROWSER_USER_AGENT
            vlc_command.append(f"--http-user-agent={user_agent}")

            if "Referer" in self.headers:
                vlc_command.append(f"--http-referrer={self.headers.get('Referer')}")

            vlc_command.extend(
                f"--sub-file={subtitle.url}" for subtitle in extract_data.subtitles
            )
            vlc_command.append(extract_data.url)
            
            debug_log(f"Çalıştırılan VLC komutu: {' '.join(vlc_command)}")

            with open(os.devnull, "w") as devnull:
                subprocess.run(vlc_command, stdout=devnull, stderr=devnull, check=True)

        except subprocess.CalledProcessError as hata:
            konsol.print(f"[red]VLC oynatma hatası: {hata}[/red]")
            konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})
        except FileNotFoundError:
            konsol.print("[red]VLC bulunamadı! VLC kurulu olduğundan emin olun.[/red]")
            konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})

    def play_with_mpv(self, extract_data: ExtractResult):
        konsol.log(f"[yellow][»] MPV ile Oynatılıyor : {extract_data.url}")
        # URL'de görünmez karakter olabilir; repr ile gerçek byte'ları göster
        if any(ord(c) > 127 or ord(c) < 32 for c in extract_data.url if c not in "\t\n\r"):
            debug_log(f"[DEBUG MPV] URL repr: {extract_data.url!r}")
        try:
            mpv_command = ["mpv"]

            if self.title:
                mpv_command.append(f"--force-media-title={self.title}")
                # mpv_command.extend([
                #     f"--force-media-title={self.title}",
                #     f"--title={self.title}",
                #     f"--script-opts=osc-title={self.title}",
                # ])

            header_fields = []
            for key, value in self.headers.items():
                if isinstance(value, dict):
                    # Dict türündeki başlıkları (örn. Cookie) HTTP formatına çevir (virgül içermez)
                    cookie_val = "; ".join(f"{k}={v}" for k, v in value.items())
                    header_fields.append(f"{key}: {cookie_val}")
                else:
                    val_str = str(value)
                    if key.lower() == "cookie":
                        val_str = val_str.replace(",", ";")
                    header_fields.append(f"{key}: {val_str}")

            if "User-Agent" not in self.headers:
                header_fields.append(f"User-Agent: {BROWSER_USER_AGENT}")

            if "Accept" not in self.headers:
                header_fields.append("Accept: */*")

            if "Accept-Language" not in self.headers:
                header_fields.append("Accept-Language: en-US,en;q=0.9")

            if header_fields:
                mpv_command.append(f"--http-header-fields={','.join(header_fields)}")

            # HLS için lavf demuxer zorla (dbx.molystream.org /q/1 URL'leri text/html döner)
            # NOT: master.txt uzantılı CDN linkleri mpv/ffmpeg tarafından otomatik HLS olarak algılanır.
            # Burada --demuxer-lavf-format=hls eklenmemelidir; mpv'de global lavf formatı zorlamak
            # --sub-file ile yüklenen harici altyazı (.vtt/.srt) dosyalarını da hls olarak açmaya çalışıp
            # 'avformat_open_input() failed' hatasıyla bozar.
            url_lower = extract_data.url.lower()
            if "molystream" in url_lower:
                mpv_command.extend(["--demuxer=lavf", "--demuxer-lavf-format=hls"])

            # Altyazıları mpv başlamadan önce indir (CF korumalı domain'ler için mpv'nin TLS
            # fingerprint'i yetersiz kalıyor). İndirilenler geçici dosyaya yazılır ve mpv'ye
            # lokal yol olarak geçilir.
            if extract_data.subtitles:
                mpv_command.append("--sub-demuxer=subrandr")
                for subtitle in extract_data.subtitles:
                    local_path = self._materialize_subtitle(subtitle, self.headers)
                    if local_path:
                        mpv_command.append(f"--sub-file={local_path}")
                mpv_command.append("--sid=auto")

            mpv_command.append(extract_data.url)
            
            debug_log(f"Çalıştırılan MPV komutu: {' '.join(mpv_command)}")

            with open(os.devnull, "w") as devnull:
                subprocess.run(mpv_command, stdout=devnull, stderr=devnull, check=True)
        except subprocess.CalledProcessError as hata:
            konsol.print(f"[red]mpv oynatma hatası: {hata}[/red]")
            konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})
        except FileNotFoundError:
            konsol.print("[red]mpv bulunamadı! mpv kurulu olduğundan emin olun.[/red]")
            konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})

    def play_with_ytdlp(self, extract_data: ExtractResult):
        konsol.log(f"[yellow][»] yt-dlp ile Oynatılıyor : {extract_data.url}")
        konsol.print(self.headers)
        try:
            ytdlp_command = ["yt-dlp", "--quiet", "--no-warnings"]
            print("1")
            for key, value in self.headers.items():
                ytdlp_command.extend(["--add-header", f"{key}: {value}"])
            print("2")
            ytdlp_command.extend([
                "-o", "-",
                extract_data.url
            ])  
            print("3",ytdlp_command)
            mpv_command = ["mpv", "--really-quiet", "-"]
            print("4")
            if self.title:
                mpv_command.append(f"--force-media-title={self.title}")
                print("5")
            mpv_command.extend(
                f"--sub-file={subtitle.url}" for subtitle in extract_data.subtitles
            )
            print("6",mpv_command)
            with subprocess.Popen(ytdlp_command, stdout=subprocess.PIPE) as ytdlp_proc:             
                subprocess.run(mpv_command, stdin=ytdlp_proc.stdout, check=True)

        except subprocess.CalledProcessError as hata:
            konsol.print(f"[red]Oynatma hatası: {hata}[/red]")
            konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})
        except FileNotFoundError:
            konsol.print("[red]yt-dlp veya mpv bulunamadı! Kurulumlarından emin olun.[/red]")
            konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})

    def play_with_android_mxplayer(self, extract_data: ExtractResult):
        konsol.log(f"[yellow][»] MxPlayer ile Oynatılıyor : {extract_data.url}")
        konsol.print(self.headers)
        paketler = [
            "com.mxtech.videoplayer.ad/.ActivityScreen",  # Free sürüm
            "com.mxtech.videoplayer.pro/.ActivityScreen"  # Pro sürüm
        ]

        for paket in paketler:
            try:
                android_command = [
                    "am", "start",
                    "-a", "android.intent.action.VIEW",
                    "-d", extract_data.url,
                    "-n", paket
                ]

                if self.title:
                    android_command.extend(["--es", "title", self.title])

                with open(os.devnull, "w") as devnull:
                    subprocess.run(android_command, stdout=devnull, stderr=devnull, check=True)

                return

            except subprocess.CalledProcessError as hata:
                konsol.print(f"[red]{paket} oynatma hatası: {hata}[/red]")
                konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})
            except FileNotFoundError:
                konsol.print(f"Paket: {paket}, Hata: MX Player kurulu değil")
                konsol.print({"title": self.title, "url": extract_data.url, "headers": self.headers})