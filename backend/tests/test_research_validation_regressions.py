import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import research_tables as tables


@pytest.mark.parametrize('bad', ['NaN', 'sNaN', 'Infinity', '-Infinity', '1e9999999'])
def test_formula_validation_skips_unsupported_actual_values(monkeypatch, bad):
    monkeypatch.setattr(tables, 'require_auth', lambda request: {'uid': 'u'})
    monkeypatch.setattr(tables, '_get_table', lambda uid, table_id: {
        'columns': [{'key': 'A', 'type': 'number'}, {'key': 'B', 'type': 'number'}],
        'rows': [['1', bad], ['2', '4']],
    })
    app = Starlette(routes=[Route('/tables/{table_id}/validate', tables.validate_formula, methods=['POST'])])
    response = TestClient(app).post('/tables/t/validate', json={'columnKey': 'B', 'formula': '=A2*2'})
    assert response.status_code == 200
    assert response.json()['matched'] == 1
    assert response.json()['compared'] == 1
