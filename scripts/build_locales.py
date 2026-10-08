"""Compile English static templates; user content is interpolated only at runtime."""
import json
import re
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'src'/'shopping_bot'
translations=json.loads((root/'translations.json').read_text())
pattern=re.compile('|'.join(re.escape(key) for key in sorted(translations,key=len,reverse=True)))
for source,target in [('index.html','index.en.html'),('app.js','app.en.js'),('admin.html','admin.en.html'),('admin.js','admin.en.js')]:
 text=(root/'web'/source).read_text()
 text=pattern.sub(lambda match:translations[match[0]],text)
 if source.endswith('.html'):text=text.replace('lang="uk"','lang="en"')
 if source.endswith('.js'):text=text.replace("toLocaleString('uk-UA'","toLocaleString('en-GB'").replace("toLocaleLowerCase('uk'","toLocaleLowerCase('en'")
 (root/'web'/target).write_text(text)
