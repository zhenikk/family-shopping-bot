"""Bounded Groq audio transcription; credentials read only from a secret file."""
import json
import os
import uuid
import urllib.request
from pathlib import Path

def transcribe_audio(wav, language, prompt=''):
    key=Path(os.environ['GROQ_API_KEY_FILE']).read_text().strip()
    if not key:raise ValueError('Groq key missing')
    audio=Path(wav).read_bytes()
    if len(audio)>4_000_000:raise ValueError('Audio too large')
    boundary='shopping-'+uuid.uuid4().hex
    parts=[]
    for name,value in [('model','whisper-large-v3-turbo'),('language',language),('response_format','json'),('temperature','0'),('prompt',prompt)]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+audio+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    request=urllib.request.Request('https://api.groq.com/openai/v1/audio/transcriptions',data=b''.join(parts),headers={'User-Agent':'FamilyShoppingBot/1.0','Authorization':'Bearer '+key,'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request,timeout=20) as response:raw=response.read(65537)
    if len(raw)>65536:raise ValueError('Transcription response too large')
    text=json.loads(raw).get('text')
    if not isinstance(text,str) or len(text)>12000:raise ValueError('Invalid transcription')
    return text.strip()
