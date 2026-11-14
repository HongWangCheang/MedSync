import unittest

from fastapi.testclient import TestClient

from app import create_app
from label_retrieval import LabelIndex, LabelSnapshot
from medtrack_server import DEMO_LABELS, DemoLabels, MedTrack, demo_select


class LabelApiTests(unittest.TestCase):
    def setUp(self):
        index = LabelIndex(LabelSnapshot(DEMO_LABELS, public=False), model=None)
        self.addCleanup(index.db.close)
        legacy = MedTrack(DemoLabels(), demo_select, "demo")
        self.client = self.enterContext(TestClient(create_app(index, legacy)))

    def ask(self, **body):
        response = self.client.post("/v1/answer", json={"mode": "keyword", **body})
        response.raise_for_status()
        return response.json()

    def test_ambiguous_name_does_not_produce_an_answer(self):
        answer = self.ask(drug_name="MedTrack Demo", question="What storage instructions are listed?")
        self.assertEqual(answer["status"], "needs_selection")
        self.assertEqual({r["id"] for r in answer["candidates"]}, {"demo-a", "demo-b"})
        self.assertEqual(answer["sources"], [])

    def test_versioned_selection_only_uses_the_chosen_record(self):
        question = "What storage instructions are listed?"
        answer = self.ask(label_id="demo-a", version="1", question=question)
        self.assertEqual(answer["status"], "answered")
        self.assertEqual(answer["summary"], DEMO_LABELS[0]["storage_and_handling"][0])
        self.assertIsNone(answer["source_url"])
        self.assertEqual(self.ask(label_id="demo-b", version="1", question=question)["status"], "no_evidence")
        self.assertEqual(self.ask(label_id="demo-a", version="2", question=question)["status"], "no_match")

    def test_extra_fields_are_rejected(self):
        response = self.client.post("/v1/answer", json={
            "drug_name": "MedTrack Demo", "question": "Storage instructions?", "patient_id": "synthetic",
        })
        self.assertEqual(response.status_code, 422)

    def test_rerank_mode_cites_cross_encoder_top_passage_and_refuses_below_threshold(self):
        class FakeReranker:
            def __init__(self, score):
                self.score = score

            def rerank(self, query, documents):
                return [self.score if "Storage" in doc else self.score - 20 for doc in documents]

        index = self.client.app.state.index
        index.vector = lambda *_: []  # demo index has no embedding model; rerank the keyword candidates only
        body = dict(label_id="demo-a", version="1", question="What storage instructions are listed?", mode="rerank")
        index.reranker = FakeReranker(5.0)
        answer = self.ask(**body)
        self.assertEqual(answer["status"], "answered")
        self.assertEqual(answer["summary"], DEMO_LABELS[0]["storage_and_handling"][0])
        index.reranker = FakeReranker(-50.0)
        answer = self.ask(**body)
        self.assertEqual((answer["status"], answer["sources"]), ("no_evidence", []))

    def test_legacy_clients_still_use_same_paths(self):
        self.assertEqual(len(self.client.get("/labels", params={"q": "MedTrack Demo"}).json()["labels"]), 2)
        response = self.client.post("/answer", json={"label_id": "demo-a", "version": "1", "topic": "storage"})
        self.assertEqual(response.json()["selection_method"], "demo")


if __name__ == "__main__":
    unittest.main()
