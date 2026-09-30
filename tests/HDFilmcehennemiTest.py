# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
"""HDFilmCehennemi test / oynatma aracı.

Ortak akış `tests/EklentiTestAraci.py` içinde; bu dosya yalnızca eklenti adını verir.
Önceki sürümde sezon/bölüm seçimi boş bırakılmış ve kategori desteği yoktu; artık
film ve dizi akışlarının ikisi de tam çalışıyor.

    python tests/HDFilmcehennemiTest.py
    python tests/HDFilmcehennemiTest.py --arama "spider-noir"
    python tests/HDFilmcehennemiTest.py --kategori "IMDB 7+ Filmler"
    python tests/HDFilmcehennemiTest.py --url "<dizi url>" --otomatik --oynat --saniye 20
"""

import sys
from pathlib import Path

for _yol in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
    if str(_yol) not in sys.path:
        sys.path.insert(0, str(_yol))

from EklentiTestAraci import calistir

if __name__ == "__main__":
    calistir("HDFilmCehennemi", "HDFilmCehennemi - film & dizi izleme")
