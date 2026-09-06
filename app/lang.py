"""Offline language detection (zero dependencies, instant).

Why: the AI must answer in EXACTLY the language the customer wrote in.
Naming the language explicitly inside the prompt (in both English and the
customer's own tongue, at the top AND the bottom of the prompt) makes the
model comply almost 100% of the time — a vague "answer in the user's
language" rule alone does not.

Detection strategy:
1. Script / alphabet detection (Persian vs Arabic vs Urdu, Cyrillic, CJK,
   Devanagari, Thai, Hebrew, Greek, ...). The dominant script wins.
2. Latin-script languages are separated by characteristic letters and very
   common words (Turkish, Spanish, French, German, Portuguese, Italian,
   Dutch, Polish, Romanian, Vietnamese, Indonesian); default: English.

The result is only used to steer the prompt, so a rare mistake is harmless:
the prompt still carries a generic "match the customer's language" rule
whenever detection is uncertain.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------- scripts
_PERSIAN_MARKERS = set(
    "پچژگک"  # U+067E 0686 0698 06AF 06A9
    "\u06cc"  # ی (Persian yeh) — Arabic uses ي (U+0649/064A)
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"  # ۰-۹
    "\u200c"  # ZWNJ — extremely common in Persian typing
)
_URDU_MARKERS = set("\u0679\u0688\u0691\u06ba\u06be\u06c1\u06d2\u06d3\u06c3\u06cc")  # ٹ ڈ ڑ ں ھ ہ ے ۂ ۃ
_ARABIC_MARKERS = set("ةأإئؤءىك")  # strongly Arabic-only letters (ك=U+0643 vs Persian ک)

_HANGUL_RANGES = ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))
_KANA_RANGES = ((0x3040, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9D))
_HAN_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))


def _in_ranges(cp: int, ranges) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def _script_of(ch: str) -> str | None:
    cp = ord(ch)
    if not ch.isalpha():
        # ZWNJ is a strong Persian signal although not a letter
        if cp == 0x200C:
            return "arabic"
        return None
    if (
        0x41 <= cp <= 0x5A or 0x61 <= cp <= 0x7A
        or 0xC0 <= cp <= 0x24F or 0x1E00 <= cp <= 0x1EFF
        or 0x2C60 <= cp <= 0x2C7F or 0xA720 <= cp <= 0xA7FF
    ):
        return "latin"
    if 0x590 <= cp <= 0x5FF:
        return "hebrew"
    if (
        0x600 <= cp <= 0x6FF or 0x750 <= cp <= 0x77F
        or 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF
    ):
        return "arabic"
    if 0x370 <= cp <= 0x3FF or 0x1F00 <= cp <= 0x1FFF:
        return "greek"
    if 0x400 <= cp <= 0x4FF or 0x500 <= cp <= 0x52F:
        return "cyrillic"
    if 0x530 <= cp <= 0x58F:
        return "armenian"
    if 0x10A0 <= cp <= 0x10FF:
        return "georgian"
    if 0x900 <= cp <= 0x97F:
        return "devanagari"
    if 0x980 <= cp <= 0x9FF:
        return "bengali"
    if 0xA00 <= cp <= 0xA7F:
        return "gurmukhi"
    if 0xA80 <= cp <= 0xAFF:
        return "gujarati"
    if 0xB80 <= cp <= 0xBFF:
        return "tamil"
    if 0xC00 <= cp <= 0xC7F:
        return "telugu"
    if 0xC80 <= cp <= 0xCFF:
        return "kannada"
    if 0xD00 <= cp <= 0xD7F:
        return "malayalam"
    if 0xE00 <= cp <= 0xE7F:
        return "thai"
    if 0xE80 <= cp <= 0xEFF:
        return "lao"
    if 0x1000 <= cp <= 0x109F:
        return "myanmar"
    if 0x1200 <= cp <= 0x137F:
        return "ethiopic"
    if 0x1780 <= cp <= 0x17FF:
        return "khmer"
    if _in_ranges(cp, _HANGUL_RANGES):
        return "hangul"
    if _in_ranges(cp, _KANA_RANGES):
        return "kana"
    if _in_ranges(cp, _HAN_RANGES):
        return "han"
    return None


# ------------------------------------------------------------------ latin langs
# lang -> (distinctive letters, very common words)
_LATIN_LANGS: dict[str, tuple[set[str], set[str]]] = {
    "Turkish": (
        set("ıİğşĞŞçÇöÖüÜ"),
        {"ve", "bir", "için", "değil", "nasıl", "nedir", "merhaba", "evet",
         "hayır", "teşekkür", "talep", "fiyat", "lütfen"},
    ),
    "Spanish": (
        set("ñÑ¿¡"),
        {"que", "de", "el", "es", "por", "para", "como", "gracias", "hola",
         "cuánto", "cuanto", "precio", "días", "deseo", "puedo"},
    ),
    "French": (
        set("éèêàçùîôœÉÈ"),
        {"le", "la", "les", "est", "des", "vous", "je", "pour", "bonjour",
         "merci", "prix", "combien", "peux", "s'il"},
    ),
    "German": (
        set("äöüßÄÖÜ"),
        {"der", "die", "das", "und", "ist", "nicht", "ich", "für", "hallo",
         "danke", "preis", "wie", "viele", "können", "möchte"},
    ),
    "Portuguese": (
        set("ãõÃÕâêÂÊçÇ"),
        {"não", "você", "uma", "que", "para", "obrigado", "olá", "preço",
         "como", "está", "quero", "pode"},
    ),
    "Italian": (
        set("àèìòùÀÈÌÒÙ"),
        {"il", "che", "di", "non", "per", "sono", "ciao", "grazie", "prezzo",
         "come", "quanto", "voglio", "può"},
    ),
    "Dutch": (
        set(),
        {"de", "het", "een", "niet", "van", "ik", "is", "dat", "hallo",
         "dank", "prijs", "hoeveel", "wil", "kunt"},
    ),
    "Polish": (
        set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"),
        {"nie", "jest", "się", "dziękuję", "cześć", "ile", "chcę", "można"},
    ),
    "Romanian": (
        set("ăâîșțĂÂÎȘȚ"),
        {"și", "este", "nu", "pentru", "mulțumesc", "bună", "preț", "cât"},
    ),
    "Vietnamese": (
        set("ăâđêôơưĂĐÊÔƠƯ"),
        {"không", "của", "là", "và", "cảm", "ơn", "giá", "bao", "nhiêu",
         "tôi", "muốn", "xin", "chào", "cái", "này", "gì", "ạ", "ừ",
         "bạn", "cho", "biết", "được", "tốn", "phí"},
    ),
    "Indonesian": (
        set(),
        {"yang", "dan", "tidak", "saya", "apa", "adalah", "bisa", "berapa",
         "harga", "mau", "terima", "kasih"},
    ),
}

_WORD_SPLIT = re.compile(r"[^\w']+", re.UNICODE)


def _latin_language(text: str) -> str:
    words = [w.lower() for w in _WORD_SPLIT.split(text) if w]
    scores: dict[str, int] = {}
    for lang, (letters, vocab) in _LATIN_LANGS.items():
        score = 0
        for ch in text:
            if ch in letters:
                score += 3
        for w in words:
            if w in vocab:
                score += 2
        if score:
            scores[lang] = score
    # Vietnamese-only diacritics (ạ ả ấ ầ ... ợ ự ữ) are a dead giveaway
    vi_specific = sum(1 for ch in text if 0x1EA0 <= ord(ch) <= 0x1EF9)
    if vi_specific:
        scores["Vietnamese"] = scores.get("Vietnamese", 0) + vi_specific * 4
    if not scores:
        return "English"
    best = max(scores.items(), key=lambda kv: kv[1])
    # a single shared word (like "de") is not enough — require a solid signal
    if best[1] < 4:
        return "English"
    return best[0]


def _arabic_script_language(text: str) -> str:
    per = sum(1 for ch in text if ch in _PERSIAN_MARKERS)
    urd = sum(1 for ch in text if ch in _URDU_MARKERS)
    if per >= urd and per > 0:
        return "Persian"
    if urd > 0:
        return "Urdu"
    return "Arabic"


def _cyrillic_language(text: str) -> str:
    # Ukrainian/Belarusian share most letters with Russian; use exclusive ones
    if any(ch in text for ch in "їєґЇЄҐ"):
        return "Ukrainian"
    if "ў" in text:
        return "Belarusian"
    if any(ch in text for ch in "әғңөұүһіӘҒҢӨҰҮҺІ"):
        return "Kazakh"
    return "Russian"


def _cjk_language(counter: dict[str, int]) -> str:
    if counter.get("kana", 0) > 0:
        return "Japanese"
    if counter.get("hangul", 0) > 0:
        return "Korean"
    return "Chinese"


# --------------------------------------------------------------------- public
def detect_language(text: str | None) -> str | None:
    """Best-effort language NAME (English) of ``text``; None when unsure.

    Mixed-language input resolves to the dominant script.
    """
    if not text or not text.strip():
        return None

    counter: dict[str, int] = {}
    for ch in text:
        script = _script_of(ch)
        if script:
            counter[script] = counter.get(script, 0) + 1

    if not counter:
        return None

    # dominant script (but a handful of stray latin chars should not beat
    # a whole Persian sentence, hence simple max on counts)
    script = max(counter.items(), key=lambda kv: kv[1])[0]

    if script == "arabic":
        return _arabic_script_language(text)
    if script == "latin":
        return _latin_language(text)
    if script == "cyrillic":
        return _cyrillic_language(text)
    if script in ("han", "kana", "hangul"):
        return _cjk_language(counter)

    names = {
        "hebrew": "Hebrew",
        "greek": "Greek",
        "armenian": "Armenian",
        "georgian": "Georgian",
        "devanagari": "Hindi",
        "bengali": "Bengali",
        "gurmukhi": "Punjabi",
        "gujarati": "Gujarati",
        "tamil": "Tamil",
        "telugu": "Telugu",
        "kannada": "Kannada",
        "malayalam": "Malayalam",
        "thai": "Thai",
        "lao": "Lao",
        "myanmar": "Burmese",
        "ethiopic": "Amharic",
        "khmer": "Khmer",
    }
    return names.get(script)


# Persian names for the languages we can name (used inside the prompt so the
# model sees the language in BOTH tongues — this measurably boosts compliance).
LANG_FA: dict[str, str] = {
    "Persian": "فارسی",
    "Arabic": "عربی",
    "Urdu": "اردو",
    "English": "انگلیسی",
    "Turkish": "ترکی",
    "Spanish": "اسپانیایی",
    "French": "فرانسوی",
    "German": "آلمانی",
    "Portuguese": "پرتغالی",
    "Italian": "ایتالیایی",
    "Dutch": "هلندی",
    "Polish": "لهستانی",
    "Romanian": "رومانیایی",
    "Vietnamese": "ویتنامی",
    "Indonesian": "اندونزیایی",
    "Russian": "روسی",
    "Ukrainian": "اوکراینی",
    "Belarusian": "بلاروسی",
    "Kazakh": "قزاقی",
    "Hebrew": "عبری",
    "Greek": "یونانی",
    "Armenian": "ارمنی",
    "Georgian": "گرجی",
    "Hindi": "هندی",
    "Bengali": "بنگالی",
    "Punjabi": "پنجابی",
    "Gujarati": "گجراتی",
    "Tamil": "تامیلی",
    "Telugu": "تلوگو",
    "Kannada": "کانادا",
    "Malayalam": "مالایالم",
    "Thai": "تایلندی",
    "Lao": "لائوسی",
    "Burmese": "برمه‌ای",
    "Amharic": "امهری",
    "Khmer": "خمری",
    "Japanese": "ژاپنی",
    "Korean": "کره‌ای",
    "Chinese": "چینی",
}


def lang_fa(name: str | None) -> str:
    if not name:
        return ""
    return LANG_FA.get(name, name)
