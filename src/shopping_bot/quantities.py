"""Conservative quantity prefixes; packaging stays in the editable note."""
import re
from .product_names import LOOKUP, normalized_name

NUMBERS = {'один':'1','одна':'1','одне':'1','одну':'1','два':'2','дві':'2','три':'3','чотири':'4','п’ять':'5',"п'ять":'5','шість':'6','сім':'7','вісім':'8','дев’ять':'9','десять':'10','one':'1','two':'2','three':'3','four':'4','five':'5'}
UNITS = {
    'буханка':'буханки','буханку':'буханки','буханки':'буханки','буханок':'буханок',
    'пачка':'пачки','пачку':'пачки','пачки':'пачки','пачок':'пачок',
    'упаковка':'упаковки','упаковку':'упаковки','упаковки':'упаковки',
    'пляшка':'пляшки','пляшку':'пляшки','пляшки':'пляшки',
    'контейнер':'контейнер','контейнери':'контейнери',
    'літр':'л','літра':'л','літри':'л','літрів':'л','л':'л',
    'кілограм':'кг','кілограми':'кг','кілограмів':'кг','кг':'кг','грам':'г','грамів':'г','г':'г',
    'шт':'шт.','штуки':'шт.','штук':'шт.','pack':'packs','packs':'packs',
    'loaf':'loaves','loaves':'loaves','bottle':'bottles','bottles':'bottles','litre':'l','litres':'l','kg':'kg','g':'g',
}

def quantity_note(name, note=None):
    words = name.strip().split()
    if not words:
        return name, note
    first = words[0].casefold()
    amount = NUMBERS.get(first, first if re.fullmatch(r'\d+(?:[.,]\d+)?', first) else None)
    unit = None
    if amount and len(words) > 1:
        words.pop(0)
        unit = UNITS.get(words[0].casefold().rstrip('.'))
        if unit:
            words.pop(0)
    elif first in UNITS and len(words) > 1:
        amount, unit = '1', UNITS[first]
        words.pop(0)
    else:
        return name, note
    if not words:
        return name, note
    if unit and words and words[0].casefold() == 'of':
        words.pop(0)
    if not words:
        return name, note
    base = re.sub(r'\s+без\s+(?:лактози|глютену|цукру)$', '', ' '.join(words), flags=re.I)
    if unit is None and normalized_name(base) not in LOOKUP:
        return name, note
    if amount == '1':
        unit = {'буханки':'буханка', 'пачки':'пачка', 'упаковки':'упаковка', 'пляшки':'пляшка', 'packs':'pack', 'loaves':'loaf', 'bottles':'bottle'}.get(unit, unit)
    quantity = amount + ' ' + (unit or ('pcs' if re.search('[a-z]', name, re.I) else 'шт.'))
    return ' '.join(words), '; '.join(value for value in (quantity, note) if value)

def merge_note(incoming, existing):
    if not incoming:
        return existing or ''
    # A new quantity replaces only the old quantity, retaining descriptive notes.
    prefix = re.compile(r'^\d+(?:[.,]\d+)?\s+(?:' + '|'.join(re.escape(x) for x in set(UNITS.values()) | {'pcs', 'буханка', 'пачка', 'упаковка', 'пляшка', 'pack', 'loaf', 'bottle'}) + r')(?=;|$)\s*;?\s*', re.I)
    if prefix.match(incoming):
        previous = prefix.sub('', existing or '')
        if previous and previous not in incoming:
            combined = incoming + '; ' + previous
            return combined if len(combined) <= 200 else incoming
    return incoming


def product_variant(name, note=None):
    """Dietary requirements distinguish products, unlike packaging or store notes."""
    pattern = r'\b(?:без\s+(?:лактози|глютену|цукру)|lactose[- ]free|gluten[- ]free|sugar[- ]free)\b'
    modifiers = re.findall(pattern, note or '', flags=re.I)
    for modifier in modifiers:
        if modifier.casefold() not in name.casefold():
            name += ' ' + modifier.casefold()
    if modifiers:
        note = re.sub(pattern, '', note, flags=re.I)
        note = re.sub(r'\s*;\s*', '; ', note).strip(' ;,') or None
    return name, note
