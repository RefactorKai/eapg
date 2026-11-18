"""Evaluate the prospective primary gate under a pre-data family model.

Each retained family has an independent contrast X in {-1, 0, 1}. The two
positive slots have identical paired differences when both qualify. Set
P(X != 0) = q and E[X] = delta, so variance is q - delta**2 and the signed
masses are (q + delta)/2 and (q - delta)/2. Each of the 80 drawn families is
retained independently with probability r, independently of X. Under 60
retained families the primary gate cannot pass.

The ideal bootstrap lower endpoint is positive exactly when the empirical
bootstrap distribution puts less than 1/40 of its mass at means <= 0. The
registered 10,000-draw rule instead requires at most 249 nonpositive draws.
Conditional on a fresh random bootstrap seed, that count would be binomial
with event probability given by the exact bootstrap distribution. The script
evaluates the ideal rule as an approximation to the fixed-seed scorer.
"""

import argparse
from fractions import Fraction
from functools import cache
from itertools import product
from math import comb, lcm


DRAWN, MIN_RETAINED = 80, 60
LOWER_TAIL_DENOMINATOR = 40
EFFECTS = (Fraction(0), Fraction("0.20"))
BINOMIAL = tuple(tuple(comb(n, k) for k in range(n + 1)) for n in range(DRAWN + 1))


@cache
def powers(base):
    return tuple(base**exponent for exponent in range(DRAWN + 1))


def bootstrap_nonpositive_weight(n, positive, negative):
    """Count nonpositive ordered bootstrap resamples among the n**n possibilities."""
    plus, minus, zero = (powers(count) for count in (positive, negative, n - positive - negative))
    weight = 0
    for nonzero, choose_nonzero in enumerate(BINOMIAL[n]):
        sign_weight = sum(BINOMIAL[nonzero][k] * plus[k] * minus[nonzero - k]
                          for k in range(nonzero // 2 + 1))
        weight += choose_nonzero * zero[n - nonzero] * sign_weight
    return weight


@cache
def cutoffs(n):
    """For each observed discordant count, return the first passing positive count."""
    limits = []
    total = n**n
    for discordant in range(n + 1):
        # At fixed discordance, replacing a negative family by a positive can only increase a resample mean.
        low, high = discordant // 2 + 1, discordant + 1
        while low < high:
            positive = (low + high) // 2
            weight = bootstrap_nonpositive_weight(n, positive, discordant - positive)
            if LOWER_TAIL_DENOMINATOR * weight < total:
                high = positive
            else:
                low = positive + 1
        limits.append(low)
    return tuple(limits)


def weights(probabilities):
    scale = lcm(*(value.denominator for value in probabilities))
    return scale, tuple(int(value * scale) for value in probabilities)


def gate_probability(n, delta, discordance):
    scale, counts = weights(((discordance + delta) / 2, (discordance - delta) / 2, 1 - discordance))
    plus, minus, zero = map(powers, counts)
    weight = 0
    for discordant, cutoff in enumerate(cutoffs(n)):
        sign_weight = sum(BINOMIAL[discordant][k] * plus[k] * minus[discordant - k]
                          for k in range(cutoff, discordant + 1))
        weight += BINOMIAL[n][discordant] * zero[n - discordant] * sign_weight
    return Fraction(weight, scale**n)


def retention_weights(retention):
    denominator, (yes, no) = weights((retention, 1 - retention))
    return {n: Fraction(BINOMIAL[DRAWN][n] * yes**n * no**(DRAWN - n), denominator**DRAWN)
            for n in range(MIN_RETAINED, DRAWN + 1)}


def check_enumeration():
    observed = (1, 1, -1, 0)
    assert bootstrap_nonpositive_weight(4, 2, 1) == sum(sum(draw) <= 0 for draw in product(observed, repeat=4))
    assert cutoffs(4) == (1, 2, 3, 3, 4)
    assert gate_probability(4, Fraction("0.20"), Fraction("0.20")) == Fraction("0.0272")


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--discordance", nargs="+", type=Fraction,
                     default=list(map(Fraction, (".20", ".30", ".34", ".40", ".60", "1"))))
    cli.add_argument("--retention", nargs="+", type=Fraction,
                     default=list(map(Fraction, (".70", ".75", ".80", ".85", ".90", "1"))))
    args = cli.parse_args()
    if any(not EFFECTS[-1] <= q <= 1 for q in args.discordance):
        cli.error("Discordance must be between .20 and 1 to support both effect sizes")
    if any(not 0 <= r <= 1 for r in args.retention):
        cli.error("Retention must be between 0 and 1")
    check_enumeration()

    gates = {(q, delta): {n: gate_probability(n, delta, q) for n in range(MIN_RETAINED, DRAWN + 1)}
             for q in args.discordance for delta in EFFECTS}
    print("Ideal bootstrap primary gate. Type I uses delta=0 and power uses delta=.20.")
    print("Discordance     Type I at 60     Type I at 80     Power at 60     Power at 80")
    for q in args.discordance:
        values = [gates[q, delta][n] for delta in EFFECTS for n in (MIN_RETAINED, DRAWN)]
        print(f"{float(q):11.2f}" + "".join(f"{float(value):16.2%}" for value in values))

    print("\nRetention   P(at least 60)  Discordance   Type I after attrition  Power after attrition")
    for r in args.retention:
        sample_sizes = retention_weights(r)
        for q in args.discordance:
            values = [sum(mass * gates[q, delta][n] for n, mass in sample_sizes.items()) for delta in EFFECTS]
            print(f"{float(r):9.2f}{float(sum(sample_sizes.values())):17.2%}{float(q):13.2f}"
                  + "".join(f"{float(value):23.2%}" for value in values))


if __name__ == "__main__":
    main()
