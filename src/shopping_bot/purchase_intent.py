"""Conservative explicit purchase commands; never infer completed purchases."""
import re


def purchase_targets(text):
    text = text.strip().rstrip('.!')
    verb = r'(?:купив|купила|купили|куплено|bought|purchased)'
    if re.search(r'\b(?:не|not|never)\s+' + verb + r'\b', text, re.I):
        return ''
    prefix = r'^(?:(?:привіт|hi|hello)[,! ]+)?(?:(?:я|ми|i|we)\s+)?(?:(?:вже|already|have)\s+)*' + verb + r'\b[\s,:-]*'
    match = re.match(prefix, text, re.I)
    if match:
        result = text[match.end():]
    else:
        match = re.search(r'\s+(?:вже\s+|already\s+)?' + verb + r'$', text, re.I)
        if not match:
            return None
        result = text[:match.start()]
    # Mixed actions and negations require separate messages, never partial execution.
    if re.search(r'\b(?:не|not|купи|купити|buy|remove|прибери)\b', result, re.I):
        return ''
    return re.sub(r'(?:[, ]+і\s+все|[, ]+дякую|[, ]+thanks|[, ]+that.s all)$', '', result, flags=re.I).strip()
