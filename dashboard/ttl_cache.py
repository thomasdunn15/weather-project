"""Tiny in-process TTL cache decorator.

Replaces Streamlit's @st.cache_data for the FastAPI dashboard backend. Keyed on
(args, sorted kwargs); entries expire after `ttl` seconds. Unhashable args
bypass the cache (always recompute) so it degrades safely.
"""
from __future__ import annotations

import functools
import time
from typing import Callable


def ttl_cache(ttl: float) -> Callable:
    def decorator(fn: Callable) -> Callable:
        store: dict = {}   # key -> (value, expires_at)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                key = (args, tuple(sorted(kwargs.items())))
                hash(key)
            except TypeError:
                return fn(*args, **kwargs)   # unhashable args — skip cache
            now = time.monotonic()
            hit = store.get(key)
            if hit is not None and now < hit[1]:
                return hit[0]
            value = fn(*args, **kwargs)
            store[key] = (value, now + ttl)
            return value

        wrapper.cache_clear = store.clear   # type: ignore[attr-defined]
        return wrapper

    return decorator
