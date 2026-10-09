"""Build a secret-free Apple Shortcuts template; sign with macOS shortcuts sign."""
import plistlib
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--language', choices=('uk', 'en'), default='uk')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
dictation_languages = {'uk': 'uk-UA', 'en': 'en-US'}

AUTH='11111111-1111-4111-8111-111111111111'
AUDIO='22222222-2222-4222-8222-222222222222'
HTTP='33333333-3333-4333-8333-333333333333'
def token(value): return {'WFSerializationType':'WFTextTokenString','Value':{'string':value}}
def ref(uuid, name): return {'Type':'ActionOutput','OutputUUID':uuid,'OutputName':name}
def action(identifier, **params): return {'WFWorkflowActionIdentifier':'is.workflow.actions.'+identifier,'WFWorkflowActionParameters':params}
workflow = {
 'WFWorkflowName':'Shopping','WFWorkflowClientVersion':'2600','WFWorkflowMinimumClientVersion':900,
 'WFWorkflowIcon':{'WFWorkflowIconStartColor':4282601983,'WFWorkflowIconGlyphNumber':59446},
 'WFWorkflowTypes':['NCWidget','WatchKit'], 'WFWorkflowInputContentItemClasses':[],
 'WFWorkflowImportQuestions':[{'ActionIndex':0,'Category':'Parameter','ParameterKey':'WFTextActionText','Text':'Paste your personal Authorization value (Bearer …) from the bot’s Shopping setup. Never share your configured copy.','DefaultValue':'Bearer PASTE_YOUR_PERSONAL_KEY'}],
 'WFWorkflowActions':[
  action('gettext',WFTextActionText='Bearer PASTE_YOUR_PERSONAL_KEY',UUID=AUTH),
  action('dictatetext',WFSpeechLanguage=dictation_languages[args.language],WFDictateTextStopListening='After Pause',UUID=AUDIO),
  action('downloadurl', UUID=HTTP, WFURL='https://shopping.taranets.dev/shortcuts/text',WFHTTPMethod='POST',WFHTTPBodyType='JSON',
   WFJSONValues={'WFSerializationType':'WFDictionaryFieldValue','Value':{'WFDictionaryFieldValueItems':[
    {'WFItemType':0,'WFKey':token('text'),'WFValue':{'WFSerializationType':'WFTextTokenString','Value':{'string':'\ufffc','attachmentsByRange':{'{0, 1}':ref(AUDIO,'Dictated Text')}}}}
   ]}},
   WFHTTPHeaders={'WFSerializationType':'WFDictionaryFieldValue','Value':{'WFDictionaryFieldValueItems':[
    {'WFItemType':0,'WFKey':token('Authorization'),'WFValue':{'WFSerializationType':'WFTextTokenString','Value':{'string':'\ufffc','attachmentsByRange':{'{0, 1}':ref(AUTH,'Text')}}}}
   ]}}),
  action('nothing'),
 ]}
# Discard the API response so Siri does not display technical JSON.
if args.language == 'uk':
 workflow['WFWorkflowImportQuestions'][0]['Text'] = 'Вставте персональне значення Authorization (Bearer …), скопійоване в боті. Не поширюйте налаштовану копію.'
out=args.output or Path('/private/tmp/Shopping-' + args.language + '-unsigned.shortcut');out.write_bytes(plistlib.dumps(workflow,fmt=plistlib.FMT_BINARY))
print(out)
