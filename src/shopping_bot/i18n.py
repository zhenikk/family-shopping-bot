"""Translate only source-code UI templates, never user content."""
import json
from contextvars import ContextVar
from pathlib import Path
language = ContextVar('shopping_language', default='uk')
MESSAGES = json.loads(Path(__file__).with_name('messages.json').read_text())
EN = json.loads(Path(__file__).with_name('translations.json').read_text())
PAIRS = sorted(EN.items(), key=lambda pair: len(pair[0]), reverse=True)

def tr(text):
    text=MESSAGES.get(text,text)
    if language.get() != 'en':
        return text
    if text in EN:
        return EN[text]
    # Template fragments may combine an emoji, whitespace and multiple labels.
    import re
    return re.sub('|'.join(re.escape(key) for key,_ in PAIRS),lambda match: EN[match[0]],text)

class CategoryLabels(dict):
    def __getitem__(self,key):
        return tr(super().__getitem__(key))
    def get(self,key,default=None):
        value=super().get(key,default)
        return tr(value) if isinstance(value,str) else value
    def items(self):
        return ((key,tr(value)) for key,value in super().items())
