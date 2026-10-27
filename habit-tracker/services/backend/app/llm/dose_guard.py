# [review:need-review] PHASE-03/251
# summary: the dose net under the health advice — folds the answer (compatibility decomposition, no invisible characters, no accents), then looks for a number or a number word glued to a dose unit or a pharmacy abbreviation, and for fractions of a tablet
"""
The net under «не называй дозу» (`#223`, `#246`, `#251`).

Instruction in the prompt is a request; this module is the check. It answers one
question — does the text name a dose? — and a «yes» is final: such an answer is
not shown, and nothing of it reaches a log.

**Сначала свёртка.** The text is decomposed (NFKD), the invisible characters
(zero width, soft hyphen) and combining marks are dropped, and the letters are
lowered. After it «ё» is «е», «½» is «1/2», fullwidth digits are plain, and
`µ` (micro sign) equals `μ` (Greek mu). The patterns below are written for the
folded text: no «ё» and no «й» in them.

**Что считается дозой.**
- число (с разделителем тысяч, дробью, «тыс.») и единица: «400 мг», «5 тыс. МЕ»,
  «1 табл.», «2 капс.», «10 капель»;
- числительное словом в любом падеже и единица: «двумя капсулами», «по трём
  таблеткам», «пять тысяч единиц»;
- доля упаковки: «полтаблетки», «половину таблетки», «четверть капсулы»;
- единицы бывают латинскими и смешанными («mg», «мg», «ME», «IU»).

**Что не считается.** Одинокая буква «г» — год, если перед ней год или дата
(«в 2026 г.», «12.2026 г.»); шаги, проценты, пульс и минуты не единицы дозы.
Известная щель: «2000 г» читается как год, а не как два килограмма.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["names_a_dose"]

# Invisible (Cf: zero width, soft hyphen, word joiner) and combining (Mn) marks.
_DROPPED_CATEGORIES = frozenset({"Cf", "Mn"})

_FRACTION_SLASH = "⁄"
# «5000», «10 000», «1,5», «1/2», «1⁄2»; not a tail of a longer number, but a number
# glued to the comma that follows a word («утром,400 мг») is still a number.
_NUMBER = rf"(?<!\d)(?<!\d[.,])\d+(?: \d{{3}})*(?:[.,/{_FRACTION_SLASH}]\d+)?"
# «5 тыс. МЕ», «5 тысяч единиц».
_THOUSANDS = r"(?:\s*(?:тыс(?:\.|(?!\w))|тысяч\w*))?"

_GRAM_ENDING = r"(?:а|ов|ам|ами|ах|у|ом|е|ы)?"
_UNIT = (
    r"(?:"
    r"[мm][гg]|[мm][кk][гg]|[мm][сc][гg]|[uμ][гg]|[мm][еe]|iu|[мm][лl]|"
    rf"милл?играмм?{_GRAM_ENDING}|микро?грамм?{_GRAM_ENDING}|грамм?{_GRAM_ENDING}|"
    r"гр(?!\w)|"
    r"ед(?:иниц(?:а|ы|у|е|ей|ам|ами|ах)?)?|"
    r"таблет(?:ка|ки|ку|ке|ок|кам|ками|ках|кой|кою)|табл(?!\w)|таб(?!\w)|"
    r"капсул(?:а|ы|у|е|ой|ою|ам|ами|ах)?|капс(?!\w)|"
    r"капл(?:я|и|ю|ей|ям|ями)|капель|"
    r"ампул(?:а|ы|у|е|ой|ам|ами)|пилюл(?:я|и|ю|ей|ям|ями)"
    r")"
)

# Bare «г»/«g» is a gram, but also the abbreviation of «год»: «в 2026 г.»,
# «12.2026 г.». A year or a month-year in front of it is not a dose.
_YEAR_OR_DATE_BEFORE_G = r"(?:\d{1,2}[./])?(?:19|20)\d{2}\s*[гg](?!\w)"

_NUMBER_WORDS = (
    r"(?:ноль|нуль|"
    r"одн(?:а|у|о|ой|ого|ому|им|ою)|один|"
    r"дв(?:а|е|ух|ум|умя)|тр(?:и|ех|ем|емя)|четыр(?:е|ех|ем|ьмя)|"
    r"пят(?:ь|и|ью)|шест(?:ь|и|ью)|сем(?:ь|и|ью)|восем(?:ь|ью)|восьми|"
    r"девят(?:ь|и|ью)|десят(?:ь|и|ью)|"
    r"(?:одиннадцат|двенадцат|тринадцат|четырнадцат|пятнадцат|шестнадцат|"
    r"семнадцат|восемнадцат|девятнадцат|двадцат|тридцат)(?:ь|и|ью)|"
    r"сорок|сорока|(?:пят|шест|сем|восем)ьдесят|(?:пят|шест|сем|восьм)идесяти|"
    r"девяност[оа]|сто|ста|двест[иь]|двухсот|триста|трехсот|четыреста|четырехсот|"
    r"пятьсот|пятисот|шестьсот|шестисот|семьсот|семисот|восемьсот|восьмисот|"
    r"девятьсот|девятисот|тысяч\w*|полтора|полторы|полутора)"
)

_PACK = r"(?:таблет|капсул|ампул|пилюл)\w*"
_FRACTION_OF_PACK = (
    rf"(?:пол-?{_PACK}"
    rf"|(?:половин\w*|четверть|четверти|четвертин\w*|треть\w*)\s+{_PACK})"
)

_DOSE = re.compile(
    rf"{_NUMBER}{_THOUSANDS}\s*{_UNIT}(?!\w)"
    rf"|(?!{_YEAR_OR_DATE_BEFORE_G}){_NUMBER}\s*[гg](?!\w)"
    rf"|(?<!\w){_NUMBER_WORDS}\s+{_UNIT}(?!\w)"
    rf"|(?<!\w){_FRACTION_OF_PACK}(?!\w)"
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    kept = "".join(
        ch for ch in decomposed if unicodedata.category(ch) not in _DROPPED_CATEGORIES
    )
    return kept.casefold()


def names_a_dose(text: str) -> bool:
    """True when the text names a dose of anything: a number or a fraction and its unit."""
    return _DOSE.search(_fold(text)) is not None
