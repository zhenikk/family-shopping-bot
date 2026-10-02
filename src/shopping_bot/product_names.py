"""Exact offline aliases; keep brands and qualifiers distinct."""
import unicodedata

ALIASES = {
    "картопля": ("картошка", "картоплю", "картоплі", "картошку", "картофель"),
    "картопля фрі": ("картошка фрі", "картошка фри", "картопля фри", "картофель фри", "фріха", "фриха", "фрі", "фри"),
    "помідори": ("помідор", "помідорів", "помидоры", "помидор", "томати", "томат"),
    "огірки": ("огірок", "огірків", "огурцы", "огурец"),
    "яйця": ("яйце", "яєць", "яйца"),
    "яблука": ("яблуко", "яблук", "яблоки", "яблоко"),
    "мандарини": ("мандарин", "мандаринів", "мандарины"),
    "банани": ("банан", "бананів", "бананы"),
    "хліб": ("хліба", "хлеб"),
    "молоко": ("молока",),
}

def normalized_name(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())

LOOKUP = {alias: canonical for canonical, aliases in ALIASES.items() for alias in (canonical, *aliases)}

def canonical_name(name):
    cleaned = " ".join(unicodedata.normalize("NFKC", name).split())
    key = normalized_name(cleaned)
    canonical = LOOKUP.get(key)
    if canonical and canonical != key:
        return canonical.capitalize() if cleaned[:1].isupper() else canonical
    return cleaned

def product_key(name):
    key = normalized_name(name)
    return LOOKUP.get(key, key)
