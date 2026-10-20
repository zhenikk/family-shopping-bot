"""Translate only source-code UI templates, never user content.

Ukrainian is the source language. Each other language has a catalog keyed by the
Ukrainian text: translations.json (English) and translations.<code>.json.
"""
import json
import re
from contextvars import ContextVar
from pathlib import Path

LANGUAGES = ('uk', 'en', 'de')
language = ContextVar('shopping_language', default='uk')
_HERE = Path(__file__).parent
MESSAGES = json.loads((_HERE / 'messages.json').read_text())
EN = json.loads((_HERE / 'translations.json').read_text())
# ponytail: a key missing from a newer catalog falls back to English, never to Ukrainian; tests require full coverage.
CATALOGS = {'en': EN, 'de': {**EN, **json.loads((_HERE / 'translations.de.json').read_text())}}
_PATTERNS = {code: re.compile('|'.join(re.escape(key) for key in sorted(catalog, key=len, reverse=True)))
             for code, catalog in CATALOGS.items()}


def tr(text):
    text = MESSAGES.get(text, text)
    catalog = CATALOGS.get(language.get())
    if catalog is None:
        return text
    if text in catalog:
        return catalog[text]
    # Template fragments may combine an emoji, whitespace and multiple labels.
    return _PATTERNS[language.get()].sub(lambda match: catalog[match[0]], text)


class CategoryLabels(dict):
    def __getitem__(self,key):
        return tr(super().__getitem__(key))
    def get(self,key,default=None):
        value=super().get(key,default)
        return tr(value) if isinstance(value,str) else value
    def items(self):
        return ((key,tr(value)) for key,value in super().items())
