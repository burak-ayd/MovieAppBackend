# Oluşturan: Burak Aydoğan
"""
Şifreleme/çözümleme yardımcıları.

Bu modül, daha önce `Kekik` paketinden gelen üç sınıfın aynı davranışıyla
yeniden yazılmış hâlidir:

    from Kekik.Sifreleme import CryptoJS        →  from Core.Helpers.Sifreleme import CryptoJS
    from Kekik.Sifreleme import HexCodec, Packer →  from Core.Helpers.Sifreleme import HexCodec, Packer

Neden taşındı:

  1. `Kekik` bir genel amaçlı yardımcı kütüphanesidir ve 15 bağımlılık
     getirir (aiohttp, redis, pytz, tabulate, simplejson, cssselect, ...).
     Proje ise yalnızca bu üç sınıfını kullanıyor; geri kalanı kullanılmıyor.
  2. `Kekik` GPLv3+ lisanslıdır. Üç sınıfı kullanmak, tüm projeye GPL
     yükü getiriyordu; bu modül onları bağımlılık zincirinden çıkarır.

Gerçekten kullanılan API (kalan kısım ölü koddu, taşınmadı):
  • CryptoJS : yalnızca `decrypt`
  • Packer   : yalnızca `unpack`
  • HexCodec : yalnızca `decode`

Bağımlılık: yalnızca `CryptoJS` için `pycryptodome` (AES-CBC).
`HexCodec` ve `Packer` saf standart kütüphanedir.
"""

from __future__ import annotations

import base64
import hashlib
import re

try:
    from Crypto.Cipher import AES
except ImportError as _hata:  # pragma: no cover
    raise ImportError(
        "CryptoJS için 'pycryptodome' gerekiyor. Kurulum: "
        "pip install pycryptodome  (requirements.txt içinde yer alıyor)"
    ) from _hata


# ══════════════════════════════════════════════════════════════════════════════
#  HexCodec — kaçış dizili hex <-> UTF-8 metin
# ══════════════════════════════════════════════════════════════════════════════

