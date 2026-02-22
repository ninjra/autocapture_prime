import os
import tempfile
import unittest

class QueryPopupRouteTests(unittest.TestCase):
    def _require_fastapi_stack(self):
        try:
            from fastapi.testclient import TestClient  # type: ignore
            from autocapture.web.api import get_app
            from autocapture_nx.kernel.auth import load_or_create_token
            from tests._fastapi_support import fastapi_testclient_usable
        except Exception as exc:  # pragma: no cover - deterministic fail signal
            self.fail(f"fastapi stack import failed: {type(exc).__name__}: {exc}")
        self.assertTrue(bool(fastapi_testclient_usable()), "fastapi TestClient unavailable or unusable")
        return TestClient, get_app, load_or_create_token

    def test_popup_route_requires_auth_token(self) -> None:
        TestClient, get_app, _load_or_create_token = self._require_fastapi_stack()
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
        TestClient, get_app, load_or_create_token = self._require_fastapi_stack()
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
        TestClient, get_app, load_or_create_token = self._require_fastapi_stack()
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

    def test_popup_route_forbids_query_compute_disabled_when_claims_exist(self) -> None:
        TestClient, get_app, load_or_create_token = self._require_fastapi_stack()
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
                        "answer": {
                            "state": "not_available_yet",
                            "display": {"summary": "Song: Sunlight", "bullets": ["source: siriusxm window"]},
                            "claims": [
                                {
                                    "text": "Song: Sunlight",
                                    "citations": [
                                        {
                                            "record_id": "run1/derived.text.vlm/1",
                                            "record_type": "derived.text.vlm",
                                            "source": "hard_vlm.direct",
                                            "span_kind": "record",
                                            "offset_start": 0,
                                            "offset_end": 14,
                                            "stale": False,
                                            "stale_reason": "",
                                        }
                                    ],
                                }
                            ],
                        },
                        "processing": {
                            "extraction": {"blocked": True, "blocked_reason": "query_compute_disabled"},
                            "query_trace": {"query_run_id": "qry_popup_3", "stage_ms": {"total": 19.0}},
                        },
                    }

                app.state.facade.query = _fake_query
                client = TestClient(app)
                resp = client.post(
                    "/api/query/popup",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": "what song is playing"},
                )
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertEqual(payload.get("state"), "ok")
                self.assertEqual(payload.get("needs_processing"), False)
                self.assertEqual(payload.get("processing_blocked_reason"), "")
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


if __name__ == "__main__":
    unittest.main()
