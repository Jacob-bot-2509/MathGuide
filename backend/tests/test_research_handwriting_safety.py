import pytest

import research_vision as vision


def clean(handwriting):
    return vision._clean_table_result({
        'columns': ['A', 'B'], 'rows': [['1', '2']], 'handwriting': handwriting,
    })


def test_cells_override_false_detected_flag():
    result = clean({'detected': False, 'cells': [[0, 1]]})
    assert result['handwriting']['detected'] is True
    assert result['handwriting']['cells'] == [[0, 1]]


@pytest.mark.parametrize('bad', [[9, 9], [0.9, 1], [float('inf'), 1], [True, 1], ['0', '1']])
def test_invalid_cell_disables_partial_filtering(bad):
    result = clean({'detected': True, 'cells': [[0, 1], bad]})
    assert result['handwriting']['detected'] is True
    assert result['handwriting']['cells'] == []
    assert result['warnings']


def test_skipped_rows_disable_partial_filtering():
    result = vision._clean_table_result({
        'columns': ['A'], 'rows': ['invalid', ['printed'], ['handwritten']],
        'handwriting': {'detected': True, 'cells': [[1, 0]]},
    })
    assert result['handwriting']['cells'] == []
    assert result['warnings']


def test_truncated_cell_list_does_not_enable_partial_filtering():
    result = clean({'detected': True, 'cells': [[0, 1]] * 401})
    assert result['handwriting']['cells'] == []
    assert result['warnings']
