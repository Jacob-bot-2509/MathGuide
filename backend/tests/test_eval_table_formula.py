from tools import eval_table_formula as evaluation


def test_empty_library_must_not_produce_candidates(monkeypatch):
    monkeypatch.setattr(evaluation, 'CASES', [{
        'name': 'empty', 'table': {'columns': [], 'formulas': {}},
        'saved': [], 'target': '', 'mapping': {}, 'roles': {},
    }])
    monkeypatch.setattr(evaluation.rt, '_match_formula_candidates',
                        lambda table, saved: [{'formulaId': 'unexpected'}])
    assert evaluation.main() == 1


def test_wrong_candidate_with_same_target_must_fail(monkeypatch):
    monkeypatch.setattr(evaluation, 'CASES', [{
        'name': 'ranking', 'table': {'columns': [], 'formulas': {}},
        'saved': [{'id': 'right'}], 'candidate': 'right',
        'target': 'C', 'mapping': {}, 'roles': {},
    }])
    monkeypatch.setattr(evaluation.rt, '_match_formula_candidates', lambda table, saved: [{
        'formulaId': 'wrong', 'columnKey': 'C', 'mapping': {},
        'validation': {'compared': 1, 'matched': 1, 'unverified': 0, 'calculationErrors': 0},
    }])
    assert evaluation.main() == 1


def test_unverified_rows_do_not_count_as_backcalc_pass(monkeypatch):
    monkeypatch.setattr(evaluation, 'CASES', [{
        'name': 'partial', 'table': {'columns': [], 'formulas': {}},
        'saved': [{'id': 'right'}], 'candidate': 'right',
        'target': 'C', 'mapping': {}, 'roles': {},
    }])
    monkeypatch.setattr(evaluation.rt, '_match_formula_candidates', lambda table, saved: [{
        'formulaId': 'right', 'columnKey': 'C', 'mapping': {},
        'validation': {'compared': 1, 'matched': 1, 'unverified': 1, 'calculationErrors': 1},
    }])
    assert evaluation.main() == 1


def test_metrics_exclude_empty_library_from_positive_denominators(monkeypatch, capsys):
    monkeypatch.setattr(evaluation, 'CASES', [
        {'name': 'positive', 'table': {'columns': [], 'formulas': {}},
         'saved': [{'id': 'right'}], 'candidate': 'right', 'target': 'C',
         'mapping': {}, 'roles': {}},
        {'name': 'empty', 'table': {'columns': [], 'formulas': {}},
         'saved': [], 'target': '', 'mapping': {}, 'roles': {}},
    ])
    monkeypatch.setattr(evaluation.rt, '_match_formula_candidates', lambda table, saved: [{
        'formulaId': 'right', 'columnKey': 'C', 'mapping': {},
        'validation': {'compared': 1, 'matched': 1, 'unverified': 0, 'calculationErrors': 0},
    }] if saved else [])
    assert evaluation.main() == 0
    output = capsys.readouterr().out
    assert 'top1=1/1' in output
    assert 'backcalc=1/1' in output
    assert 'no_candidate=1/1' in output
    assert 'roles=2/2' in output
