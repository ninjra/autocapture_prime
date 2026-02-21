from tools.reprocess_models import _build_plugin_status


def test_build_plugin_status_flags_skip_without_reason():
    manifests = [{"plugin_id": "a"}, {"plugin_id": "b"}]
    load_report = {"loaded": ["a"], "failed": [], "skipped": ["b"], "errors": []}
    probe = []
    trace = {"summary": {"plugins": {}}}
    status, skipped = _build_plugin_status(
        manifests=manifests,
        load_report=load_report,
        probe_results=probe,
        trace=trace,
    )
    assert any(item["plugin_id"] == "a" and item["status"] == "loaded" for item in status)
    assert "b" in skipped
