from chronicle.ingest.cache import DiskCache, cache_key


def test_disk_cache_hit_miss_and_persistence(tmp_path):
    c = DiskCache(tmp_path)
    k = cache_key("model", "v1", "text")
    assert c.get(k) is None and c.misses == 1
    c.put(k, {"claims": []})
    assert c.get(k) == {"claims": []} and c.hits == 1
    assert DiskCache(tmp_path).get(k) == {"claims": []}


def test_cache_key_depends_on_every_part():
    assert cache_key("a", "b") != cache_key("ab", "")
    assert cache_key("m", "v1", "t") != cache_key("m", "v2", "t")


def test_corrupt_entry_is_a_miss(tmp_path):
    c = DiskCache(tmp_path)
    k = cache_key("x")
    c.put(k, 1)
    c._path(k).write_text("{not json")
    assert c.get(k) is None
