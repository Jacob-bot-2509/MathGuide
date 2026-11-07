def test_capabilities_default_false_without_packages(monkeypatch):
    import analysis_capabilities as ac
    monkeypatch.setattr(ac.importlib.util, "find_spec", lambda name: None)
    assert ac.available_packs() == {
        "rdkit": False, "biopython": False, "astropy": False, "networkx": False,
    }


def test_capabilities_endpoint_defaults_false(monkeypatch):
    import research_tables as rt
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def fake_caps():
        return {"rdkit": False, "biopython": False,
                "astropy": False, "networkx": False}

    monkeypatch.setattr(rt, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(rt, "_run_capabilities", fake_caps)
    app = Starlette(routes=[Route(
        "/api/research/analysis/capabilities", rt.analysis_capabilities)])
    body = TestClient(app).get("/api/research/analysis/capabilities").json()
    assert body["packs"]["rdkit"] is False
    assert body["packs"]["networkx"] is False
