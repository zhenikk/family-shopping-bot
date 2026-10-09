"""Build a standalone ODbL category dictionary from Open Food Facts taxonomy.
Usage: PYTHONPATH=src python scripts/import_food_dictionary.py categories.txt
No user catalogs are read, exported or mixed into the public dictionary.
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from shopping_bot.categories import infer_category, normalize

source = Path(sys.argv[1])
records = {}
for block in re.split(r'\n\s*\n', source.read_text()):
    labels = {}; parents = []
    for line in block.splitlines():
        if line.startswith('< en:'):
            parents.append(normalize(line[5:].strip()))
        match = re.match(r'^(en|uk|pt):\s*(.+)', line)
        if match:
            labels[match[1]] = [v.strip() for v in match[2].split(',') if v.strip()]
    if labels.get('en'):
        records[normalize(labels['en'][0])] = (labels, parents)
roots = {'fruits':'produce','vegetables':'produce','cereals and their products':'pantry',
         'pastas':'pantry','breads':'bakery','dairy products':'dairy','eggs':'dairy',
         'meats':'meat','fishes':'meat','seafood':'meat','beverages':'drinks',
         'snacks':'snacks','confectioneries':'snacks','frozen foods':'frozen',
         'sauces':'spices','spices':'spices','vegetable oils':'spices'}
def category(key, seen=frozenset()):
    if key in roots:
        return roots[key]
    if key in seen or key not in records:
        return 'other'
    labels, parents = records[key]
    direct = infer_category(key)
    if direct != 'other':
        return direct
    inherited = {category(p, seen | {key}) for p in parents} - {'other'}
    return next(iter(inherited)) if len(inherited) == 1 else 'other'
entries = {}; conflicts = set()
for key, (labels, _) in records.items():
    aisle = category(key)
    if aisle == 'other':
        continue
    for names in labels.values():
        for name in names:
            name = normalize(name)
            if not 2 <= len(name) <= 100 or name in conflicts:
                continue
            if name in entries and entries[name] != aisle:
                entries.pop(name); conflicts.add(name)
            else:
                entries[name] = aisle
result = {'source':'https://github.com/openfoodfacts/openfoodfacts-server/blob/main/taxonomies/food/categories.txt',
          'license':'ODbL-1.0','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'languages':['uk','en','pt'],'entries':dict(sorted(entries.items()))}
Path('src/shopping_bot/food_dictionary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('Dictionary entries:', len(entries))
