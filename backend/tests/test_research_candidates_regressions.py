import research_tables as tables


def test_incomplete_mapping_cannot_produce_an_applicable_formula():
    table = {
        'columns': [{'key': 'A', 'label': 'x'}, {'key': 'B', 'label': 'y'}],
        'rows': [['1', '2']], 'formulas': {},
    }
    saved = [{
        'id': 'f', 'target': 'y', 'expr': 'x/z', 'variables': ['x', 'z'],
        'variableMap': {}, 'handwriting': True,
    }]
    candidate = tables._match_formula_candidates(table, saved)[0]
    assert candidate['formula'] == ''
    assert candidate['handwriting'] is True


def test_invalid_rows_do_not_discard_other_validation_results():
    table = {
        'columns': [{'key': 'A', 'label': 'x'}, {'key': 'B', 'label': 'y'}],
        'rows': [['1', 'NaN'], ['2', '4']], 'formulas': {},
    }
    saved = [{
        'id': 'f', 'target': 'y', 'expr': 'x*2', 'variables': ['x'],
        'variableMap': {}, 'handwriting': False,
    }]
    candidate = tables._match_formula_candidates(table, saved)[0]
    assert candidate['validation']['matched'] == 1
    assert candidate['validation']['compared'] == 1
    assert candidate['handwriting'] is False
