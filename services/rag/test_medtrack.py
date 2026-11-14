import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from medtrack_server import (
    ApiError, DemoLabels, MedTrack, demo_select, gemini_select, live_service,
    load_local_config, request_json, route,
)


class MedTrackTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock(side_effect=demo_select)
        self.service = MedTrack(DemoLabels(), self.model)
        self.question = {"label_id": "demo-a", "version": "1", "topic": "storage"}

    def test_name_collision_returns_both_candidates(self):
        result = route(self.service, "GET", "/labels?q=medtrack+demo")
        self.assertEqual({label["id"] for label in result["labels"]}, {"demo-a", "demo-b"})

    def test_brand_matches_one_candidate(self):
        result = self.service.search("  sample   label a ")
        self.assertEqual([label["id"] for label in result["labels"]], ["demo-a"])

    def test_product_variants_are_kept_and_exact_match_ranks_first(self):
        def record(label_id, brand):
            return {"id": label_id, "version": "1", "openfda": {"brand_name": [brand]}}
        self.service.labels = Mock()
        self.service.labels.search.return_value = [
            record("variant", "Tylenol Extra Strength"),
            record("different", "Tylenolish"),
            record("exact", "Tylenol"),
            record("other-variant", "Children's Tylenol"),
        ]
        result = self.service.search("tylenol")
        self.assertEqual([label["id"] for label in result["labels"]], ["exact", "variant", "other-variant"])

    def test_no_model_returns_original_excerpts_with_versioned_source(self):
        self.service.select_sources = None
        result = self.service.answer(self.question)
        self.assertEqual(result["selection_method"], "openfda")
        self.assertIn("https://api.fda.gov/drug/label.json?", result["source_url"])
        self.assertIn("demo-a", result["source_url"])
        self.assertEqual(result["sources"][0]["id"], "storage_and_handling:1")
        self.model.assert_not_called()

    def test_unknown_name_is_empty(self):
        self.assertEqual(self.service.search("Unknown"), {"labels": []})

    def test_answer_uses_the_selected_label_and_exact_source_text(self):
        result = route(self.service, "POST", "/answer", self.question)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["sources"][0]["id"], "storage_and_handling:1")
        self.assertEqual(result["sources"][0]["text"], DemoLabels().get("demo-a", "1")["storage_and_handling"][0])

    def test_missing_section_does_not_call_gemini(self):
        result = self.service.answer(dict(self.question, label_id="demo-b"))
        self.assertEqual(result, {"status": "no_evidence", "sources": []})
        self.model.assert_not_called()

    def test_missing_label_version_cannot_answer_from_another_version(self):
        with self.assertRaises(ApiError) as caught:
            self.service.answer(dict(self.question, version="2"))
        self.assertEqual(caught.exception.status, 404)
        self.model.assert_not_called()

    def test_rejects_a_model_citation_outside_the_retrieved_evidence(self):
        self.model.side_effect = None
        self.model.return_value = ["purpose:1"]
        with self.assertRaises(ApiError) as caught:
            self.service.answer(self.question)
        self.assertEqual(caught.exception.payload["code"], "invalid_model_output")

    def test_invalid_topic_is_rejected_before_model_call(self):
        with self.assertRaises(ApiError) as caught:
            self.service.answer(dict(self.question, topic=["storage"]))
        self.assertEqual(caught.exception.status, 400)
        self.model.assert_not_called()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key", "GEMINI_MODEL": "test-3.5-model"})
    @patch("medtrack_server.request_json")
    def test_gemini_request_uses_structured_citations_and_parses_response(self, request):
        request.return_value = {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [
                {"thought": True, "text": "thought"},
                {"text": json.dumps({"source_ids": ["storage_and_handling:1"]})},
            ]}}],
        }
        evidence = [{"id": "storage_and_handling:1", "section": "Storage", "text": "Fixture"}]
        self.assertEqual(gemini_select("storage", evidence), ["storage_and_handling:1"])
        args, kwargs = request.call_args
        self.assertTrue(args[0].endswith("/test-3.5-model:generateContent"))
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "fake-test-key")
        schema = kwargs["data"]["generationConfig"]["responseJsonSchema"]
        self.assertEqual(schema["properties"]["source_ids"]["items"]["enum"], [evidence[0]["id"]])

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key", "GEMINI_MODEL": "test-3.5-model"})
    @patch("medtrack_server.request_json", return_value={"candidates": [{"finishReason": "SAFETY"}]})
    def test_blocked_gemini_response_is_reported_as_a_failure(self, _):
        with self.assertRaises(ApiError) as caught:
            gemini_select("storage", [{"id": "a", "text": "Fixture"}])
        self.assertEqual(caught.exception.payload["code"], "invalid_model_output")

    @patch("medtrack_server.urlopen")
    def test_gemini_rejected_credentials_get_a_distinct_error(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://example.com", 400, "", {},
            io.BytesIO(b'{"error":{"details":[{"reason":"API_KEY_INVALID"}]}}'),
        )
        with self.assertRaises(ApiError) as caught:
            request_json("https://example.com", timeout=1, gemini=True)
        self.assertEqual(caught.exception.payload["code"], "gemini_access_denied")

    @patch.dict(os.environ, {}, clear=True)
    def test_local_config_is_loaded_and_exported_key_takes_priority(self):
        self.assertEqual(live_service().selection_method, "openfda")
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".env.local"
            config.write_text("GEMINI_API_KEY=fake-file-key\nGEMINI_MODEL=test-3.5-model\n")
            os.environ["GEMINI_API_KEY"] = "fake-exported-key"
            load_local_config(config)
        self.assertEqual(os.environ["GEMINI_API_KEY"], "fake-exported-key")
        self.assertEqual(os.environ["GEMINI_MODEL"], "test-3.5-model")
        self.assertEqual(live_service().selection_method, "gemini")

    def test_clinician_insights_sends_only_the_approved_aggregate_payload(self):
        summary = {"patient_count": 12, "medication_count": 20, "symptom_count": 16,
                   "category_counts": {"Dizziness": 6}, "severity_counts": {"Mild": 10}}
        self.service.selection_method = "gemini"
        with patch("medtrack_server.gemini_text", return_value="Summary") as model:
            self.assertEqual(route(self.service, "POST", "/clinician/insights", summary), {"text": "Summary"})
            self.assertEqual(model.call_args.args[1], summary)
            for invalid in (
                dict(summary, notes="private"),
                dict(summary, category_counts={"private free text": 6}),
                dict(summary, category_counts={"Dizziness": 1}),
                dict(summary, patient_count=3),
                dict(summary, severity_counts={"Severe": 17}),
            ):
                with self.subTest(invalid=invalid), self.assertRaises(ApiError) as caught:
                    route(self.service, "POST", "/clinician/insights", invalid)
                self.assertEqual(caught.exception.status, 400)
            model.assert_called_once()

    def test_clinician_insights_without_gemini_returns_service_unavailable(self):
        with self.assertRaises(ApiError) as caught:
            route(self.service, "POST", "/clinician/insights", {})
        self.assertEqual(caught.exception.payload["code"], "insights_unavailable")

    @patch("medtrack_server.urlopen", side_effect=TimeoutError)
    def test_timeout_is_reported_separately(self, _):
        with self.assertRaises(ApiError) as caught:
            request_json("https://example.com", timeout=1)
        self.assertEqual(caught.exception.status, 504)
        self.assertEqual(caught.exception.payload["code"], "timeout")

    @patch("medtrack_server.urlopen")
    def test_openfda_empty_results_are_not_treated_as_an_outage(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://example.com", 404, "", {},
            io.BytesIO(b'{"error":{"code":"NOT_FOUND","message":"No matches found!"}}'),
        )
        self.assertEqual(
            request_json("https://example.com", timeout=1, no_matches=True),
            {"results": []},
        )

    @patch("medtrack_server.urlopen")
    def test_generic_upstream_404_is_not_treated_as_no_matches(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://example.com", 404, "", {}, io.BytesIO(b'{}'),
        )
        with self.assertRaises(ApiError) as caught:
            request_json("https://example.com", timeout=1, no_matches=True)
        self.assertEqual(caught.exception.status, 502)


if __name__ == "__main__":
    unittest.main()
