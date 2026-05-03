"""SystemLexicon: built-in Chinese TTS pronunciation rules.

Versioned to allow reproduction of past generation configs.
"""

from __future__ import annotations

import re

SYSTEM_LEXICON_VERSION = "1.0.0"

# ── Polyphonic character context rules ─────────────────────────────────────
# Each rule: (pattern, replacement, description)
# Pattern is a regex that matches the polyphonic char in context.

POLYPHONIC_RULES: list[tuple[str, str, str]] = [
    # 了 le / liao
    ("了(?=解|然|无|不|结|断|却|事|得)", "liǎo", "了 as liao in compound words"),
    # 着 zhe / zhao / zhuo
    ("着(?=急|火|凉|迷|魔|陆|地)", "zháo", "着 as zhao (verb result)"),
    ("[衣着]着", "zhuó", "着 as zhuo (attire/land)"),
    # 得 de / dei / de2
    ("得(?=罪|意|逞|手|力|体|当)", "dé", "得 as de2 (obtain/capable)"),
    ("[你谁我他她它那这]得", "děi", "得 as dei (must)"),
    # 地 de / di
    ("[土田场草荒大天心境名各此该该当]地", "dì", "地 as di (ground/place)"),
    # 长 chang / zhang
    ("[增生成校家船队为首]长", "zhǎng", "长 as zhang (grow/elder)"),
    # 行 xing / hang
    ("[银车同本一各内]行", "háng", "行 as hang (profession/row)"),
    ("[发旅出进飞航步爬]行", "xíng", "行 as xing (travel/walk)"),
    # 重 zhong / chong
    ("重(?=新|复|来|叠|合|演|申|返)", "chóng", "重 as chong (repeat)"),
    # 还 huan / hai
    ("[归退交]还", "huán", "还 as huan (return)"),
    # 只 zhi / zhi3
    ("只(?=有|是|要|见|怕|好|得|能|会)", "zhǐ", "只 as zhi3 (only)"),
    # 觉 jue / jiao
    ("[睡]觉", "jiào", "觉 as jiao (sleep)"),
    # 乐 le / yue
    ("[音声器]乐", "yuè", "乐 as yue (music)"),
    # 校 xiao / jiao
    ("校对|校正|校勘", "jiào", "校 as jiao (proofread)"),
    # 率 lv / shuai
    ("[功效利概机速频比几]率", "lǜ", "率 as lv (rate/ratio)"),
    # 会 hui / kuai
    ("会计", "kuài", "会 as kuai (accounting)"),
    # 降 jiang / xiang
    ("投降|降服|降伏", "xiáng", "降 as xiang (surrender)"),
    # 藏 cang / zang
    ("[西]藏", "zàng", "藏 as zang (Tibet)"),
    # 盛 sheng / cheng
    ("盛(?=饭|菜|汤|满|器)", "chéng", "盛 as cheng (fill/hold)"),
    # 传 chuan / zhuan
    ("[自]传", "zhuàn", "传 as zhuan (biography)"),
    # 弹 tan / dan
    ("[子导炸炮]弹", "dàn", "弹 as dan (bullet/bomb)"),
]


# ── Number pronunciation rules ─────────────────────────────────────────────

def normalize_year(text: str) -> str:
    """Convert year numbers 1900-2099 to character-spaced form for TTS clarity.

    2024 -> 2 0 2 4 (so TTS reads each digit individually as a year).
    """
    def _replace(m):
        year = m.group(0)
        return " ".join(year)
    return re.sub(r'(?<!\d)(?:19|20)\d{2}(?!\d)', _replace, text)


def normalize_percentage(text: str) -> str:
    """Convert percentage patterns to readable Chinese form."""
    return re.sub(r'(\d+(?:\.\d+)?)%', r'\1百分之', text)


def normalize_decimal(text: str) -> str:
    """Convert decimal numbers to Chinese reading form."""
    text = re.sub(r'(\d+)\.(\d+)', r'\1点\2', text)
    return text


def normalize_simple_number(text: str) -> str:
    """Convert 4-digit or smaller numbers to Chinese reading."""
    def _replace(m):
        num = m.group(0)
        if len(num) <= 4:
            digits_cn = "零一二三四五六七八九"
            result = "".join(digits_cn[int(d)] for d in num)
            return result
        return num
    return re.sub(r'(?<!\d)\d{1,4}(?!\d)', _replace, text)


