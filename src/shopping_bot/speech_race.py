"""Bounded first-success race; losing work completes for timing comparison."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import threading
import time
import uuid

POOL=ThreadPoolExecutor(max_workers=3,thread_name_prefix='speech-compare')
LOCAL_SLOT=threading.BoundedSemaphore(1)
LOG=logging.getLogger(__name__)

class LocalBusy(Exception):
    pass

def run_local(function, *, blocking=True):
    if not LOCAL_SLOT.acquire(blocking=blocking):raise LocalBusy()
    try:return function()
    finally:LOCAL_SLOT.release()

def race(local, cloud, record=None):
    started=time.monotonic();lock=threading.RLock();texts={}
    state={'request_id':uuid.uuid4().hex,'occurred':time.time(),'local_ms':None,'groq_ms':None,'local_status':'pending','groq_status':'pending','winner':None,'delivered_ms':None,'agreement':None}
    def publish():
        if record:
            try:record(dict(state))
            except Exception:LOG.warning('Speech benchmark recording unavailable')
    def candidate(provider,function):
        begin=time.monotonic();status='error'
        try:
            text=run_local(function,blocking=False) if provider=='local' else function()
            if not text.strip():raise ValueError('Empty transcription')
            status='ok'
            with lock:texts[provider]=text
            return text
        except LocalBusy:
            status='skipped_busy'
            raise
        finally:
            with lock:
                state[provider+'_ms']=round((time.monotonic()-begin)*1000) if status!='skipped_busy' else None
                state[provider+'_status']=status
                if len(texts)==2:
                    normalize=lambda text:' '.join(''.join(c.casefold() if c.isalnum() else ' ' for c in text).split())
                    state['agreement']=normalize(texts['local'])==normalize(texts['groq'])
                publish()
    futures={POOL.submit(candidate,'local',local):'local',POOL.submit(candidate,'groq',cloud):'groq'}
    for future in as_completed(futures):
        try:text=future.result()
        except Exception:continue
        with lock:
            state['winner']=futures[future];state['delivered_ms']=round((time.monotonic()-started)*1000);publish()
        return text
    raise RuntimeError('Both speech providers unavailable')
