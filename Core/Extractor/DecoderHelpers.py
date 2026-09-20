import base64
import json
import re
import shutil
import subprocess
from typing import Optional

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
    """Rapidrame dahili player'larındaki (dc_...) dinamik akış çözümleyiciyi yürütür."""
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


def decode_close_v2(parts: list[str]) -> str:
    """hdfilmcehennemi ve rapidrame yeni nesil (v2) obfuscasyonunu çözer.
    Dinamik delimiter ile ayrılmış parçalardan anahtarları çıkarır, ters Caesar/atob/reverse
    ve Fisher-Yates karıştırmasını geri alıp XOR ile gerçek akış URL'sini üretir.
    """
    parts = list(parts)
    yq0i = len(parts) - 2
    if yq0i < 13:
        return ""
    u3b75 = yq0i % 7
    d0ce = 8 + (yq0i % 5)

    g5se = parts.pop(d0ce)
    p0fp = parts.pop(u3b75)
    c3u = "".join(parts)

    if len(p0fp) > 4096:
        c3u = base64.b64decode(c3u).decode("latin-1")

    n5a9q = 0
    ub7o0 = 0
    for f03rn, ch in enumerate(p0fp):
        t6qe = ord(ch)
        n5a9q = (n5a9q * 37 + t6qe) % 241
        ub7o0 = (ub7o0 + ((t6qe << 1) ^ f03rn)) & 255

    t7zf2 = (n5a9q * 3 + ub7o0) % 256
    bt00 = (ub7o0 % 11) + 5
    b0uy = ((ub7o0 * 251 + n5a9q) % 65519) + 1

    for kk2 in reversed(g5se):
        if kk2 == '7':
            c3u = base64.b64decode(c3u).decode("latin-1")
        elif kk2 == '3':
            c3u = c3u[::-1]
        else:
            rv6 = (26 - ((ord(kk2) - 96) % 26)) % 26
            def shift_char(m):
                ch = m.group(0)
                o = ord(ch)
                base = 65 if o <= 90 else 97
                return chr((o - base + rv6) % 26 + base)
            c3u = re.sub(r'[a-zA-Z]', shift_char, c3u)

    if len(g5se) > 2048:
        c3u = c3u[::-1]

    yq0i = len(c3u)
    ask84 = [0] * yq0i
    for f03rn in range(yq0i - 1, 0, -1):
        b0uy = (b0uy * 97 + 41) % 65519
        ask84[f03rn] = b0uy % (f03rn + 1)

    chars = list(c3u)
    for f03rn in range(1, yq0i):
        v97 = ask84[f03rn]
        chars[f03rn], chars[v97] = chars[v97], chars[f03rn]
    c3u = "".join(chars)

    e0bt = t7zf2
    out = []
    for ch in c3u:
        t6qe = ord(ch)
        e0bt = (e0bt * 5 + bt00) % 256
        out.append(chr(t6qe ^ e0bt))
        e0bt = (e0bt + t6qe) % 256
    return "".join(out)


def decode_close_obfuscation(parts: list[str], key1: str, key2: str) -> str:
    """v1 obfuscasyon çözümleyici."""
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


def extract_close_keys(unpacked_code: str, fn_name: str) -> tuple[Optional[str], Optional[str]]:
    """Fonksiyon gövdesinin içinden iki anahtar string'i çeker."""
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


