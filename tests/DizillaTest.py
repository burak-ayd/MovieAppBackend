# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
"""Dizilla test / oynatma aracı.

Ortak akış `tests/EklentiTestAraci.py` içinde; bu dosya yalnızca eklenti adını verir.

    python tests/DizillaTest.py
    python tests/DizillaTest.py --arama "breaking bad"
    python tests/DizillaTest.py --kategori "Aksiyon" --sayfa 2
    python tests/DizillaTest.py --url "https://dizilla.now/breaking-bad-1-sezon-1-bolum-c02" --otomatik --oynat --saniye 20
"""

import sys
from pathlib import Path

# Hem `python tests/DizillaTest.py` hem `python -m tests.DizillaTest` için yol ayarı
for _yol in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
    if str(_yol) not in sys.path:
        sys.path.insert(0, str(_yol))

from EklentiTestAraci import calistir

if __name__ == "__main__":
    calistir("Dizilla", "Dizilla - Yabancı dizi izleme platformu")
