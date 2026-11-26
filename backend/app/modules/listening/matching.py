"""Compare what was heard with the slide question's expected answers.

Arabic is normalised (diacritics, tatweel, alef/ta marbuta/ya forms, the
article «ال», digits as words) so «الباء» matches «باء» and «3» matches
«ثلاثة». Pure functions, no I/O.
"""

import re

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_NON_WORD = re.compile(r"[^\w\s]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_NUMBER_WORDS = {
    "0": "صفر", "1": "واحد", "2": "اثنين", "3": "ثلاثه", "4": "اربعه", "5": "خمسه",
    "6": "سته", "7": "سبعه", "8": "ثمانيه", "9": "تسعه", "10": "عشره",
}
# Spoken variants that mean the same number.
_SAME = {"اثنان": "اثنين", "ثنين": "اثنين", "ثلاث": "ثلاثه", "اربع": "اربعه", "خمس": "خمسه",
         "ست": "سته", "سبع": "سبعه", "ثمان": "ثمانيه", "ثمانية": "ثمانيه", "تسع": "تسعه", "عشر": "عشره"}


def _word(w: str) -> str:
    if w.isdigit():
        w = _NUMBER_WORDS.get(str(int(w)), w)
    if w.startswith("وال") and len(w) > 4:
        w = w[3:]
    elif w.startswith("ال") and len(w) > 3:
        w = w[2:]
    return _SAME.get(w, w)


def normalize(text: str) -> list[str]:
    t = _DIACRITICS.sub("", text.translate(_DIGITS)).lower()
    t = re.sub("[إأآٱ]", "ا", t).replace("ة", "ه").replace("ى", "ي")
    t = re.sub(r"(\d+)", r" \1 ", _NON_WORD.sub(" ", t))
    return [_word(w) for w in t.split()]


def match(heard: str, expected: list[str]) -> str | None:
    """The first expected answer whose words all appear, in order, in what was heard."""
    words = normalize(heard)
    for answer in expected:
        target = normalize(answer)
        if not target:
            continue
        n = len(target)
        if any(words[i : i + n] == target for i in range(len(words) - n + 1)):
            return answer
    return None
