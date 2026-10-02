# Oluşturan: Burak Aydoğan
#
# İki nesil oynatıcı desteklenir:
#   1) bePlayer('<anahtar>', '{...}') -> AES çözme -> "video_location":"..."
#      (Kotlin: AesHelper.cryptoAESHandler -> AES/ECB/PKCS5Padding)
#   2) file:"..." + tracks:[...]  -> doğrudan m3u8 + altyazılar

import base64
import json
import re
from typing import Any, List, Optional, Union

from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle


class HDMomPlayer(ExtractorBase):
    name     = "HDMomPlayer"
    main_url = "https://hdmomplayer.com"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and "hdmomplayer" in url

    # ------------------------------------------------------------------ #
    # Şifreleme (Kotlin AesHelper -> AES/ECB/PKCS5Padding)
    # ------------------------------------------------------------------ #

    def _aes_ebs_coz(self, veri: str, anahtar: str) -> str:
        """Base64 metni AES/ECB ile çözer, JSON'u geri döndürür."""
        try:
            ham = base64.b64decode(veri + "=" * (-len(veri) % 4))
            cozucu = Cipher(algorithms.AES(anahtar.encode()), modes.ECB()).decryptor()
            duz = cozucu.update(ham) + cozucu.finalize()
            geri = crypto_padding.PKCS7(128).unpadder()
            return (geri.update(duz) + geri.finalize()).decode("utf-8", "replace").replace("\\", "")
        except Exception:
            return ""

    # ------------------------------------------------------------------ #

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        referer = referer or f"{self.main_url}/"
        istek = await self.httpx.get(url, headers={"Referer": referer}, timeout=30.0)
        govde = istek.text or ""

        altyazilar: List[Subtitle] = []
        m3u8 = None

        # --- 1) bePlayer(...) ---
        be = re.search(r"""bePlayer\('([^']+)',\s*'(\{[^}]+\})'\);""", govde)
        if be:
            anahtar, sifreli = be.group(1), be.group(2)
            cozulmus = self._aes_ebs_coz(sifreli, anahtar)
            if cozulmus:
                m = re.search(r'video_location":"([^"]+)', cozulmus)
                if m:
                    m3u8 = m.group(1).replace("\\/", "/")

        # --- 2) file:"..." + tracks:[...] ---
        if not m3u8:
            m = re.search(r'file:"([^"]+)', govde)
            if m:
                m3u8 = m.group(1).replace("\\/", "/")

            blok = re.search(r"tracks:\[([^\]]+)", govde)
            if blok:
                try:
                    parcalar = json.loads("[" + blok.group(1) + "]")
                except Exception:
                    parcalar = re.findall(r'file:"([^"]+)".*?label:"([^"]+)"', blok.group(1), re.S)
                    parcalar = [{"file": f, "label": l} for f, l in parcalar]

                for track in parcalar:
                    if not isinstance(track, dict):
                        continue
                    etiket = track.get("label") or ""
                    if not etiket or not track.get("file"):
                        continue
                    if "Forced" in etiket:      # Kotlin zorunlu altyazıları atıyor
                        continue
                    altyazilar.append(Subtitle(
                        name=etiket,
                        url=self.fix_url(f"{self.main_url}{track['file']}"),
                    ))

        if not m3u8:
            raise ValueError(f"{self.name}: m3u bağlantısı bulunamadı ({url})")

        return ExtractResult(
            name=self.name,
            url=self.fix_url(m3u8),
            referer=url,
            headers={"Referer": url},
            subtitles=altyazilar,
        )


HDMomPlayerExtractor = HDMomPlayer