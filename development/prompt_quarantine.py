"""Apply final prompt-token keys to the registered Phase 2 custody graph."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifacts/phase1_correction"))
from phase2_custody_and_probes import Pair, quarantine


PROMPT_PREFIX = "eapg:prompt-token-sha256:"


def seal_splits(test, validation, train, prompt_tokens, *, unsupported=None):
    """Return a manifest for finalized prompts, with precedence test > validation > train.

    The custodian supplies each pair's finalized token sequences, one per registered
    representation. Each key is the exact sequence excluding the reference answer.
    Record explicitly unsupported pair IDs and reasons. Those pairs remain in
    the static graph and are ineligible for training.
    """
    unsupported = {} if unsupported is None else dict(unsupported)
    test, validation, train = (sorted(cohort, key=lambda row: row.pair_id) for cohort in (test, validation, train))
    rows = [*test, *validation, *train]
    ids = {row.pair_id for row in rows}
    if (len(rows) != len(ids) or ids != set(prompt_tokens) | set(unsupported)
            or set(prompt_tokens) & set(unsupported) or not all(unsupported.values())):
        raise ValueError("Require final tokens or a registered unsupported reason for every unique pair")
    decorated = {}
    for row in rows:
        sequences = prompt_tokens.get(row.pair_id, ())
        if ((not sequences and row.pair_id not in unsupported)
                or any(not seq or any(type(token) is not int or token < 0 for token in seq) for seq in sequences)):
            raise ValueError(f"Missing or invalid finalized token sequence: {row.pair_id}")
        if any(value.startswith(PROMPT_PREFIX) for value in (row.problem_id, *row.aliases)):
            raise ValueError(f"Reserved alias prefix in pair: {row.pair_id}")
        keys = {PROMPT_PREFIX + hashlib.sha256(json.dumps(list(seq), separators=(",", ":")).encode()).hexdigest()
                for seq in sequences}
        decorated[row.pair_id] = replace(row, aliases=(*row.aliases, *sorted(keys)))

    test_ids = [row.pair_id for row in test]
    validation_ids = [row.pair_id for row in validation]
    train_ids = [row.pair_id for row in train]
    outer = quarantine([decorated[pid] for pid in test_ids],
                       [decorated[pid] for pid in (*validation_ids, *train_ids)])
    surviving = set(outer["retained_pilot_pair_ids"])
    validation_ids = sorted(surviving.intersection(validation_ids))
    inner = quarantine([decorated[pid] for pid in validation_ids],
                       [decorated[pid] for pid in train_ids if pid in surviving])
    manifest = {
        "schema": "eapg-phase2-final-prompt-quarantine-v1",
        "test_groups": outer["test_groups"],
        "validation_groups": inner["test_groups"],
        "removed_by_test": outer["removed_pilot_pair_ids"],
        "removed_by_validation": inner["removed_pilot_pair_ids"],
        "train_pair_ids": [pid for pid in inner["retained_pilot_pair_ids"] if pid not in unsupported],
        "unsupported_prompts": unsupported,
        "prompt_keys_by_pair": {pid: sorted(alias.removeprefix(PROMPT_PREFIX) for alias in row.aliases
                                            if alias.startswith(PROMPT_PREFIX))
                                for pid, row in decorated.items()},
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return {"manifest": manifest, "sha256": hashlib.sha256(payload).hexdigest()}


def self_check():
    test = [Pair("test", "test-problem", "int a=999;", "int b;")]
    validation = [Pair("validation", "val-problem", "int aa[]={11,12};", "char bytes[1];")]
    train = [Pair("literal", "train-literal", "int c=7;", "long d;"),
             Pair("prompt", "train-prompt", "void g() {}", "bool e;"),
             Pair("val-prompt", "train-val", "long long f;", "static double t;"),
             Pair("transitive", "train-val", "double q;", "unsigned short x;"),
             Pair("clean", "train-clean", "struct A {};", "struct B {};")]
    tokens = {"test": [[1]], "validation": [[2]], "literal": [[3]], "prompt": [[1]],
              "val-prompt": [[2]], "transitive": [[4]], "clean": [[5]]}
    result = seal_splits(test, validation, train, tokens)
    manifest = result["manifest"]
    assert manifest["removed_by_test"] == ["literal", "prompt"]
    assert manifest["removed_by_validation"] == ["transitive", "val-prompt"]
    assert manifest["train_pair_ids"] == ["clean"]
    assert result == seal_splits(test, validation, list(reversed(train)), tokens)
    supported_tokens = {pid: seq for pid, seq in tokens.items() if pid not in {"test", "clean"}}
    partial = seal_splits(test, validation, train, supported_tokens,
                          unsupported={"test": "context", "clean": "node ID limit"})["manifest"]
    assert partial["removed_by_test"] == ["literal"] and partial["train_pair_ids"] == ["prompt"]
    try:
        seal_splits(test, validation, train, {**tokens, "clean": []})
    except ValueError:
        pass
    else:
        raise AssertionError("Missing final prompt did not block quarantine")
    print(f"Authored literal, prompt, transitive and missing-key checks passed ({result['sha256']}).")


if __name__ == "__main__":
    self_check()