class HexCodec:
    """Kaçış dizileriyle yazılmış hex dizilerini düz metne çevirir."""

    @staticmethod
    def encode(utf8_string: str) -> str:
        """UTF-8 stringini kaçış dizileriyle birlikte hex stringine dönüştürür."""
        byte_data   = utf8_string.encode("utf-8")
        hex_string  = byte_data.hex()
        escaped_hex = "\\x".join(hex_string[i:i+2] for i in range(0, len(hex_string), 2))

        return f"\\x{escaped_hex}"

    @staticmethod
    def decode(escaped_hex: str) -> str:
        """
        Kaçış dizileri içeren bir hex stringini UTF-8 formatındaki stringe
        dönüştürür.

        Oynatıcı metni `\\x68\\x74\\x74\\x70...` biçiminde geliyorsa hex
        çözülür. `\\x` ile başlamayan girdi (ör. düz `http://...`) ise
        unicode_escape üzerinden geçirilir — böylece `\\u0130` gibi diziler
        de doğru karaktere dönüşür.
        """
        escaped_hex = escaped_hex.strip().replace("\\X", "\\x")

        if isinstance(escaped_hex, str) and not escaped_hex.startswith(r"\x"):
            return escaped_hex.encode("unicode_escape").decode("utf-8")

        hex_string = escaped_hex.replace("\\x", "")
        byte_data  = bytes.fromhex(hex_string)

        return byte_data.decode("utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  Packer — P.A.C.K.E.R. sıkıştırılmış JavaScript çözücü
# ══════════════════════════════════════════════════════════════════════════════

class Packer:
    """
    Dean Edwards' P.A.C.K.E.R. algoritmasıyla sıkıştırılmış JavaScript'i çözer.

    Format: eval(function(p,a,c,k,e){...}('PAYLOAD',RADIX,COUNT,'SYM|SYM|...'.split('|')))

    Çözüm iki adımdadır: önce argümanlar (payload, radix, sembol tablosu)
    çıkarılır, sonra payload içindeki her kelime taban-radix sayıya çevrilip
    sembol tablosundaki karşılığıyla değiştirilir.

    Gerçek sayfalarda birden fazla varyant görüldüğü için birden fazla
    regex deseni denenir; en sonda elle parçalama denenir.
    """

    # Ana desen — standart PACKED çağrısı
    PACKED_PATTERN = re.compile(
        r"\}\s*\(\s*['\"](.*?)['\"],\s*(\d+),\s*(\d+),\s*['\"](.+?)['\"]\.split\(['\"]\\?\|['\"]\)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL
    )

    # Varyant desenler — farklı site sürümlerinde geçen biçimler
    ALTERNATIVE_PATTERNS = [
        # Standart desen (tırnak tipi farklı olabilir)
        re.compile(
            r"\}\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*?)'\.split\('\|'\)",
            re.IGNORECASE | re.MULTILINE | re.DOTALL
        ),
        # Daha gevşek desen: tırnak/aralık esnekliği
        re.compile(
            r"\}\s*\(\s*['\"](.*?)['\"],\s*(\d+),\s*(\d+),\s*['\"](.+?)['\"]\.split\(['\"]\\?\|['\"]\)",
            re.IGNORECASE | re.MULTILINE | re.DOTALL
        ),
        # eval(function(p,a,c,k,e){...}return p}(...)) biçimi
        re.compile(
            r"eval\(function\(p,a,c,k,e,(?:r|d|)\)\{.*?return p\}(.*?\.split\('\|'\))",
            re.IGNORECASE | re.MULTILINE | re.DOTALL
        )
    ]

    # Payload içindeki kelimeleri yakalayan desen
    REPLACE_PATTERN = re.compile(
        r"\b\w+\b",
        re.IGNORECASE | re.MULTILINE
    )

    # Radix 52/54/62 için kullanılan alfabeler (base64 benzeri)
    ALPHABET = {
        52: "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP",
        54: "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQR",
        62: "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        95: " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
    }

    @staticmethod
    def clean_escape_sequences(source: str) -> str:
        """Kaynak koddaki çift kaçışları ve tırnak kaçışlarını sadeleştirir."""
        source = re.sub(r'\\\\', r'\\', source)
        source = source.replace("\\'", "'")
        source = source.replace('\\"', '"')
        return source

    @staticmethod
    def extract_arguments(source: str) -> tuple[str, list[str], int, int]:
        """
        P.A.C.K.E.R. kaynak kodundan argümanları çıkarır.

        Dönüş: (payload, sembol listesi, radix, count)

        Not: `count` ile sembol sayısı uyuşmazsa hata VERİLMEZ. Gerçek
        sayfalarda sembol tablosu kısaltılmış olabiliyor; çözüm yine de
        çalışıyor.
        """
        # Önce standart desenle dene
        match = Packer.PACKED_PATTERN.search(source)

        # Bulunamazsa varyant desenleri dene
        if not match:
            for pattern in Packer.ALTERNATIVE_PATTERNS:
                match = pattern.search(source)
                if match:
                    break

        # Son çare: daha serbest bir string araması
        if not match:
            if "'.split('|')" in source or '".split("|")' in source:
                try:
                    parts = re.findall(r"\((['\"](.*?)['\"],\s*(\d+),\s*(\d+),\s*['\"](.*?)['\"]\.split", source)
                    if parts:
                        payload, radix, count, symtab = parts[0][1:]
                        return payload, symtab.split("|"), int(radix), int(count)
                except Exception:
                    pass

            raise ValueError("Geçersiz P.A.C.K.E.R. biçimi: desen bulunamadı.")

        # eval biçimi yakalandıysa içeriği çıkar
        if len(match.groups()) == 1:
            eval_content = match.group(1)
            if inner_match := re.search(r"\('(.*)',(\d+),(\d+),'(.*)'\)", eval_content):
                payload, radix, count, symtab = inner_match.groups()
            else:
                raise ValueError("eval deseninden argümanlar çıkarılamadı.")
        else:
            payload, radix, count, symtab = match.groups()

        return payload, symtab.split("|"), int(radix), int(count)

    @staticmethod
    def unbase(value: str, base: int) -> int:
        """
        Verilen kelimeyi belirtilen tabandan ondalık sayıya çevirir.

        2-36 tabanları Python'un kendi dönüşümüyle; 37-95 tabanları
        ALPHABET sözlüğüyle çözülür (JS'in toString(base) davranışı).
        """
        if base > 95:
            raise ValueError(f"Desteklenmeyen taban: {base}")

        # Python'un yerleşik dönüşümü (2-36)
        if 2 <= base <= 36:
            try:
                return int(value, base)
            except ValueError:
                return 0

        # Geniş taban desteği (37-95)
        if base > 62:
            selector = 95
        elif base > 54:
            selector = 62
        elif base > 52:
            selector = 54
        else:
            selector = 52

        char_dict = {char: idx for idx, char in enumerate(Packer.ALPHABET[selector])}

        result = 0
        for index, char in enumerate(reversed(value)):
            digit = char_dict.get(char, 0)
            result += digit * (base ** index)

        return result

    @staticmethod
    def lookup_symbol(match: re.Match, symtab: list[str], radix: int) -> str:
        """Bulunan kelimeyi sembol tablosundaki karşılığıyla değiştirir."""
        word = match[0]

        try:
            index = Packer.unbase(word, radix)
            if 0 <= index < len(symtab):
                replacement = symtab[index]
                return replacement or word
        except (ValueError, IndexError):
            pass

        return word

    @staticmethod
    def unpack(source: str) -> str:
        """
        P.A.C.K.E.R. ile sıkıştırılmış JavaScript'i çözer.

        Sitenin bazı oynatıcılarında iç içe iki katman sıkıştırma kullanıldığı
        için iki kez çağrılması normaldir:
            Packer.unpack(Packer.unpack(eval_jwsetup))
        """
        source = Packer.clean_escape_sequences(source)

        try:
            payload, symtab, radix, _count = Packer.extract_arguments(source)
        except Exception as e:
            raise ValueError(
                f"P.A.C.K.E.R. çözülemedi: {e}\nKaynak önizleme: {source[:100]}..."
            ) from e

        # Sembol tablosu ile count uyuşmazlığı HATA DEĞİLDİR: kısaltılmış
        # tablolar gerçek sayfalarda görülüyor, çözüm yine de doğru çalışır.
        return Packer.REPLACE_PATTERN.sub(
            lambda match: Packer.lookup_symbol(match, symtab, radix),
            payload
        )


# ══════════════════════════════════════════════════════════════════════════════
#  CryptoJS — CryptoJS.AES ile uyumlu AES/CBC/PKCS7 çözme
# ══════════════════════════════════════════════════════════════════════════════

class CryptoJS:
    """
    CryptoJS.AES ile uyumlu şifre çözme.

    CryptoJS çıktısı şu biçimdedir:
        base64( "Salted__" (8 bayt) + salt (8 bayt) + AES-CBC şifreli metin )
    Anahtar ve IV, parola+salt çiftinden OpenSSL'in EVP_BytesToKey algoritmasıyla
    türetilir (MD5, tek yineleme).

    Yalnızca `decrypt` uygulanmıştır: proje yalnızca çözme yapar, şifreleme
    yapmaz. `encrypt`/`generate_salt` kullanılmadığı için eklenmedi.
    """

    KEY_SIZE = 32
    IV_SIZE  = 16
    AES_MODE = AES.MODE_CBC
    APPEND   = b"Salted__"
    KDF      = "md5"

    @staticmethod
    def evp_kdf(password, salt, key_size: int = KEY_SIZE, iv_size: int = IV_SIZE, iterations: int = 1) -> tuple[bytes, bytes]:
        """
        Parola + tuzdan (anahtar, IV) çifti türetir — OpenSSL EVP_BytesToKey.

        `iterations=1` CryptoJS varsayılanıdır; her turda özet birikimli
        olarak ilerler, toplam `key_size + iv_size` bayt dolana kadar.
        """
        target_key_size = key_size + iv_size
        derived_bytes   = b""
        block           = None

        while len(derived_bytes) < target_key_size:
            hasher = hashlib.new(CryptoJS.KDF)
            if block:
                hasher.update(block)

            hasher.update(password)
            hasher.update(salt)
            block = hasher.digest()

            for _ in range(1, iterations):
                block = hashlib.new(CryptoJS.KDF, block).digest()

            derived_bytes += block

        return derived_bytes[:key_size], derived_bytes[key_size:key_size + iv_size]

    @staticmethod
    def _unpad(data: bytes) -> bytes:
        """PKCS7 dolgusunu kaldırır."""
        return data[:-ord(data[-1:])]

    @staticmethod
    def decrypt(password: str, cipher_text: str) -> str:
        """
        CryptoJS ile şifrelenmiş metni çözer.

        Dönüş: çözülmüş UTF-8 metin.
        """
        ct_bytes          = base64.b64decode(cipher_text)
        salt              = ct_bytes[8:16]
        cipher_text_bytes = ct_bytes[16:]

        key, iv = CryptoJS.evp_kdf(
            password.encode("utf-8"),
            salt,
            key_size=CryptoJS.KEY_SIZE,
            iv_size=CryptoJS.IV_SIZE,
        )

        cipher     = AES.new(key, CryptoJS.AES_MODE, iv)
        plain_text = cipher.decrypt(cipher_text_bytes)

        return CryptoJS._unpad(plain_text).decode("utf-8")
