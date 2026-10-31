import research_corpus as corpus


def test_storage_counts_new_database_and_separates_derived_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    root = corpus._user_dir('storage-accuracy')
    (root / 'files' / 'document.txt').write_bytes(b'x' * 11)
    (root / 'files' / 'document.pages.json').write_bytes(b'x' * 7)
    (root / '.embeddings.json').write_bytes(b'x' * 13)
    (root / '.embeddings.json.tmp').write_bytes(b'x' * 3)
    derived = root / 'derived' / 'doc'
    derived.mkdir(parents=True)
    (derived / 'crop.png').write_bytes(b'x' * 5)

    stats = corpus._storage_stats('storage-accuracy')

    assert stats['filesBytes'] == 11
    assert stats['derivedBytes'] == 28
    assert stats['dbBytes'] > 0
    assert stats['totalBytes'] == stats['filesBytes'] + stats['derivedBytes'] + stats['dbBytes']
