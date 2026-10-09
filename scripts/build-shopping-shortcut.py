"""Build a secret-free Apple Shortcuts template; sign with macOS shortcuts sign."""
import plistlib
from pathlib import Path

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
  action('recordaudio',WFRecordingCompression='Normal',WFRecordingStart='Immediately',WFRecordingEnd='On Tap',UUID=AUDIO),
  action('downloadurl', UUID=HTTP, WFURL='https://shopping.taranets.dev/shortcuts/audio',WFHTTPMethod='POST',WFHTTPBodyType='File',
   WFRequestVariable={'WFSerializationType':'WFTextTokenAttachment','Value':ref(AUDIO,'Recorded Audio')},
   WFFormValues={'WFSerializationType':'WFDictionaryFieldValue','Value':{'WFDictionaryFieldValueItems':[]}},
   WFHTTPHeaders={'WFSerializationType':'WFDictionaryFieldValue','Value':{'WFDictionaryFieldValueItems':[
    {'WFItemType':0,'WFKey':token('Authorization'),'WFValue':{'WFSerializationType':'WFTextTokenString','Value':{'string':'\ufffc','attachmentsByRange':{'{0, 1}':ref(AUTH,'Text')}}}},
    {'WFItemType':0,'WFKey':token('Content-Type'),'WFValue':token('audio/mp4')}
   ]}}),
  action('showresult',Text='\ufffc',WFInput={'WFSerializationType':'WFTextTokenAttachment','Value':ref(HTTP,'Contents of URL')}),
 ]}
# HTTP result is shown verbatim: never claim "queued" on an error response.
workflow['WFWorkflowActions'][-1] = action('showresult', Text={'WFSerializationType':'WFTextTokenString','Value':{'string':'\ufffc','attachmentsByRange':{'{0, 1}':ref(HTTP,'Contents of URL')}}})
out=Path('/private/tmp/Shopping-unsigned.shortcut');out.write_bytes(plistlib.dumps(workflow,fmt=plistlib.FMT_BINARY))
print(out)
