# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
"""DiziBox test / oynatma aracı.

Ortak akış `tests/EklentiTestAraci.py` içinde; bu dosya yalnızca eklenti adını verir.
(Bu eklentinin `load_links` fonksiyonu ExtractResult listesi döner; harness bunu
str dönen eklentilerle birlikte ele alır.)

    python tests/DiziboxTest.py
    python tests/DiziboxTest.py --arama "silo"
    python tests/DiziboxTest.py --kategori "Aksiyon" --sayfa 1
    python tests/DiziboxTest.py --url "https://www.dizibox.live/diziler/silo-1/" --otomatik --oynat --saniye 20
"""

import sys
from pathlib import Path

for _yol in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
    if str(_yol) not in sys.path:
        sys.path.insert(0, str(_yol))

from EklentiTestAraci import calistir

if __name__ == "__main__":
    calistir("DiziBox", "DiziBox - Yabancı dizi izleme platformu")
