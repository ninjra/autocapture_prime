import tempfile
import unittest

from autocapture_nx.kernel.egress_approvals import EgressApprovalStore


class _EB:
    def __init__(self) -> None:
        self.events = []

    def ledger_entry(self, record_type, inputs, outputs, payload):  # noqa: ANN001
        self.events.append({"record_type": record_type, "payload": dict(payload or {})})


class EgressApprovalStoreTests(unittest.TestCase):
    def test_request_approve_deny_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eb = _EB()
            cfg = {
                "storage": {"data_dir": tmp},
                "privacy": {
                    "egress": {
                        "approval_store_path": f"{tmp}/approvals.json",
                        "approval_ttl_s": 60,
                    }
                },
            }
            store = EgressApprovalStore(cfg, event_builder=eb)
            req = store.request(packet_hash="deadbeef", policy_id="policy", schema_version=1)
            approval_id = req.get("approval_id")
            self.assertTrue(approval_id)
            self.assertEqual(len(store.list_requests()), 1)
            tok = store.approve(approval_id, ttl_s=60)
            self.assertIn("token", tok)
            self.assertEqual(tok.get("approval_id"), approval_id)
            self.assertEqual(store.list_requests(), [])

            # Ledger emission is best-effort but should occur when event_builder is provided.
            event_names = [e["payload"].get("event") for e in eb.events]
            self.assertIn("egress.approval.request", event_names)
            self.assertIn("egress.approval.granted", event_names)


if __name__ == "__main__":
    unittest.main()

