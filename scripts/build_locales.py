"""Compile translated static templates; user content is interpolated only at runtime.

Ukrainian files are the source. English uses translations.json; German uses
translations.de.json with English as the fallback for any missing key.
"""
import json
import re
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'src'/'shopping_bot'
english=json.loads((root/'translations.json').read_text())
targets={'en':(english,'en-GB',[('index.html','index.en.html'),('app.js','app.en.js'),('admin.html','admin.en.html'),('admin.js','admin.en.js')]),
         'de':({**english,**json.loads((root/'translations.de.json').read_text())},'de-DE',[('index.html','index.de.html'),('app.js','app.de.js')])}
for code,(translations,locale,files) in targets.items():
 pattern=re.compile('|'.join(re.escape(key) for key in sorted(translations,key=len,reverse=True)))
 for source,target in files:
  text=(root/'web'/source).read_text()
  text=pattern.sub(lambda match:translations[match[0]],text)
  if source.endswith('.html'):text=text.replace('lang="uk"',f'lang="{code}"')
  if source.endswith('.js'):text=text.replace("toLocaleString('uk-UA'",f"toLocaleString('{locale}'").replace("toLocaleLowerCase('uk'",f"toLocaleLowerCase('{code}'")
  (root/'web'/target).write_text(text)
