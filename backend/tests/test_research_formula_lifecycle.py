import research_corpus as corpus
import research_tables as tables


def test_formula_save_respects_deleted_document_and_table(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(corpus.embed_mod, 'is_configured', lambda: False)
    uid = 'formula-lifecycle'
    doc = corpus._ingest(uid, 'sample.txt', b'sample text ' * 10, 'text/plain', analyze=False)['docId']
    table = tables._create_table(uid, {
        'columns': [{'key': 'A', 'label': 'A', 'type': 'number'}], 'rows': [['1']],
    }, None)['id']
    formula = [{'target': 'A', 'expr': '1'}]
    assert corpus._save_extracted_formulas(uid, doc, table, formula) == 1
    assert tables._delete_table(uid, table)
    assert corpus._save_extracted_formulas(uid, doc, table, formula) == 0
    assert not corpus._list_extracted_formulas(uid, table_id=table)
    assert corpus._delete(uid, doc)
    assert corpus._save_extracted_formulas(uid, doc, '', formula) == 0
    assert not corpus._list_extracted_formulas(uid, doc_id=doc)
    assert corpus._save_source_blocks(uid, doc, 1, formula) == 0
    assert corpus._save_page_blocks(uid, doc, 1, [{'kind': 'printed_text', 'text': 'late'}]) == 0
    conn = corpus._connect(uid)
    try:
        assert conn.execute("SELECT COUNT(*) FROM source_blocks WHERE doc_id = ?", (doc,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_page_reanalysis_preserves_formula_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(corpus.embed_mod, 'is_configured', lambda: False)
    uid = 'page-lifecycle'
    doc = corpus._ingest(uid, 'sample.txt', b'sample text ' * 10, 'text/plain', analyze=False)['docId']
    assert corpus._save_source_blocks(uid, doc, 2, [
        {'target': 'speed', 'expr': 'x/t', 'handwriting': True},
    ]) == 1
    assert corpus._save_page_blocks(uid, doc, 2, [{'kind': 'printed_text', 'text': 'old'}]) == 1
    assert corpus._save_page_blocks(uid, doc, 2, [{'kind': 'printed_text', 'text': 'new'}]) == 1
    conn = corpus._connect(uid)
    try:
        rows = conn.execute(
            "SELECT kind, text FROM source_blocks WHERE doc_id = ? AND page = 2 ORDER BY kind", (doc,),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [('handwriting_formula', 'speed = x/t'), ('printed_text', 'new')]


def test_legacy_source_blocks_survive_schema_migration(tmp_path, monkeypatch):
    import hashlib
    import sqlite3

    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(corpus.embed_mod, 'is_configured', lambda: False)
    uid, data = 'legacy-page', b'sample text ' * 10
    doc = hashlib.sha256(data).hexdigest()[:16]
    with sqlite3.connect(corpus._db_path(uid)) as conn:
        conn.execute(
            "CREATE TABLE source_blocks (id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,"
            " page INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,"
            " latex TEXT NOT NULL, confidence REAL NOT NULL, created_at REAL NOT NULL)"
        )
        conn.execute("INSERT INTO source_blocks VALUES (?,?,?,?,?,?,?,?)",
                     ('old', doc, 2, 'printed_formula', 'legacy', 'x', 0.5, 1.0))
    assert corpus._ingest(uid, 'sample.txt', data, 'text/plain', analyze=False)['docId'] == doc
    assert corpus._save_page_blocks(uid, doc, 2, [{'kind': 'printed_text', 'text': 'new'}]) == 1
    conn = corpus._connect(uid)
    try:
        assert conn.execute(
            "SELECT source_type FROM source_blocks WHERE id = 'old'",
        ).fetchone() == ('legacy',)
    finally:
        conn.close()


def test_duplicate_without_metadata_preserves_existing_details(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(corpus.embed_mod, 'is_configured', lambda: False)
    uid = 'formula-details'
    doc = corpus._ingest(uid, 'sample.txt', b'sample text ' * 10, 'text/plain', analyze=False)['docId']
    original = {'target': 'y', 'expr': 'x', 'variables': ['x'],
                'variableMap': {'x': 'A'}, 'units': {'x': 'm'}, 'handwriting': True}
    assert corpus._save_extracted_formulas(uid, doc, '', [original]) == 1
    assert corpus._save_extracted_formulas(uid, doc, '', [
        {'target': 'y', 'expr': 'x', 'handwriting': False},
    ]) == 0
    saved = corpus._list_extracted_formulas(uid, doc_id=doc)[0]
    assert saved['variables'] == ['x']
    assert saved['variableMap'] == {'x': 'A'}
    assert saved['units'] == {'x': 'm'}
    assert saved['handwriting'] is True


def test_handwriting_metadata_survives_save_and_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(corpus.embed_mod, 'is_configured', lambda: False)
    uid = 'handwriting'
    doc = corpus._ingest(uid, 'sample.txt', b'sample text ' * 10, 'text/plain', analyze=False)['docId']
    printed = {'target': 'A', 'expr': '1', 'handwriting': False}
    assert corpus._save_extracted_formulas(uid, doc, '', [printed]) == 1
    assert corpus._list_extracted_formulas(uid, doc_id=doc)[0]['handwriting'] is False
    assert corpus._save_extracted_formulas(uid, doc, '', [{**printed, 'handwriting': True}]) == 0
    assert corpus._list_extracted_formulas(uid, doc_id=doc)[0]['handwriting'] is True
    assert corpus._save_extracted_formulas(uid, doc, '', [printed]) == 0
    assert corpus._list_extracted_formulas(uid, doc_id=doc)[0]['handwriting'] is True
    conn = corpus._connect(uid)
    try:
        conn.execute("UPDATE formulas SET handwriting = NULL")
        conn.commit()
    finally:
        conn.close()
    assert corpus._list_extracted_formulas(uid, doc_id=doc)[0]['handwriting'] is None
