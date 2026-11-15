import json
import unittest

from fastapi.testclient import TestClient

from app import create_app
from label_corpus import DEFAULT_CORPUS
from label_retrieval import LabelIndex, LabelSnapshot
from medtrack_server import DemoLabels, MedTrack, demo_select
from safety_review import HOUR_MS, SafetyChecker, canonical

NOW = 1_800_000_000_000
RECORDS = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))["results"]


def taken(name, hours_ago=2):
    return {"name": name, "last_taken_at": NOW - int(hours_ago * HOUR_MS)}


class SafetyCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = LabelIndex(LabelSnapshot(RECORDS, public=True), model=None)
        cls.checker = SafetyChecker(cls.index)

    @classmethod
    def tearDownClass(cls):
        cls.index.db.close()

    def review(self, new, *existing):
        return self.checker.review(new, list(existing), taken_at=NOW)

    def test_label_warning_cites_the_passage_that_names_the_other_drug_class(self):
        review = self.review("布洛芬", taken("华法林"))
        [alert] = review["alerts"]
        self.assertEqual((alert["with"], alert["severity"], alert["kinds"]), ("华法林", "moderate", ["label_warning"]))
        citation = alert["findings"][0]["citation"]
        self.assertIn("anticoagulant", citation["excerpt"])
        self.assertTrue(citation["source_url"].startswith("https://api.fda.gov/drug/label.json"))
        # The excerpt is copied from the passage, never paraphrased.
        passage = next(p for p in self.index.passages if p.label_id == citation["label_id"]
                       and p.version == citation["version"] and p.id == citation["passage_id"])
        self.assertIn(citation["excerpt"].strip("…"), passage.text)

    def test_shared_ingredient_within_a_day_is_high_and_cites_do_not_use(self):
        [alert] = self.review("泰诺", taken("FLONASE Headache and Allergy Relief"))["alerts"]
        self.assertEqual((alert["severity"], alert["kinds"][0]), ("high", "duplicate_ingredient"))
        self.assertEqual(alert["findings"][0]["citation"]["section"], "Do not use")

    def test_shared_ingredient_days_apart_is_not_a_duplicate(self):
        self.assertEqual(self.review("泰诺", taken("对乙酰氨基酚", hours_ago=72))["alerts"], [])

    def test_same_product_again_is_skipped(self):
        review = self.review("泰诺", taken("泰诺"))
        self.assertEqual((review["alerts"], review["checked"]), ([], []))

    def test_records_older_than_a_week_are_history(self):
        review = self.review("布洛芬", taken("华法林", hours_ago=24 * 30))
        self.assertEqual((review["alerts"], review["not_recent"]), ([], ["华法林"]))

    def test_window_is_relative_to_when_it_was_taken_not_when_it_synced(self):
        # Recorded offline a month ago and synced only now: compared with records from around that time.
        old = {"name": "华法林", "last_taken_at": NOW - 30 * 24 * HOUR_MS}
        review = self.checker.review("布洛芬", [old], taken_at=NOW - 30 * 24 * HOUR_MS + HOUR_MS)
        self.assertEqual([a["with"] for a in review["alerts"]], ["华法林"])

    def test_allergy_and_negated_mentions_do_not_count(self):
        # ZYRTEC: "allergic reaction ... to an antihistamine containing hydroxyzine" is not an interaction.
        self.assertEqual(self.review("西替利嗪", taken("苯海拉明"))["alerts"], [])
        # Lipitor: "no clinically significant effect on prothrombin time ... chronic warfarin treatment".
        self.assertEqual(self.review("阿托伐他汀", taken("华法林"))["alerts"], [])

    def test_unknown_names_are_reported_not_silently_passed(self):
        review = self.review("阿托伐他汀", taken("克拉霉素"))
        self.assertEqual((review["alerts"], review["unresolved"]), ([], ["克拉霉素"]))
        self.assertEqual(self.review("某种草药")["status"], "unresolved_medication")

    def test_pairs_with_no_label_on_either_side_are_not_reported_as_compared(self):
        # Found by the blind test (eval/safety_blind/NOTES.md): diclofenac and warfarin are both recognised, but the
        # snapshot has neither label, so nothing about the combination could be read.
        review = self.review("双氯芬酸", taken("华法林"), taken("舍曲林"))
        self.assertEqual([m["name"] for m in review["no_label"]], ["华法林"])
        self.assertEqual([m["name"] for m in review["checked"]], ["舍曲林"])  # Zoloft's label was read
        self.assertEqual([a["with"] for a in review["alerts"]], ["舍曲林"])

    def test_both_labels_are_read(self):
        # Ibuprofen's label is silent about SSRIs; Zoloft's names NSAIDs.
        [alert] = self.review("布洛芬", taken("舍曲林"))["alerts"]
        self.assertEqual(alert["findings"][0]["citation"]["label"], "Zoloft")

    def test_names_resolve_through_chinese_aliases_and_the_snapshot(self):
        self.assertEqual(self.checker.resolve("布洛芬缓释胶囊").ingredients, {"ibuprofen"})
        self.assertEqual(self.checker.resolve("Advil Dual Action with Acetaminophen").ingredients,
                         {"ibuprofen", "acetaminophen"})
        self.assertEqual(self.checker.resolve("Advil").problem, None)  # exact name beats "ADVIL COLD AND SINUS"
        self.assertEqual(canonical("ATORVASTATIN CALCIUM TRIHYDRATE"), "atorvastatin")
        self.assertEqual(canonical("NAPROXEN SODIUM"), "naproxen")


class SafetyEndpointTests(unittest.TestCase):
    def setUp(self):
        index = LabelIndex(LabelSnapshot(RECORDS, public=True), model=None)
        self.addCleanup(index.db.close)
        self.seen = []
        test = self

        class Medications:
            def list(self, token):
                test.seen.append(token)
                return [taken("华法林")]

        from agent import LabelAgent
        agent = LabelAgent(index, medications=Medications())
        self.client = self.enterContext(TestClient(create_app(index, MedTrack(DemoLabels(), demo_select, "demo"),
                                                              agent)))

    def test_reads_the_list_with_the_callers_token(self):
        response = self.client.post("/v1/safety/review", json={"medication": "布洛芬", "taken_at": NOW},
                                    headers={"Authorization": "Bearer dlg_example"})
        response.raise_for_status()
        self.assertEqual([a["with"] for a in response.json()["alerts"]], ["华法林"])
        self.assertEqual(self.seen, ["Bearer dlg_example"])

    def test_requires_a_token_and_rejects_extra_fields(self):
        self.assertEqual(self.client.post("/v1/safety/review", json={"medication": "布洛芬"}).status_code, 401)
        response = self.client.post("/v1/safety/review", json={"medication": "布洛芬", "patient": "x"},
                                    headers={"Authorization": "Bearer dlg_example"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
