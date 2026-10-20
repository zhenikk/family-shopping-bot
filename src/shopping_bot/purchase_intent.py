"""Conservative explicit purchase commands; never infer completed purchases."""
import re

VERB = r'(?:купив|купила|купили|куплено|bought|purchased|gekauft|eingekauft)'


def purchase_targets(text):
    text = text.strip().rstrip('.!')
    if re.search(r'\b(?:не|not|never|nicht|kein\w*)\s+(?:\w+\s+)?' + VERB + r'\b', text, re.I):
        return ''
    prefix = r'^(?:(?:привіт|hi|hello|hallo)[,! ]+)?(?:(?:я|ми|i|we)\s+)?(?:(?:вже|already|have)\s+)*' + VERB + r'\b[\s,:-]*'
    match = re.match(prefix, text, re.I)
    if match:
        result = text[match.end():]
    else:
        match = re.search(r'\s+(?:вже\s+|already\s+|schon\s+|bereits\s+)?' + VERB + r'$', text, re.I)
        if not match:
            return None
        # German puts the participle last: "Ich habe Milch gekauft".
        result = re.sub(r'^(?:(?:hallo)[,! ]+)?(?:ich|wir)\s+(?:habe|hab|haben)\s+(?:schon\s+|bereits\s+)?', '', text[:match.start()], flags=re.I)
    # Mixed actions and negations require separate messages, never partial execution.
    if re.search(r'\b(?:не|not|купи|купити|buy|remove|прибери|nicht|kein\w*|kauf|kaufe|kaufen)\b', result, re.I):
        return ''
    return re.sub(r'(?:[, ]+і\s+все|[, ]+дякую|[, ]+thanks|[, ]+that.s all|[, ]+danke)$', '', result, flags=re.I).strip()
