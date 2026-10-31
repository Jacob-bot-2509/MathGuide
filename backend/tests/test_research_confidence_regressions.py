import json

import pytest

import research_corpus as corpus
import research_tables as tables
import research_vision as vision


@pytest.mark.parametrize('invalid', ['NaN', 'Infinity', '-Infinity', True])
def test_invalid_confidence_is_never_high(invalid):
    formula = vision._clean_result({'formulas': [
        {'target': 'y', 'expr': 'x', 'confidence': invalid},
    ]})['formulas'][0]
    page = vision._clean_page_result({'blocks': [
        {'kind': 'printed_text', 'text': 'sample', 'confidence': invalid},
    ]})['blocks'][0]
    topic = tables._parse_topic(json.dumps({'title': 'sample', 'confidence': invalid}))
    assert formula['confidence'] == page['confidence'] == topic['confidence'] == 0


def test_unknown_formula_origin_is_not_treated_as_printed(tmp_path, monkeypatch):
    formula = vision._clean_result({'formulas': [{'target': 'y', 'expr': 'x'}]})['formulas'][0]
    assert formula['handwriting'] is None
    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(corpus.embed_mod, 'is_configured', lambda: False)
    uid = 'unknown-origin'
    doc = corpus._ingest(uid, 'sample.txt', b'sample text ' * 10, 'text/plain', analyze=False)['docId']
    assert corpus._save_source_blocks(uid, doc, 1, [formula]) == 1
    conn = corpus._connect(uid)
    try:
        assert conn.execute('SELECT kind FROM source_blocks').fetchone()[0] == 'unknown_formula'
    finally:
        conn.close()


def test_invalid_confidence_is_not_persisted_as_high(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(corpus.embed_mod, 'is_configured', lambda: False)
    uid = 'confidence-test'
    doc = corpus._ingest(uid, 'sample.txt', b'sample text ' * 10, 'text/plain', analyze=False)['docId']
    formula = {'target': 'y', 'expr': 'x', 'confidence': 'NaN'}
    assert corpus._save_extracted_formulas(uid, doc, '', [formula]) == 1
    assert corpus._save_source_blocks(uid, doc, 1, [formula]) == 1
    assert corpus._save_page_blocks(uid, doc, 1, [
        {'kind': 'printed_text', 'text': 'sample', 'confidence': 'Infinity'},
    ]) == 1
    conn = corpus._connect(uid)
    try:
        assert conn.execute('SELECT confidence FROM formulas').fetchone()[0] == 0
        assert all(row[0] == 0 for row in conn.execute('SELECT confidence FROM source_blocks'))
    finally:
        conn.close()
