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


def test_units_affect_candidate_score_without_cross_candidate_state():
    table = {
        'columns': [{'key': 'A', 'label': 'x', 'unit': 's'}, {'key': 'B', 'label': 'y'}],
        'rows': [], 'formulas': {},
    }
    saved = [
        {'id': 'correct', 'target': 'y', 'expr': 'x', 'variables': ['x'],
         'variableMap': {}, 'units': {'x': 's'}},
        {'id': 'wrong', 'target': 'y', 'expr': 'x', 'variables': ['x'],
         'variableMap': {}, 'units': {'x': 'ms'}},
        {'id': 'unknown', 'target': 'y', 'expr': 'x', 'variables': ['x'],
         'variableMap': {}, 'units': {}},
    ]
    result = tables._match_formula_candidates(table, saved)
    scores = {candidate['formulaId']: candidate['score'] for candidate in result}
    assert scores == {'correct': 5.5, 'unknown': 5.0, 'wrong': 4.0}


def test_formula_compiler_does_not_rewrite_inserted_references():
    assert tables._compile_table_formula(
        'mass+B2', {'mass': 'B', 'B2': 'C'},
    ) == '=B2+C2'
    assert tables._compile_table_formula('exp(X)+X', {'X': 'A'}) == '=EXP(A2)+A2'
    assert tables._compile_table_formula('速度/时间', {'速度': 'A', '时间': 'B'}) == '=A2/B2'


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
