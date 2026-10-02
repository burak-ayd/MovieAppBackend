# Oluşturan: Burak Aydoğan
#
# Akış: POST {url}?do=getVideo (hash, r, s) -> JSON `videoSources`
#       (yanıt teve2 embed'i içerirse teve2 API'sine geçilir)
#
# Not: HDStreamAble bu sınıftan türetiliyor (yalnızca main_url değişiyor).

import re
from typing import Any, List, Optional, Union

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class PeaceMakerst(ExtractorBase):
    name     = "PeaceMakerst"
    main_url = "https://peacemakerst.com"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and ("peacemakerst.com" in url or "hdstreamable.com" in url)

    def _ajax_basliklari(self, referer: str) -> dict:
        return {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
        }

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        referer = referer or f"{self.main_url}/"
        vid_id = url.split("video/")[-1].split("/")[0].split("?")[0]

        yanit = await self.httpx.post(
            f"{url}?do=getVideo",
            data={"hash": vid_id, "r": referer, "s": ""},
            headers=self._ajax_basliklari(referer),
            timeout=30.0,
        )
        govde = yanit.text or ""

        # --- teve2 yönlendirmesi ---
        if "teve2.com.tr\\/embed\\/" in govde:
            teve_id = govde.split("teve2.com.tr\\/embed\\/")[1].split('"')[0]
            m3u8 = await self._teve2_coz(teve_id)
            if not m3u8:
                raise ValueError(f"{self.name}: teve2 bağlantısı çözülemedi")

            return ExtractResult(
                name=self.name,
                url=m3u8,
                referer=referer,
                headers={"Referer": f"https://www.teve2.com.tr/embed/{teve_id}"},
            )

        # --- standart yanıt ---
        try:
            veri = yanit.json()
        except Exception as e:
            raise ValueError(f"{self.name}: yanıt JSON değil ({e})") from e

        kaynaklar = veri.get("videoSources") or []
        m3u8 = kaynaklar[-1].get("file") if kaynaklar else None
        if not m3u8:
            raise ValueError(f"{self.name}: m3u bağlantısı bulunamadı")

        return ExtractResult(
            name=self.name,
            url=self.fix_url(m3u8),
            referer=referer,
            headers={"Referer": referer},
        )

    async def _teve2_coz(self, teve_id: str) -> Optional[str]:
        """teve2 gömülü oynatıcı -> serviceUrl + securePath birleşimi."""
        try:
            yanit = await self.httpx.get(
                f"https://www.teve2.com.tr/action/media/{teve_id}",
                headers={"Referer": f"https://www.teve2.com.tr/embed/{teve_id}"},
                timeout=30.0,
            )
            baglanti = (yanit.json().get("Media") or {}).get("Link") or {}
            return f'{baglanti["ServiceUrl"]}//{baglanti["SecurePath"]}'
        except Exception as e:
            print(f"[!] {self.name}: teve2 hatası: {e}")
            return None


PeaceMakerstExtractor = PeaceMakerst