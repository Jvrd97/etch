# [review:need-review] PHASE-03/271
# summary: the dose net under the health advice — folds the answer (compatibility decomposition, no invisible characters, no accents), then looks for a number or a number word glued to a dose unit or a pharmacy abbreviation, and for fractions of a tablet
"""
The net under «не называй дозу» (`#223`, `#246`, `#251`).

Instruction in the prompt is a request; this module is the check. It answers one
question — does the text name a dose? — and a «yes» is final: such an answer is
not shown, and nothing of it reaches a log.

**Сначала свёртка.** The text is decomposed (NFKD), the invisible characters
(zero width, soft hyphen) and combining marks are dropped, and the letters are
lowered. After it «ё» is «е», «½» is «1/2», fullwidth digits are plain, and
`µ` (micro sign) equals `μ` (Greek mu). The breve of «й» is the one combining
mark that stays (the letter is recomposed): «одной» must keep its ending, or the
most common prescription, «по одной таблетке», slips through. The patterns below
are written for the folded text: no «ё» in them, «й» as it is.

**Что считается дозой.**
- число (с разделителем тысяч, дробью, «тыс.») и единица: «400 мг», «5 тыс. МЕ»,
  «1 табл.», «2 капс.», «10 капель»;
- числительное словом в любом падеже и единица: «двумя капсулами», «по трём
  таблеткам», «пять тысяч единиц»;
- доля упаковки: «полтаблетки», «половину таблетки», «четверть капсулы»;
- единицы бывают латинскими и смешанными («mg», «мg», «ME», «IU»).

**Что не считается.** Одинокая буква «г» — год, если перед ней год или дата
(«в 2026 г.», «12.2026 г.»); шаги, проценты, пульс и минуты не единицы дозы.
Пульс измеряется в «уд/мин» и «ударах» — их защита не считает единицей дозы. «ед» и «единиц»
рядом со словом о пульсе («пульс снизился на 4 единицы», «добавь на 10 ед») — всегда доза:
точечные исключения для шкалы пульса (круги 3–4 `#251`, `#271` круг 1) раз за разом пропускали
2-значные дозы инсулина, поэтому исключение убрано целиком. Сервер такие строки не пишет:
`health_format.py` форматирует пульс только как «N уд/мин». Ложное срабатывание на «единицы
пульса» допустимо: при сомнении ловим дозу.
Известная щель: «2000 г» читается как год, а не как два килограмма.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["names_a_dose"]

# Invisible (Cf: zero width, soft hyphen, word joiner) and combining (Mn) marks.
_DROPPED_CATEGORIES = frozenset({"Cf", "Mn"})
_BREVE = "\u0306"
_I_LETTERS = "иИ"

_FRACTION_SLASH = "⁄"
# «5000», «10 000», «1,5», «1/2», «1⁄2»; not a tail of a longer number, but a number
# glued to the comma that follows a word («утром,400 мг») is still a number.
# «10 000 000 000 000» is far more than any dose; the cap keeps a run of groups linear.
_MAX_THOUSAND_GROUPS = 4
_NUMBER = rf"(?<!\d)(?<!\d[.,])\d+(?: \d{{3}}){{0,{_MAX_THOUSAND_GROUPS}}}(?:[.,/{_FRACTION_SLASH}]\d+)?"
# «5 тыс. МЕ», «5 тысяч единиц».
_THOUSANDS = r"(?:\s*(?:тыс(?:\.|(?!\w))|тысяч\w*))?"

_GRAM_ENDING = r"(?:а|ов|ам|ами|ах|у|ом|е|ы)?"
_UNIT = (
    r"(?:"
    r"[мm][гg]|[мm][кk][гg]|[мm][сc][гg]|[uμ][гg]|[мm][еe]|iu|[мm][лl]|"
    rf"милл?играмм?{_GRAM_ENDING}|микро?грамм?{_GRAM_ENDING}|грамм?{_GRAM_ENDING}|"
    r"гр(?!\w)|"
    r"ед(?:иниц(?:а|ы|у|е|ей|ею|ам|ами|ах)?)?|"
    r"таблет(?:ка|ки|ку|ке|ок|кам|ками|ках|кой|кою)|табл(?!\w)|таб(?!\w)|"
    r"капсул(?:а|ы|у|е|ой|ою|ам|ами|ах)?|капс(?!\w)|"
    r"капл(?:я|и|ю|е|ей|ею|ям|ями|ях)|капель|"
    r"ампул(?:а|ы|у|е|ой|ою|ам|ами|ах)?|пилюл(?:я|и|ю|е|ей|ею|ям|ями|ях|ь)"
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
    kept: list[str] = []
    for ch in unicodedata.normalize("NFKD", text):
        if ch == _BREVE and kept and kept[-1] in _I_LETTERS:
            kept.append(ch)
        elif unicodedata.category(ch) not in _DROPPED_CATEGORIES:
            kept.append(ch)
    return unicodedata.normalize("NFC", "".join(kept)).casefold()


def names_a_dose(text: str) -> bool:
    """True when the text names a dose of anything: a number or a fraction and its unit."""
    folded = _fold(text)
    return _DOSE.search(folded) is not None
