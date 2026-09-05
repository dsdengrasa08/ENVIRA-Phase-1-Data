"""Bounded, run-scoped access to decoded page images.

Image-dependent stages historically decoded the same PNG independently.  This
cache shares immutable NumPy arrays between those stages while bounding memory
by bytes rather than by document length.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

import numpy as np


class PageImageCache:
    """Byte-bounded LRU cache for RGB and grayscale page arrays."""

    def __init__(self, max_bytes: int = 128 * 1024 * 1024):
        self.max_bytes = max(0, int(max_bytes))
        self._images: OrderedDict[tuple[str, str], np.ndarray] = OrderedDict()
        self.bytes = 0
        self.peak_bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def load(self, path: str | Path, mode: str = "L") -> np.ndarray | None:
        resolved = str(Path(path).resolve())
        key = (resolved, mode)
        cached = self._images.pop(key, None)
        if cached is not None:
            self._images[key] = cached
            self.hits += 1
            return cached
        self.misses += 1
        try:
            from PIL import Image

            with Image.open(resolved) as source:
                image = np.asarray(source.convert(mode)).copy()
        except (FileNotFoundError, OSError, ValueError):
            return None
        image.setflags(write=False)
        if self.max_bytes and image.nbytes <= self.max_bytes:
            while self._images and self.bytes + image.nbytes > self.max_bytes:
                _, evicted = self._images.popitem(last=False)
                self.bytes -= evicted.nbytes
                self.evictions += 1
            self._images[key] = image
            self.bytes += image.nbytes
            self.peak_bytes = max(self.peak_bytes, self.bytes)
        return image

    def clear(self) -> None:
        self._images.clear()
        self.bytes = 0

    def diagnostics(self) -> dict[str, int]:
        return {
            "max_bytes": self.max_bytes,
            "resident_bytes": self.bytes,
            "peak_bytes": self.peak_bytes,
            "resident_images": len(self._images),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
        }


_CURRENT: ContextVar[PageImageCache | None] = ContextVar("page_image_cache", default=None)


def load_page_image(path: str | Path, mode: str = "L") -> np.ndarray | None:
    cache = _CURRENT.get()
    if cache is not None:
        return cache.load(path, mode)
    return PageImageCache(max_bytes=0).load(path, mode)


@contextmanager
def bind_page_image_cache(max_bytes: int = 128 * 1024 * 1024) -> Iterator[PageImageCache]:
    cache = PageImageCache(max_bytes=max_bytes)
    token = _CURRENT.set(cache)
    try:
        yield cache
    finally:
        _CURRENT.reset(token)
        cache.clear()
