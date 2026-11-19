import unittest

from . import panel, timing


class TimingTests(unittest.TestCase):
    def test_paired_random_order_is_reproducible_and_balanced(self):
        orders = timing.paired_orders(timing.SEED, timing.WARMUPS, timing.REPEATS)
        self.assertEqual(orders, timing.paired_orders(timing.SEED, timing.WARMUPS, timing.REPEATS))
        self.assertEqual(len(orders), timing.WARMUPS + timing.REPEATS)
        self.assertTrue(all(set(order) == set(timing.SIDES) for order in orders))
        self.assertEqual(len({tuple(order) for order in orders}), 2)

    def test_independent_runtime_screen_ignores_warmups_and_needs_all_repeats(self):
        rows = []
        for stream in panel.STREAMS:
            for n in panel.SIZES:
                for side in timing.SIDES:
                    elapsed = 100 * n if side == "target" else 100
                    rows.append({"stream": stream, "size": n, "side": side,
                                 "phase": "warmup", "elapsed_ns": 10**9})
                    rows.extend({"stream": stream, "size": n, "side": side,
                                 "phase": "measured", "elapsed_ns": elapsed}
                                for _ in range(timing.REPEATS))
        result = timing.summarize(rows, panel.SIZES)
        for screen in result.values():
            self.assertAlmostEqual(screen["fit"]["slope"], 1.0)
            self.assertEqual(screen["fit"]["largest_ratio"], panel.SIZES[-1])
            self.assertTrue(screen["passes_screen"])
        with self.assertRaisesRegex(ValueError, "missing repetitions"):
            timing.summarize(rows[:-1], panel.SIZES)
