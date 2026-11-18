"""Join separately sealed synthetic study ledgers under registered code pins.

Run --print-revision before registration. Scoring needs the independently
recorded scorer, prediction runner, pipeline, baseline, and raw ledger digests.
Only canonical, source-free ledgers enter this role.
"""

import argparse
from hashlib import sha256
from pathlib import Path

from score_synthetic import digest, require, score
from synthetic_frame import canonical, commitment, read_canonical


HERE = Path(__file__).resolve().parent
CODE = (Path(__file__).name, "score_synthetic.py", "score_external.py", "replay_pilot_contrast.py", "synthetic_frame.py")
LEDGERS = ("draw", "labels", "predictions")


def scoring_revision():
    """Compute the registered local scoring bundle digest without ledgers."""
    return commitment({name: sha256((HERE / name).read_bytes()).hexdigest() for name in CODE})


def score_study(draw, labels, predictions, *, draw_sha256, labels_sha256, predictions_sha256,
                scorer_sha256, runner_sha256, pipeline_sha256, baseline_sha256):
    """Verify all commitments before calling the existing estimator."""
    require(digest(scorer_sha256) and scoring_revision() == scorer_sha256, "Scorer bundle digest mismatch")
    require(type(predictions) is dict and predictions.get("schema") == "eapg-synthetic-predictions-v1",
            "Wrong predictions ledger schema")
    for name, expected in (("runner", runner_sha256), ("pipeline", pipeline_sha256), ("baseline", baseline_sha256)):
        require(digest(expected) and predictions.get(f"{name}_sha256") == expected,
                f"Prediction {name} digest mismatch")
    for name, document, expected in zip(LEDGERS, (draw, labels, predictions),
                                        (draw_sha256, labels_sha256, predictions_sha256)):
        require(digest(expected) and commitment(document) == expected, f"{name.title()} ledger digest mismatch")
    return score(draw, labels, predictions, draw_sha256=draw_sha256, labels_sha256=labels_sha256)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--print-revision", action="store_true", help="print this local scorer's bundle SHA-256")
    for name in LEDGERS:
        cli.add_argument(f"--{name}", type=Path)
        cli.add_argument(f"--{name}-sha256")
    code_pins = ("scorer", "runner", "pipeline", "baseline")
    for name in code_pins:
        cli.add_argument(f"--{name}-sha256")
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    pins = {f"{name}_sha256": getattr(args, f"{name}_sha256") for name in (*LEDGERS, *code_pins)}
    paths = {name: getattr(args, name) for name in LEDGERS}
    options = (*pins.values(), *paths.values(), args.output)
    try:
        if args.print_revision:
            require(all(value is None for value in options), "Use --print-revision on its own")
            print(scoring_revision())
            return
        require(all(value is not None for value in options), "Provide all three ledgers, their pins, code pins, and output")
        require(digest(args.scorer_sha256) and scoring_revision() == args.scorer_sha256, "Scorer bundle digest mismatch")
        require(not args.output.exists(), "Score output already exists")
        documents = [read_canonical(paths[name], pins[f"{name}_sha256"]) for name in LEDGERS]
        raw = canonical(score_study(*documents, **pins))
        with args.output.open("xb") as stream:
            stream.write(raw)
    except (OSError, ValueError) as error:
        cli.error(str(error))
    print(f"{sha256(raw).hexdigest()}  {args.output.name}")


if __name__ == "__main__":
    main()
