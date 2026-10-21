"""Small, versioned cache for reservation read results only."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from threading import Lock
from time import monotonic

_cache = OrderedDict()
_lock = Lock()
_load_locks = [Lock() for _ in range(16)]
TTL = 60
MAX_ITEMS = 128
MAX_BYTES = 8 * 1024 * 1024
MAX_ITEM_BYTES = 1024 * 1024


def cached(key, load):
    with _load_locks[hash(key) % len(_load_locks)]:
        with _lock:
            item = _cache.get(key)
            if item and item[0] > monotonic():
                _cache.move_to_end(key)
                return deepcopy(item[1])
        value = load()
        size = len(json.dumps(value, default=str, ensure_ascii=False).encode())
        if size <= MAX_ITEM_BYTES:
            with _lock:
                for old in list(_cache):
                    if _cache[old][0] <= monotonic():
                        del _cache[old]
                _cache[key] = (monotonic() + TTL, deepcopy(value), size)
                _cache.move_to_end(key)
                while len(_cache) > MAX_ITEMS or sum(x[2] for x in _cache.values()) > MAX_BYTES:
                    _cache.popitem(last=False)
        return value


class ReservationReads:
    """Preserve the route's SQL and bound parameters; reuse each result separately.

    Coverage/version is always read directly before constructing this adapter.
    Pagination parameters affect only the detail query, so charts are reusable.
    """
    def __init__(self, db, coverage):
        self.db = db
        day = datetime.now(timezone(timedelta(hours=8))).date()
        self.namespace = (db.get_bind(), str(day), json.dumps(dict(coverage), default=str, sort_keys=True))

    def execute(self, statement, params=None):
        return _Read(self, statement, params or {})


class _Read:
    def __init__(self, reads, statement, params):
        self.reads, self.statement, self.params = reads, statement, params

    def mappings(self):
        return self

    def _load(self, kind):
        key = (*self.reads.namespace, str(self.statement),
               json.dumps(self.params, default=str, sort_keys=True), kind)
        def query():
            result = self.reads.db.execute(self.statement, self.params)
            if kind == 'scalar':
                return result.scalar_one()
            mappings = result.mappings()
            return dict(mappings.one()) if kind == 'one' else [dict(row) for row in mappings.all()]
        return cached(key, query)

    def one(self):
        return self._load('one')

    def all(self):
        return self._load('all')

    def scalar_one(self):
        return self._load('scalar')
