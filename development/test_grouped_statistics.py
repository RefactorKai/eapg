"""Exact-test and public-receipt checks for the grouped statistics redo."""

from itertools import product
import sys

import pytest

import replay_grouped_statistics as replay


@pytest.mark.parametrize("weights", [[2, 4, -1, 0], [0, 0], [3, 3, 3], [3, -3, 5]])
def test_exact_sign_flip_matches_enumeration(weights):
    observed = abs(sum(weights))
    brute_force = [abs(sum(w * s for w, s in zip(weights, signs, strict=True)))
                   for signs in product((-1, 1), repeat=len(weights))]
    assert replay.sign_flip_p(weights) == sum(value >= observed for value in brute_force) / len(brute_force)


def test_contrast_flips_cluster_means_not_pairs():
    rows = [(group, value) for group, values in enumerate([[1] * 10, [-1], [1, 0]]) for value in values]
    stats = replay.paired(rows, lambda r: r[0], lambda r: r[1] == 1, lambda r: r[1] == -1)
    assert stats["left"]["total"] == 13
    assert stats["groups"] == 3
    assert stats["group_weighted_delta_pp"] == 16.7
    assert stats["cluster_sign_flip_p"] == 1
    assert stats["leave_one_group_out_range_delta_pp"] == [-25.0, 75.0]


def test_small_stratum_intervals():
    assert replay.rate(0, 5)["clopper_pearson_95pct_percent"] == [0.0, 52.2]
    assert replay.rate(5, 5)["clopper_pearson_95pct_percent"] == [47.8, 100.0]
    assert replay.rate(1, 2)["clopper_pearson_95pct_percent"] == [1.3, 98.7]
    assert replay.rate(6, 10)["clopper_pearson_95pct_percent"] == [26.2, 87.8]


def test_holm_is_monotone_and_capped():
    assert replay.holm({"c": 0.025, "a": 0.02, "d": 0.9, "b": 0.025}) == pytest.approx(
        {"a": 0.08, "b": 0.08, "c": 0.08, "d": 0.9}
    )
    assert replay.holm({"a": 0.8, "b": 0.9}) == {"a": 1.0, "b": 1.0}


@pytest.fixture(scope="module")
def computed():
    return replay.recompute()


def test_declared_primary_family_is_qualification_only(computed):
    primary = computed["paired_qualification"]["primary"]
    assert set(primary) == {"desk_stop_minus_execution", "all_stream_alert_minus_no_alert"}
    funnel = primary["desk_stop_minus_execution"]
    assert (funnel["left"]["count"], funnel["right"]["count"], funnel["left"]["total"], funnel["groups"]) == (
        103, 14, 147, 119
    )
    fitted = primary["all_stream_alert_minus_no_alert"]
    assert (fitted["left"]["count"], fitted["right"]["count"], fitted["groups"]) == (4, 9, 12)
    assert funnel["holm_p"] == 2 * funnel["cluster_sign_flip_p"]
    assert "holm_p" not in computed["part_a"]["scoped_minus_cfg_top1"]["core"]
    assert computed["paired_qualification"]["all_stream_alerts_without_admitted_sensitivity"] == ["p03999"]


def test_agreement_uses_unequal_cluster_sizes_and_positive_denominators(computed):
    pilot = computed["frozen_pilot"]["strict_13_group_ablations"]["multi_candidate"]["adapted_constrained"]
    assert pilot["abstract_graph_minus_full_eapg"]["cluster_sign_flip_p"] == 0.046875
    hits = pilot["abstract_graph_minus_abstract_hits_only"]
    assert hits["group_bootstrap_95pct_delta_pp"] == [-6.1, 39.8]
    assert hits["groups"] == 10
    core = computed["part_a"]["scoped_minus_cfg_top1"]["core"]
    assert (core["left"]["total"], core["groups"], core["cluster_sign_flip_p"]) == (20, 10, 2 / 1024)
    b = computed["part_b"]["contrasts"]
    assert b["adjudicated_positives"]["symbolic_unbiased"]["discordant_pairs"] == {"left_only": 6, "right_only": 2}
    assert b["adjudicated_positives"]["symbolic_unbiased"]["cluster_sign_flip_p"] == 1.0
    assert b["without_g_stress_08"]["symbolic_unbiased"]["group_weighted_delta_pp"] == 0.0


def test_fair_cfg_baselines_are_recomputed_from_public_candidate_sets(computed):
    uniform = computed["part_a"]["uniform_cfg_top1"]
    assert (uniform["expected_hits_exact"], uniform["expected_hits"], uniform["total"]) == ("1483/360", 4.12, 20)
    nearest = computed["oeis_development"]["nearest_preceding_cfg_minus_scoped_top1"]
    assert (nearest["left"]["count"], nearest["right"]["count"], nearest["left"]["total"], nearest["groups"]) == (
        4, 3, 5, 4
    )


def test_verifier_checks_saved_statistics(computed, tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "RECEIPT", tmp_path / "receipt.json")
    monkeypatch.setattr(replay, "recompute", lambda: computed)
    monkeypatch.setattr(sys, "argv", ["replay_grouped_statistics.py", "--write"])
    replay.main()
    monkeypatch.setattr(sys, "argv", ["replay_grouped_statistics.py"])
    replay.main()
    replay.RECEIPT.write_text('{"schema": "eapg-grouped-statistics-v1"}', encoding="utf-8")
    with pytest.raises(ValueError, match="receipt differs"):
        replay.main()
