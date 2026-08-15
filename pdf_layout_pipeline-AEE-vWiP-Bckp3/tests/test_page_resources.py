from PIL import Image
import numpy as np

from envira_pdf_layout.page_resources import (
    PageImageCache,
    bind_page_image_cache,
    load_page_image,
)


def _image(path, color):
    Image.new("RGB", (10, 10), color).save(path)


def test_page_image_cache_reuses_immutable_decodes(tmp_path):
    path = tmp_path / "page.png"
    _image(path, "white")
    cache = PageImageCache(max_bytes=10_000)

    first = cache.load(path, "L")
    second = cache.load(path, "L")

    assert first is second
    assert first.shape == (10, 10)
    assert not first.flags.writeable
    assert cache.diagnostics()["hits"] == 1
    assert cache.diagnostics()["misses"] == 1


def test_page_image_cache_evicts_to_byte_budget(tmp_path):
    first_path, second_path = tmp_path / "one.png", tmp_path / "two.png"
    _image(first_path, "white")
    _image(second_path, "black")
    cache = PageImageCache(max_bytes=100)

    cache.load(first_path, "L")
    cache.load(second_path, "L")

    assert cache.diagnostics()["resident_images"] == 1
    assert cache.diagnostics()["resident_bytes"] == 100


def test_bound_cache_is_shared_by_stage_loader(tmp_path):
    path = tmp_path / "page.png"
    _image(path, "white")
    with bind_page_image_cache(10_000) as cache:
        assert np.array_equal(load_page_image(path), load_page_image(path))
        assert cache.hits == 1
    assert cache.bytes == 0
