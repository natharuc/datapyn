"""Bounded immutable figure snapshots, owned by one kernel result store."""

from collections import OrderedDict
import json
import uuid
from weakref import WeakKeyDictionary

MAX_CHARTS = 8
MAX_CHART_BYTES = 16 * 1024 * 1024
_stores = WeakKeyDictionary()


def capture(store, response):
    content = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(content) > MAX_CHART_BYTES:
        raise ValueError("Chart preview exceeds 16 MiB; reduce its series or labels")
    cache = _stores.setdefault(store, OrderedDict())
    while cache and (len(cache) >= MAX_CHARTS or sum(len(item) for item in cache.values()) + len(content) > MAX_CHART_BYTES):
        cache.popitem(last=False)
    identifier = uuid.uuid4().hex
    cache[identifier] = content
    return {**response, "chart_id": identifier}


def get(store, identifier):
    cache = _stores.get(store, {})
    if not isinstance(identifier, str) or identifier not in cache:
        raise ValueError("Chart preview expired or belongs to another session; generate the chart again")
    return {**json.loads(cache[identifier]), "chart_id": identifier}
