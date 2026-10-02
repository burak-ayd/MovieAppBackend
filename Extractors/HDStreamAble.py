# Oluşturan: Burak Aydoğan
#
# Kotlin'da `PeaceMakerst` sınıfından türetiliyor (yalnızca mainUrl değişiyor).
# ExtractorLoader dosya başına tek sınıf yüklediği için burada sınıf ayrı tanımlanıp
# çözüm mantığı üst sınıftan miras alınıyor.

from Extractors.PeaceMakerst import PeaceMakerst


class HDStreamAble(PeaceMakerst):
    """HDStreamAble — PeaceMakerst ile aynı oynatıcı, farklı alan adı."""

    name     = "HDStreamAble"
    main_url = "https://hdstreamable.com"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and "hdstreamable.com" in url


HDStreamAbleExtractor = HDStreamAble