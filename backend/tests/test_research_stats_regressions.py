import json
from decimal import Decimal

import pytest

import research_tables as rt
import research_vision as rv


def test_large_statistic_is_not_truncated_or_rounded():
    value = '12345678901234567890123456789012345678901234567890'
    result = rt.analyze([{'key': 'A', 'type': 'number'}], [[value]], {})
    for field in ('mean', 'median', 'min', 'max'):
        assert Decimal(result['stats'][0][field]) == Decimal(value)


@pytest.mark.parametrize('bad', ['NaN', 'sNaN', 'Infinity', '-Infinity', '1e1000', '1e-1000', '9e307'])
def test_bad_numeric_cells_are_reported_and_excluded(bad):
    result = rt.analyze([{'key': 'A', 'type': 'number'}], [[bad], ['2']], {})
    assert result['stats'][0]['n'] == 1
    assert result['series'][0]['values'] == [None, 2.0]
    assert any(e['col'] == 'A' and e['row'] == 0 for e in result['errors'])
    json.dumps(result, allow_nan=False)


def test_null_table_cells_remain_empty():
    result = rv._clean_table_result({'columns': ['A', 'B'], 'rows': [[None, 0]]})
    assert result['rows'] == [['', '0']]


def test_analysis_reports_formula_cycles_without_crashing():
    columns = [{'key': 'A', 'type': 'number'}, {'key': 'B', 'type': 'number'}]
    result = rt.analyze(columns, [['1', '2']], {'A': '=B2', 'B': '=A2'})
    assert result['errors']
    assert result['columns'] == columns
