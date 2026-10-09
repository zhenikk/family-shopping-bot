"""Thread-safe, bounded operational samples; no message or user content."""
from collections import deque
import math
import threading
import time

class VoiceMetrics:
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.lock=threading.Lock()
        self.waiting={}
        self.active=0
        self.accepted=self.completed=self.rejected=self.failed=0
        self.waits=deque(maxlen=512)
        self.processing=deque(maxlen=512)

    def enqueue(self):
        token=object()
        with self.lock:
            self.waiting[token]=self.clock()
            self.accepted+=1
        return token

    def reject(self):
        with self.lock:self.rejected+=1

    def start(self, token):
        with self.lock:
            now=self.clock()
            self.waits.append(max(0,now-self.waiting.pop(token)))
            self.active+=1
        return now

    def finish(self, started, failed=False):
        with self.lock:
            self.active-=1
            self.completed+=1
            self.failed+=bool(failed)
            self.processing.append(max(0,self.clock()-started))

    def cancel(self,token):
        with self.lock:
            self.waiting.pop(token,None)
            self.failed+=1

    def snapshot(self):
        def stats(values):
            values=sorted(values)
            if not values:return {'samples':0,'p50_ms':None,'p95_ms':None}
            return {'samples':len(values),'p50_ms':round(values[(len(values)-1)//2]*1000),'p95_ms':round(values[max(0,math.ceil(len(values)*.95)-1)]*1000)}
        with self.lock:
            return dict(workers=1,waiting=len(self.waiting),active=self.active,oldest_wait_ms=round(max([0]+[self.clock()-t for t in self.waiting.values()])*1000),accepted=self.accepted,completed=self.completed,rejected=self.rejected,failed=self.failed,wait=stats(self.waits),processing=stats(self.processing))