def resolve_player_stream(html_content: str, unpacked_code: str = "") -> Optional[str]:
    """Close (hdfilmcehennemi.mobi) ve Rapidrame (rplayer / playerr) sayfalarındaki
    gerçek akış URL'sini çıkarır.
    Sayfadaki decoy/honeypot (filmakinesimp4) değişkenlerini eler, JWPlayer veya
    configs içindeki asıl değişkeni unpacked JS kodunu da kapsayarak çözümler.
    """
    def is_valid_stream_url(url: Optional[str]) -> bool:
        if not url or not isinstance(url, str):
            return False
        if "filmakinesimp4" in url:
            return False
        return url.startswith("http") and any(ext in url for ext in [".m3u8", "master", ".txt", ".mp4"])

    # 1. Sayfadaki tüm Dean Edwards packer (eval) bloklarını aç ve birleştir
    unpacked_blocks = []
    if unpacked_code and unpacked_code != html_content:
        unpacked_blocks.append(unpacked_code)

    for line in html_content.splitlines():
        if "eval(function(p,a,c,k,e" in line:
            try:
                unpacked_blocks.append(JsUnpacker.unpack(line))
            except Exception:
                pass

    combined_code = html_content + "\n" + "\n".join(unpacked_blocks)

    # 2. Yorum satırlarını temizle (örn. //sources: [{file:atob(file_link)}])
    clean_code = re.sub(r'//.*$', '', combined_code, flags=re.MULTILINE)

    # 3. JWPlayer / configs sources içindeki asıl değişkeni veya dosya URL'sini bul
    target_var = None
    jw_match = re.search(r'sources\s*:\s*\[\s*\{\s*file\s*:\s*([^,}]+)', clean_code)
    if not jw_match:
        jw_match = re.search(r'file\s*:\s*([^,}]+)\s*,\s*type\s*:\s*["\']hls["\']', clean_code)

    if jw_match:
        raw_val = jw_match.group(1).strip()
        # Doğrudan string URL ise (örn. file: "https://...")
        if (raw_val.startswith('"') and raw_val.endswith('"')) or (raw_val.startswith("'") and raw_val.endswith("'")):
            clean_url = raw_val[1:-1]
            if is_valid_stream_url(clean_url):
                return clean_url
        target_var = raw_val

    # Hedef değişken biliniyorsa combined_code içinde atamasını ara
    candidate_assignments = []
    if target_var:
        m = re.search(
            rf'var\s+{re.escape(target_var)}\s*=\s*([a-zA-Z0-9_$]+)\s*\(\s*(.*?)\s*\)\s*;',
            combined_code,
            re.DOTALL
        )
        if m:
            candidate_assignments.append((target_var, m.group(1), m.group(2).strip()))

    # Eğer jwplayer'dan bulunamadıysa, sayfadaki olası atamaları tara
    if not candidate_assignments:
        for m in re.finditer(r'var\s+([a-zA-Z0-9_$]+)\s*=\s*([a-zA-Z0-9_$]+)\s*\(\s*(["\'].*?["\']\s*\.\s*split\s*\([^)]+\))\s*\)\s*;', combined_code):
            candidate_assignments.append((m.group(1), m.group(2), m.group(3).strip()))

    # Aday atamaları çözmeyi dene
    for var_name, fn_name, arg_expr in candidate_assignments:
        parts = None
        split_match = re.search(r'^["\'](.*?)["\']\s*\.\s*split\s*\(\s*["\'](.*?)["\']\s*\)$', arg_expr, re.DOTALL)
        if split_match:
            raw_str = split_match.group(1)
            sep = split_match.group(2)
            parts = raw_str.split(sep)
        elif arg_expr.startswith("[") and arg_expr.endswith("]"):
            try:
                parts = json.loads(arg_expr)
            except Exception:
                parts = re.findall(r'["\'](.*?)["\']', arg_expr)

        if parts:
            # Önce yeni v2 decoder ile dene
            try:
                decoded = decode_close_v2(parts)
                if is_valid_stream_url(decoded):
                    debug_log(f"[DEBUG Decoder] Player v2 decoder OK: var={var_name} fn={fn_name} url={decoded[:80]}")
                    return decoded
            except Exception as e:
                debug_log(f"[DEBUG Decoder] Player v2 decoder exception: {e}")

            # Eski v1 decoder ile dene (key1/key2)
            key1, key2 = extract_close_keys(combined_code, fn_name)
            if key1 and key2:
                try:
                    decoded = decode_close_obfuscation(parts, key1, key2)
                    if is_valid_stream_url(decoded):
                        debug_log(f"[DEBUG Decoder] Player v1 decoder OK: var={var_name} fn={fn_name} url={decoded[:80]}")
                        return decoded
                except Exception as e:
                    debug_log(f"[DEBUG Decoder] Player v1 decoder exception: {e}")

        # Node.js fallback
        if shutil.which("node"):
            try:
                fn_def_match = re.search(
                    rf'(?:var\s+{re.escape(fn_name)}\s*=\s*function\s*\([^)]*\)\s*\{{.*?\}}|function\s+{re.escape(fn_name)}\s*\([^)]*\)\s*\{{.*?\n\}})',
                    combined_code,
                    re.DOTALL
                )
                if fn_def_match:
                    fn_def = fn_def_match.group(0)
                    js_code = f"""
                    {fn_def}
                    var result = {fn_name}({arg_expr});
                    console.log(result);
                    """
                    proc = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, timeout=5)
                    output = proc.stdout.strip()
                    if is_valid_stream_url(output):
                        debug_log(f"[DEBUG Decoder] Player Node.js decoder OK: var={var_name} fn={fn_name} url={output[:80]}")
                        return output
            except Exception as e:
                debug_log(f"[DEBUG Decoder] Player Node.js exception: {e}")

    return None
