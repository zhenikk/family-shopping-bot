"""Exact offline aliases; keep brands and qualifiers distinct."""
import unicodedata
import re

ALIASES = {
    "сир кисломолочний": ("творог", "творогу", "творожний сир", "кисломолочний сир"),
    "картопля": ("картошка", "картоплю", "картоплі", "картошку", "картофель"),
    "картопля фрі": ("картошка фрі", "картошка фри", "картопля фри", "картофель фри", "фріха", "фриха", "фрі", "фри"),
    "помідори": ("помідор", "помідорів", "помидоры", "помидор", "томати", "томат"),
    "яйця": ("яйце", "яєць", "яйца"),
    "яблука": ("яблуко", "яблук", "яблоки", "яблоко"),
    "мандарини": ("мандарин", "мандаринів", "мандарины"),
    "банани": ("банан", "бананів", "бананы"),
    "хліб": ("хліба", "хлеб"),
    "молоко": ("молока",),
    "морква": ("моркву", "моркви", "морковка", "морковь"),
    "цибуля": ("цибулю", "цибулі", "лук"),
    "огірки": ("огірок", "огірків", "огурцы", "огурец", "огірочки"),
    "сметана": ("сметану", "сметани"),
    "масло": ("масла",),
    "вершки": ("вершків", "сливки"),
    "сир": ("сиру",),
    "курятина": ("курятину", "курятини"),
    "макарони": ("макаронів", "макароны"),
    "чіпси": ("чіпс", "чипсы", "чіпсів"),
    "лимони": ("лимон", "лимонів"),
    "апельсини": ("апельсин", "апельсинів"),
}

ENGLISH_ALIASES = {
    'картопля': ('potato','potatoes'), 'картопля фрі': ('fries','french fries'),
    'помідори': ('tomato','tomatoes'), 'огірки': ('cucumber','cucumbers'),
    'яйця': ('egg','eggs'), 'яблука': ('apple','apples'), 'мандарини': ('mandarin','mandarins'),
    'банани': ('banana','bananas'), 'хліб': ('bread',), 'молоко': ('milk',),
    'морква': ('carrot','carrots'), 'цибуля': ('onion','onions'), 'сметана': ('sour cream',),
    'масло': ('butter',), 'вершки': ('cream',), 'макарони': ('pasta',), 'чіпси': ('chips',),
    'лимони': ('lemon','lemons'), 'апельсини': ('orange','oranges'),
}
for canonical,aliases in ENGLISH_ALIASES.items():
    ALIASES[canonical] = (*ALIASES.get(canonical,()),*aliases)

def normalized_name(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().replace("’", "'").replace("ʼ", "'").split())

LOOKUP = {alias: canonical for canonical, aliases in ALIASES.items() for alias in (canonical, *aliases)}

def canonical_name(name):
    cleaned = " ".join(unicodedata.normalize("NFKC", name).split())
    key = normalized_name(cleaned)
    dietary = re.search(r'\s+(без\s+(?:лактози|глютену|цукру))$', key)
    if dietary:
        base = key[:dietary.start()]
        if base in LOOKUP:
            cleaned = LOOKUP[base] + ' ' + dietary.group(1)
            key = normalized_name(cleaned)
    value = cleaned if re.search(r"[a-z]",key) else LOOKUP.get(key, cleaned)
    return value[:1].upper() + value[1:]


def one_edit(a, b):
    """Exactly one insertion, deletion or replacement; no broad fuzzy matching."""
    if a == b or abs(len(a)-len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a,b)) == 1
    short, long = sorted((a,b), key=len)
    return any(long[:i]+long[i+1:] == short for i in range(len(long)))


def suggested_name(name, catalog=()):
    cleaned=canonical_name(name)
    key=normalized_name(cleaned)
    # Exact known names and qualifiers are never fuzzily collapsed.
    if key in LOOKUP or not re.fullmatch(r"(?:[а-яіїєґ]{6,}|[a-z]{6,})",key):
        return cleaned
    targets={alias: canonical for alias,canonical in LOOKUP.items() if ' ' not in alias and bool(re.search(r'[a-z]',alias))==bool(re.search(r'[a-z]',key))}
    targets.update({normalized_name(value):value for value in catalog if ' ' not in normalized_name(value)})
    matches={canonical_name(alias if re.search(r"[a-z]",key) else value) for alias,value in targets.items() if one_edit(key,alias)}
    return next(iter(matches)) if len(matches)==1 else cleaned


def product_key(name):
    key = normalized_name(name)
    return LOOKUP.get(key, key)
