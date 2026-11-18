"""Run fixed authored quadratic/linear and linear/linear timing controls."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from runtime_screen import screen


SIZES = (1024, 2048, 4096, 8192, 16384)
SEEDS = (42, 43, 44)
CPP = """#include <cstdint>
#include <iostream>
int main() {{
    std::uint64_t n, seed;
    if (!(std::cin >> n >> seed)) return 1;
    const auto delta = seed % 8 + 1;
    volatile std::uint64_t sum = 0;
    {loop}
    std::cout << sum << '\\n';
}}
"""
QUADRATIC = CPP.format(loop="for (std::uint64_t i = 0; i < n; ++i)\n"
                            "        for (std::uint64_t j = 0; j < n; ++j) sum += delta;")
LINEAR = CPP.format(loop="for (std::uint64_t i = 0; i < n; ++i) sum += n * delta;")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path, help="fresh JSON report path")
    args = cli.parse_args()
    if args.output.exists():
        cli.error("output already exists")
    workload = {"inputs": [{"n": n, "seed": seed, "stdin": f"{n} {seed}\n",
                            "expected_stdout": f"{n * n * (seed % 8 + 1)}\n"}
                           for seed in SEEDS for n in SIZES]}
    results = {}
    for label, slow in (("quadratic_vs_linear", QUADRATIC), ("linear_vs_linear", LINEAR)):
        samples, per_seed = screen(workload, {"slow": slow, "fast": LINEAR})
        results[label] = {"samples": samples, "per_seed": per_seed,
                          "timing_screen_pass": all(row["timing_screen_pass"] for row in per_seed.values())}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump({"schema": "eapg-authored-timing-controls-v1", "sizes": SIZES, "seeds": SEEDS,
                   "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                   "timing_harness_sha256": sha256(Path(__file__).with_name("runtime_screen.py").read_bytes()).hexdigest(),
                   "controls": results}, stream, indent=2)
        stream.write("\n")
    print(json.dumps({label: {"samples": len(result["samples"]), "pass": result["timing_screen_pass"],
                             "per_seed": {seed: [row["ratio_slope"], row["largest_size_ratio"]]
                                          for seed, row in result["per_seed"].items()}}
                      for label, result in results.items()}, indent=2))


if __name__ == "__main__":
    main()
