import unittest

from .predict import analyze_case, fit_stream, observed_ranks, validate_traces


HASH = "0" * 64


def side(n, restart, *, clamp=False, change_entry=True):
    episodes = []
    for query in range(1, n + 1):
        entry = 0 if restart else query - 1
        nodes = [
            {"id": "reset", "statement": "write", "unit": "reset" if change_entry else None,
             "value": entry, "parents": []},
            {"id": "copy", "statement": "copy", "unit": None,
             "value": entry, "parents": ["reset"]},
            {"id": "guard", "statement": "bound", "unit": "clamp" if clamp else None,
             "value": query, "parents": []},
        ]
        episodes.append({"object": "array", "scan": "loop", "query": query, "extent": n,
                         "entry": entry, "exit": query, "entry_nodes": ["copy"],
                         "work_nodes": ["copy", "guard"], "nodes": nodes, "other_events": []})
    advances = sum(row["exit"] - row["entry"] for row in episodes)
    return {"output_sha256": HASH, "work": advances, "advances": advances, "episodes": episodes}


def case(*, restart=True, reference_restart=False):
    return {"id": "example", "span_map_sha256": HASH, "units": ["reset", "clamp"],
            "observations": [
                {"stream": "ordered", "size": n, "status": "complete",
                 "target": side(n, restart, clamp=True), "reference": side(n, reference_restart)}
                for n in (4, 8, 16, 32, 64, 128)
            ]}


class PredictionTests(unittest.TestCase):
    def test_accounting_and_competing_explanations(self):
        result = analyze_case(case())
        self.assertEqual(result["arms"]["rewind"]["ranking"], [["reset"]])
        self.assertEqual(result["arms"]["change_impact"]["ranking"], [["reset", "clamp"]])
        self.assertEqual(result["arms"]["value_impact"]["ranking"], [["reset"]])
        last = result["accounting"][0]
        self.assertEqual(last["target"]["advances"] - last["reference"]["advances"], 8128)
        self.assertEqual(last["net_rewind_delta"], 8128)
        self.assertEqual(last["assigned_distance"], {"reset": 8128})
        self.assertEqual(last["unassigned_distance"], 0)

    def test_comparator_swap(self):
        result = analyze_case(case(reference_restart=True))
        self.assertTrue(all(arm["status"] == "no_alert" for arm in result["arms"].values()))

    def test_caps_cannot_enter_the_fit(self):
        row = case()
        obs = row["observations"]
        for index in (0, 1, 2):
            obs[index].update(status="tick_cap", target=None, reference=None)
        result = analyze_case(row)
        self.assertEqual(result["arms"]["rewind"]["status"], "insufficient")
        self.assertEqual(result["screen"][0]["excluded"],
                         {"4": "tick_cap", "8": "tick_cap", "16": "tick_cap"})

    def test_wrong_answer_invalidates_screen_even_when_five_pairs_agree(self):
        row = case()
        row["observations"][0]["target"]["output_sha256"] = "1" * 64
        result = analyze_case(row)
        self.assertEqual(result["arms"]["rewind"]["status"], "measurement_failure")
        self.assertEqual(result["screen"][0]["excluded"], {"4": "output_mismatch"})

    def test_zero_denominator_is_indeterminate(self):
        rows = case()["observations"]
        rows[3]["reference"]["work"] = 0
        self.assertEqual(fit_stream(rows)["status"], "zero_cost")
        self.assertIsNone(analyze_case({**case(), "observations": rows})["arms"]["rewind"]["alert"])

    def test_independent_work_without_alignable_episode(self):
        row = case()
        row["observations"][-1]["target"]["episodes"][-1]["query"] = 129
        result = analyze_case(row)
        self.assertTrue(result["arms"]["rewind"]["alert"])
        self.assertEqual(result["arms"]["rewind"]["status"], "unsupported")
        self.assertEqual(result["accounting"][0]["reason"], "unmatched_episodes")

    def test_killed_write_is_never_ranked(self):
        row = case()
        for obs in row["observations"]:
            obs["target"]["episodes"][0]["nodes"].append(
                {"id": "dead", "statement": "earlier", "unit": "clamp", "parents": [], "value": 0})
        self.assertEqual(analyze_case(row)["arms"]["rewind"]["candidates"], ["reset"])

    def test_general_baseline_can_localize_unrelated_work(self):
        row = case(restart=False)
        for obs in row["observations"]:
            n = obs["size"]
            for episode in obs["target"]["episodes"]:
                episode["nodes"].append({"id": "aux", "statement": "aux", "unit": "clamp",
                                         "parents": [], "value": n})
                episode["other_events"].append({"site": "aux", "count": n, "roots": ["aux"]})
            obs["target"]["work"] += n * n
        validate_traces({"schema": "eapg.paired.traces.v1", "cases": [row]})
        result = analyze_case(row)
        self.assertEqual(result["arms"]["rewind"]["status"], "abstain")
        self.assertEqual(result["arms"]["value_impact"]["ranking"], [["clamp"]])
        self.assertEqual(result["accounting"][0]["unexplained_work_delta"], 128**2)

    def test_larger_prior_exit_does_not_implicate_unchanged_entry_value(self):
        target, reference = side(2, False), side(2, False)
        first, second = target["episodes"]
        for episode in (first, second, *reference["episodes"]):
            episode["extent"] = 8
        first["exit"] = 8
        reference["episodes"][0]["exit"] = 3
        for endpoint in (second, reference["episodes"][1]):
            endpoint.update(entry=2, exit=8)
        account, scores = observed_ranks({"target": target, "reference": reference})
        self.assertEqual(account["net_rewind_delta"], 5)
        self.assertEqual(account["unassigned_distance"], 5)
        self.assertFalse(scores["rewind"])

    def test_integrity_errors(self):
        for mutation in ("cycle", "bad_extent", "wrong_total", "duplicate", "grid", "label"):
            with self.subTest(mutation=mutation):
                row = case()
                side = row["observations"][0]["target"]
                episode = side["episodes"][0]
                if mutation == "cycle":
                    episode["nodes"][0]["parents"] = ["copy"]
                elif mutation == "bad_extent":
                    episode["exit"] = 100
                elif mutation == "wrong_total":
                    side["advances"] += 1
                elif mutation == "duplicate":
                    row["observations"].append(row["observations"][0])
                elif mutation == "grid":
                    row["observations"].pop()
                elif mutation == "label":
                    row["ground_truth"] = "reset"
                with self.assertRaises(ValueError):
                    validate_traces({"schema": "eapg.paired.traces.v1", "cases": [row]})


if __name__ == "__main__":
    unittest.main()
