"""Reaggregate the frozen pilot's paired neural-minus-symbolic contrast."""

from fractions import Fraction
from hashlib import sha256
import json
from math import lcm
from pathlib import Path
import random


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "artifacts/scope_isolated_pilot"
SEED = 42
DRAWS = 10_000


def verified_json(path):
    manifest = dict(line.split("  ", 1)[::-1] for line in (ROOT / "SHA256SUMS").read_text().splitlines())
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != manifest[path.relative_to(ROOT).as_posix()]:
        raise ValueError(f"Frozen input digest mismatch: {path}")
    return json.loads(raw)


def contrast(groups):
    group_effects = [Fraction(sum(group), len(group)) for group in groups]
    total = sum(group_effects)
    pairs = sum(len(group) for group in groups)
    n = len(groups)
    rng = random.Random(SEED)
    # Integer arithmetic keeps ordering exact for tied bootstrap replicates.
    denominator = lcm(*(effect.denominator for effect in group_effects))
    weights = [int(effect * denominator) for effect in group_effects]
    samples = sorted(sum(rng.choices(weights, k=n)) for _ in range(DRAWS))
    limits = [Fraction(samples[index], n * denominator) for index in (249, 9749)]
    loo = [(total - effect) / (n - 1) for effect in group_effects] if n > 1 else []
    return {
        "pairs": pairs,
        "groups": n,
        "discordant_pairs": {"neural_only": sum(group.count(1) for group in groups),
                             "symbolic_only": sum(group.count(-1) for group in groups)},
        "net_discordant_groups": {"favor_neural": sum(value > 0 for value in group_effects),
                                   "favor_symbolic": sum(value < 0 for value in group_effects)},
        "pair_weighted_delta_pp": float(Fraction(sum(map(sum, groups)) * 100, pairs)),
        "group_weighted_delta_pp": float(total * 100 / n),
        "group_bootstrap_95pct_delta_pp": [float(value * 100) for value in limits],
        "leave_one_group_out_delta_pp": [float(min(loo) * 100), float(max(loo) * 100)] if loo else None,
    }


def main():
    pairs = verified_json(PILOT / "pilot100_results.json")
    evaluation = verified_json(PILOT / "node_only_ablation/evaluation_results.json")
    predictions = evaluation["per_pair_predictions"]
    owners = {problem: index for index, group in enumerate(evaluation["template_groups"]) for problem in group}
    all_groups = [[] for _ in evaluation["template_groups"]]
    multi_groups = [[] for _ in all_groups]
    for pair in pairs:
        entry = predictions[pair["pair_id"]]
        label = pair["gt_node"]
        if entry["gt_node"] != label:
            raise ValueError(f"Mismatched label: {pair['pair_id']}")
        variants = entry["variants"]
        delta = int(variants["6b-slice"]["pred_top1"] == label) - int(variants["2"]["pred_top1"] == label)
        index = owners[pair["problem_id"]]
        all_groups[index].append(delta)
        if len(pair["slicing"]["c_pruned"]) >= 2:
            multi_groups[index].append(delta)
    all_result = contrast(all_groups)
    multi_result = contrast([group for group in multi_groups if group])
    assert (all_result["pairs"], all_result["groups"], all_result["pair_weighted_delta_pp"]) == (100, 23, 2.0)
    assert (multi_result["pairs"], multi_result["groups"]) == (66, 15)
    print(json.dumps({"contrast": "6b-slice minus Variant 2", "bootstrap_draws": DRAWS,
                      "bootstrap_seed": SEED, "quantile_method": "nearest rank",
                      "all": all_result, "multi_candidate": multi_result}, indent=2))


if __name__ == "__main__":
    main()
