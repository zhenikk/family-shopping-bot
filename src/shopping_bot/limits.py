"""Bounded, process-local token buckets for public entry points."""
import threading
import time


class RateLimiter:
    def __init__(self, capacity, refill_per_second, *, max_keys=4096, clock=time.monotonic):
        self.capacity = capacity
        self.refill = refill_per_second
        self.max_keys = max_keys
        self.clock = clock
        self.lock = threading.Lock()
        self.buckets = {}

    def allow(self, key):
        now = self.clock()
        with self.lock:
            if key not in self.buckets and len(self.buckets) >= self.max_keys:
                # Keep active identities; a flood must not evict another user's limit.
                idle = self.capacity / self.refill
                self.buckets = {k: v for k, v in self.buckets.items() if now - v[1] < idle}
                if len(self.buckets) >= self.max_keys:
                    return False
            tokens, previous = self.buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + max(0, now - previous) * self.refill)
            accepted = tokens >= 1
            self.buckets[key] = (tokens - 1 if accepted else tokens, now)
            return accepted


class VoiceAdmission:
    """Count running and queued jobs; release only when a job actually finishes."""
    def __init__(self, total=20, per_user=2):
        self.total = total
        self.per_user = per_user
        self.lock = threading.Lock()
        self.users = {}

    def acquire(self, user_id):
        with self.lock:
            if sum(self.users.values()) >= self.total or self.users.get(user_id, 0) >= self.per_user:
                return False
            self.users[user_id] = self.users.get(user_id, 0) + 1
            return True

    def release(self, user_id):
        with self.lock:
            count = self.users[user_id] - 1
            if count:
                self.users[user_id] = count
            else:
                del self.users[user_id]
