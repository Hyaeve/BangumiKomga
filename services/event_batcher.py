"""Coalesce scan events without dropping books that arrive during a refresh."""
import threading
import time


class EventBatcher:
    def __init__(self, dispatch, quiet_seconds=3, max_wait=30):
        self.dispatch = dispatch
        self.quiet_seconds, self.max_wait = quiet_seconds, max_wait
        self.pending = {}
        self.lock = threading.RLock()
        self.timer = None
        self.closed = False

    def add(self, event, now=None):
        data = event["event_data"]
        key = (data.get("libraryId"), data.get("seriesId") or data.get("id"))
        if not all(key):
            return
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.closed:
                return
            old = self.pending.get(key)
            # A metadata change must not downgrade a pending newly-added book.
            chosen = old[0] if old and event["event_type"] == "SeriesChanged" else event
            self.pending[key] = (chosen, old[1] if old else now, now)
            if self.timer is None:
                self.timer = threading.Timer(self.quiet_seconds, self.flush)
                self.timer.daemon = True
                self.timer.start()

    def flush(self, force=False, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.closed:
                return
            if self.timer:
                self.timer.cancel()
                self.timer = None
            ready = [key for key, (_, first, last) in self.pending.items()
                     if force or now-last >= self.quiet_seconds or now-first >= self.max_wait]
            events = [self.pending.pop(key)[0] for key in ready]
            if self.pending:
                self.timer = threading.Timer(self.quiet_seconds, self.flush)
                self.timer.daemon = True
                self.timer.start()
        for event in events:
            self.dispatch(event)

    def close(self):
        with self.lock:
            self.closed = True
            if self.timer:
                self.timer.cancel()
            self.pending.clear()
