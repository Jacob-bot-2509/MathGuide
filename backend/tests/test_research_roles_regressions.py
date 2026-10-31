import research_tables as tables


def test_identifier_names_do_not_match_inside_english_words():
    columns = [
        {'key': 'A', 'label': 'Fluid width'},
        {'key': 'B', 'label': 'Noise level'},
        {'key': 'C', 'label': 'Sample ID'},
    ]
    inferred = tables._infer_roles(columns, {})
    assert 'role' not in inferred[0]
    assert 'role' not in inferred[1]
    assert inferred[2]['role'] == 'identifier'


def test_formula_range_infers_every_referenced_column():
    columns = [{'key': key, 'label': key} for key in ['A', 'B', 'C', 'D']]
    inferred = tables._infer_roles(columns, {'D': '=SUM($A$2:C2)'})
    assert [col.get('role') for col in inferred] == [
        'measured', 'measured', 'measured', 'calculated',
    ]
