import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from autocapture.web.api import get_app
    from autocapture_nx.kernel.auth import load_or_create_token
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover - optional dependency in some environments
    TestClient = None  # type: ignore[assignment]
    get_app = None  # type: ignore[assignment]
    load_or_create_token = None  # type: ignore[assignment]
    fastapi_testclient_usable = None  # type: ignore[assignment]


_FASTAPI_OK = bool(
    TestClient is not None
    and get_app is not None
    and load_or_create_token is not None
    and fastapi_testclient_usable is not None
    and fastapi_testclient_usable()
)


@unittest.skipUnless(_FASTAPI_OK, "fastapi TestClient unavailable or unusable")
class QueryPopupRouteTests(unittest.TestCase):
    def test_popup_route_requires_auth_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            app = None
            try:
                app = get_app()
                client = TestClient(app)
                resp = client.post("/api/query/popup", json={"query": "hello"})
                self.assertEqual(resp.status_code, 401)
            finally:
                try:
                    if app is not None:
                        app.state.facade.shutdown()
                except Exception:
                    pass
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data

    def test_popup_route_returns_compact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            app = None
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token

                def _fake_query(text: str, *, schedule_extract: bool = False):
                    self.assertEqual(text, "who am i chatting with")
                    self.assertFalse(schedule_extract)
                    return {
                        "ok": True,
                        "scheduled_extract_job_id": "",
                        "answer": {
                            "state": "ok",
                            "summary": "Quorum collaborator: Nikki M",
                            "display": {
                                "summary": "Quorum collaborator: Nikki M",
                                "topic": "adv_incident",
                                "confidence_pct": 93.0,
                                "bullets": ["quorum collaborator: Nikki M", "source pane: Outlook task card"],
                            },
                            "claims": [
                                {
                                    "text": "Quorum collaborator: Nikki M",
                                    "citations": [
                                        {
                                            "record_id": "run1/derived.hard_vlm.answer/1",
                                            "record_type": "derived.hard_vlm.answer",
                                            "source": "hard_vlm.direct",
                                            "span_kind": "record",
                                            "offset_start": 0,
                                            "offset_end": 28,
                                            "stale": False,
                                            "stale_reason": "",
                                        }
                                    ],
                                }
                            ],
                        },
                        "processing": {
                            "extraction": {"blocked": False, "blocked_reason": ""},
                            "query_trace": {"query_run_id": "qry_popup_1", "stage_ms": {"total": 42.5}},
                        },
                    }

                app.state.facade.query = _fake_query
                client = TestClient(app)
                resp = client.post(
                    "/api/query/popup",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": "who am i chatting with", "max_citations": 4},
                )
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload.get("ok"))
                self.assertEqual(payload.get("state"), "ok")
                self.assertEqual(payload.get("query_run_id"), "qry_popup_1")
                self.assertEqual(payload.get("summary"), "Quorum collaborator: Nikki M")
                self.assertEqual(payload.get("topic"), "adv_incident")
                self.assertEqual(payload.get("needs_processing"), False)
                self.assertEqual(payload.get("processing_blocked_reason"), "")
                self.assertEqual(payload.get("confidence_pct"), 93.0)
                self.assertGreaterEqual(len(payload.get("citations", [])), 1)
            finally:
                try:
                    if app is not None:
                        app.state.facade.shutdown()
                except Exception:
                    pass
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data

    def test_popup_route_reports_processing_blocked_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            app = None
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token

                def _fake_query(_text: str, *, schedule_extract: bool = False):
                    self.assertFalse(schedule_extract)
                    return {
                        "ok": True,
                        "scheduled_extract_job_id": "",
                        "answer": {"state": "no_evidence", "display": {"summary": "Indeterminate", "bullets": []}, "claims": []},
                        "processing": {
                            "extraction": {"blocked": True, "blocked_reason": "query_read_only", "scheduled_extract_job_id": ""},
                            "query_trace": {"query_run_id": "qry_popup_2", "stage_ms": {"total": 11.0}},
                        },
                    }

                app.state.facade.query = _fake_query
                client = TestClient(app)
                resp = client.post(
                    "/api/query/popup",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": "what changed", "schedule_extract": True},
                )
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload.get("ok"))
                self.assertEqual(payload.get("needs_processing"), True)
                self.assertEqual(payload.get("processing_blocked_reason"), "query_read_only")
                self.assertEqual(payload.get("scheduled_extract_job_id"), "")
            finally:
                try:
                    if app is not None:
                        app.state.facade.shutdown()
                except Exception:
                    pass
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
