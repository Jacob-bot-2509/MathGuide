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
    conn = corpus._connect(uid)
    try:
        assert conn.execute("SELECT COUNT(*) FROM source_blocks WHERE doc_id = ?", (doc,)).fetchone()[0] == 0
    finally:
        conn.close()


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
    conn = corpus._connect(uid)
    try:
        conn.execute("UPDATE formulas SET handwriting = NULL")
        conn.commit()
    finally:
        conn.close()
    assert corpus._list_extracted_formulas(uid, doc_id=doc)[0]['handwriting'] is None