# ── Unit normalization ─────────────────────────────────────────────────────

UNIT_MAP: dict[str, str] = {
    "kg": "千克", "g": "克", "cm": "厘米", "mm": "毫米",
    "km": "千米", "m": "米", "ml": "毫升", "L": "升",
    "℃": "摄氏度", "°C": "摄氏度", "°F": "华氏度",
    "㎡": "平方米", "m²": "平方米", "km²": "平方千米",
}


def normalize_units(text: str) -> str:
    """Replace common measurement units with Chinese readings."""
    for unit, reading in UNIT_MAP.items():
        text = text.replace(unit, reading)
    return text


# ── Common web novel abbreviation mapping ──────────────────────────────────

ABBREVIATION_MAP: dict[str, str] = {
    "AB": "AB",
    # Common Chinese internet abbreviations that TTS should read in full
    "YYDS": "永远的神",
    "yyds": "永远的神",
    "NB": "牛",
    "nb": "牛逼",
    "GG": "哥哥",
    "MM": "妹妹",
}


def normalize_abbreviations(text: str) -> str:
    """Replace known abbreviations with TTS-friendly Chinese."""
    for abbr, reading in ABBREVIATION_MAP.items():
        # Only replace standalone abbreviations (surrounded by non-alpha chars)
        text = re.sub(rf'(?<![a-zA-Z]){re.escape(abbr)}(?![a-zA-Z])', reading, text)
    return text


# ── English in Chinese text ─────────────────────────────────────────────────

def normalize_english_in_chinese(text: str) -> str:
    """Wrap short English segments so TTS reads them as individual letters."""
    def _replace(m):
        word = m.group(0)
        if len(word) <= 4 and word.isalpha() and word.isascii():
            return " ".join(word.upper())
        return word
    # Match English words between Chinese characters
    return re.sub(
        r'(?<=[一-鿿])[a-zA-Z]{1,4}(?=[一-鿿，。！？、；：“”‘’）\)】》])',
        _replace, text,
    )


# ── Punctuation normalization for TTS ───────────────────────────────────────

def normalize_punctuation_for_tts(text: str) -> str:
    """Ensure Chinese punctuation is used for TTS-friendly pauses."""
    text = text.replace("...", "…")
    text = text.replace("--", "——")
    # Replace English punctuation between Chinese text with Chinese equivalents
    text = re.sub(r'(?<=[一-鿿]),(?=[一-鿿])', "，", text)
    text = re.sub(r'(?<=[一-鿿])\.(?=[一-鿿])', "。", text)
    return text


def apply_polyphonic_rules(text: str) -> str:
    """Apply polyphonic character disambiguation rules.

    Each rule only fires once per position because the replacement is pinyin
    (ASCII), and rules require CJK context via their regex patterns.
    Applying twice is safe — already-converted positions won't re-match.
    """
    for pattern, replacement, _desc in POLYPHONIC_RULES:
        text = re.sub(pattern, replacement, text)
    return text


def _make_polyphonic_rules_idempotent():
    """Ensure polyphonic rules won't re-match their own output.

    Adds a negative lookbehind for ASCII to each pattern so that
    already-converted pinyin doesn't trigger re-processing.
    """
    global POLYPHONIC_RULES
    updated = []
    for pattern, replacement, desc in POLYPHONIC_RULES:
        if not pattern.startswith("(?<!"):
            pattern = "(?<![a-zA-Z])" + pattern
        updated.append((pattern, replacement, desc))
    POLYPHONIC_RULES = list(updated)


_make_polyphonic_rules_idempotent()


# ── Apply all rules ─────────────────────────────────────────────────────────

def apply_system_rules(text: str) -> str:
    """Apply all SystemLexicon rules to normalize text for TTS.

    Polyphonic rules run FIRST on the original Chinese text to avoid
    collisions with text inserted by normalization (e.g. 百分之 from %).
    """
    text = apply_polyphonic_rules(text)
    text = normalize_year(text)
    text = normalize_percentage(text)
    text = normalize_decimal(text)
    text = normalize_units(text)
    text = normalize_abbreviations(text)
    text = normalize_english_in_chinese(text)
    text = normalize_punctuation_for_tts(text)
    return text


def get_version() -> str:
    return SYSTEM_LEXICON_VERSION
