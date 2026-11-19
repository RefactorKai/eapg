"""Blind comparative screening and ranking over source-mapped paired traces."""

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


ARMS = ("rewind", "change_impact", "value_impact", "entry_vote", "target_hotspot",
        "local_count", "diff_order")
OBSERVATION_STATUSES = {"complete", "timeout", "tick_cap", "memory_limit", "crash",
                        "output_limit", "unsupported", "invalid_output"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_pinned(path, expected):
    data = Path(path).read_bytes()
    require(digest(data) == expected, f"{Path(path).name}: SHA-256 mismatch")
    return json.loads(data, object_pairs_hook=unique_fields, parse_constant=nonfinite)


def unique_fields(items):
    fields = dict(items)
    require(len(fields) == len(items), "duplicate JSON object key")
    return fields


def nonfinite(value):
    raise ValueError(f"nonfinite JSON value: {value}")


def write_new(path, value):
    data = canonical(value)
    with Path(path).open("xb") as stream:
        stream.write(data)
    return digest(data)


def fields(obj, keys, context):
    require(isinstance(obj, dict) and obj.keys() == set(keys.split()), f"{context}: unexpected fields")


def identifier(value):
    return isinstance(value, str) and bool(value) and value == value.strip()


def sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def nat(value):
    return type(value) is int and 0 <= value < 2**64


def distinct_ids(values):
    return (isinstance(values, list) and all(identifier(value) for value in values)
            and len(set(values)) == len(values))


def validate_side(side, units):
    fields(side, "output_sha256 work advances episodes", "side")
    require(sha256(side["output_sha256"]) and nat(side["work"]) and nat(side["advances"])
            and isinstance(side["episodes"], list), "invalid side metadata")
    total = aux = 0
    last_query = {}
    for episode in side["episodes"]:
        fields(episode, "scan object query extent entry exit entry_nodes work_nodes nodes other_events", "episode")
        scan, obj, query = key(episode)
        extent, entry, end = (episode[name] for name in ("extent", "entry", "exit"))
        require(identifier(scan) and identifier(obj) and nat(query) and nat(extent)
                and nat(entry) and nat(end) and entry <= end <= extent, "invalid episode coordinates")
        require(query > last_query.get((scan, obj), -1), "duplicate or disordered episode")
        last_query[scan, obj] = query
        total += end - entry
        require(isinstance(episode["nodes"], list), "invalid graph nodes")
        ids = set()
        for node in episode["nodes"]:
            fields(node, "id statement unit value parents", "definition")
            require(identifier(node["id"]) and node["id"] not in ids and identifier(node["statement"])
                    and (node["unit"] is None or identifier(node["unit"]) and node["unit"] in units)
                    and (node["value"] is None or type(node["value"]) is int)
                    and distinct_ids(node["parents"]) and set(node["parents"]) <= ids,
                    "invalid definition or forward, missing, or cyclic edge")
            ids.add(node["id"])
        for root in ("entry_nodes", "work_nodes"):
            require(distinct_ids(episode[root]) and set(episode[root]) <= ids, "invalid graph roots")
        require(isinstance(episode["other_events"], list), "invalid additional event list")
        sites = {scan}
        for event in episode["other_events"]:
            fields(event, "site count roots", "additional event")
            require(identifier(event["site"]) and event["site"] not in sites and nat(event["count"])
                    and distinct_ids(event["roots"]) and set(event["roots"]) <= ids,
                    "invalid or duplicate additional event")
            sites.add(event["site"])
            aux += event["count"]
    require(total == side["advances"], "recorded advances disagree with scan episodes")
    require(not side["episodes"] or total + aux == side["work"],
            "recorded work disagrees with scan and additional events")


def validate_traces(traces):
    fields(traces, "schema cases", "trace ledger")
    require(traces["schema"] == "eapg.paired.traces.v1" and isinstance(traces["cases"], list)
            and traces["cases"], "invalid trace ledger")
    seen = set()
    for case in traces["cases"]:
        fields(case, "id units span_map_sha256 observations", "case")
        require(identifier(case["id"]) and case["id"] not in seen and sha256(case["span_map_sha256"])
                and distinct_ids(case["units"]) and isinstance(case["observations"], list)
                and case["observations"], "invalid or duplicate case")
        seen.add(case["id"])
        streams = defaultdict(list)
        for obs in case["observations"]:
            fields(obs, "stream size status target reference", "observation")
            require(identifier(obs["stream"]) and nat(obs["size"]) and obs["size"] > 0
                    and isinstance(obs["status"], str) and obs["status"] in OBSERVATION_STATUSES,
                    "invalid observation")
            streams[obs["stream"]].append(obs["size"])
            for side in ("target", "reference"):
                if obs[side] is not None:
                    validate_side(obs[side], set(case["units"]))
                else:
                    require(obs["status"] != "complete", "complete observation is missing a side")
        ladders = set()
        for sizes in streams.values():
            sizes.sort()
            require(len(sizes) == len(set(sizes)) == 6
                    and all(b * b == a * c for a, b, c in zip(sizes, sizes[1:], sizes[2:])),
                    "expected six distinct geometric sizes per stream")
            ladders.add(tuple(sizes))
        require(len(ladders) == 1, "streams disagree about the registered size ladder")


def calculate_fit(points):
    if len(points) < 4 or points[-1][0] < 8 * points[0][0]:
        return None
    x = [math.log(size) for size, _, _ in points]
    y = [math.log(target / reference) for _, target, reference in points]
    x_bar = math.fsum(x) / len(x)
    y_bar = math.fsum(y) / len(y)
    slope = (math.fsum((i - x_bar) * (j - y_bar) for i, j in zip(x, y))
             / math.fsum((i - x_bar) ** 2 for i in x))
    squared_error = math.fsum((j - y_bar - slope * (i - x_bar)) ** 2 for i, j in zip(x, y))
    variation = math.fsum((j - y_bar) ** 2 for j in y)
    _, target, reference = points[-1]
    return {"slope": slope, "largest_ratio": target / reference,
            "r_squared": (1 - squared_error / variation) if variation else None}


def fit_stream(observations):
    points, excluded = [], {}
    for obs in sorted(observations, key=lambda obs: obs["size"]):
        if obs["status"] != "complete":
            excluded[str(obs["size"])] = obs["status"]
            continue
        target, reference = obs["target"], obs["reference"]
        if target["output_sha256"] != reference["output_sha256"]:
            excluded[str(obs["size"])] = "output_mismatch"
            continue
        points.append((obs["size"], target["work"], reference["work"]))
    invalid = any(reason in {"invalid_output", "output_mismatch"} for reason in excluded.values())
    zero = any(target == 0 or reference == 0 for _, target, reference in points)
    fit = None if invalid or zero else calculate_fit(points)
    drop_largest = None if invalid or zero else calculate_fit(points[:-1])
    status = ("output_failure" if invalid else "zero_cost" if zero
              else "insufficient_scales" if fit is None else "fitted")
    return {"status": status,
            "points": [{"size": n, "target": t, "reference": r, "difference": t - r}
                       for n, t, r in points],
            "excluded": excluded, "fit": fit, "drop_largest": drop_largest}


def key(episode):
    return episode["scan"], episode["object"], episode["query"]


def reachable(episode, roots):
    nodes = {node["id"]: node for node in episode["nodes"]}
    todo, paths = [(node, [node]) for node in reversed(roots)], {}
    while todo:
        current, path = todo.pop()
        if current in paths:
            continue
        paths[current] = path
        todo.extend((parent, [*path, parent]) for parent in reversed(nodes[current]["parents"]))
    return {node: (nodes[node], path) for node, path in paths.items()}


def units_in(definitions):
    return {node["unit"] for node, _ in definitions.values() if node["unit"] is not None}


def value_changed_units(left, right):
    by_statement = []
    for nodes in (left, right):
        grouped = defaultdict(list)
        for node, _ in nodes.values():
            grouped[node["statement"]].append(node)
        by_statement.append(grouped)
    changes = set()
    for statement in by_statement[0].keys() | by_statement[1].keys():
        a, b = (side.get(statement, []) for side in by_statement)
        if len(a) == len(b) == 1 and a[0]["value"] is not None and a[0]["value"] == b[0]["value"]:
            continue
        changes.update(node["unit"] for node in a + b if node["unit"] is not None)
    return changes


def account_side(episodes):
    previous_exit, rewind, skip, first, last, prior_by_episode = {}, {}, {}, {}, {}, {}
    advances = 0
    for episode in episodes:
        scan, obj, query = key(episode)
        group = scan, obj
        entry, end = episode["entry"], episode["exit"]
        first.setdefault(group, entry)
        last[group] = end
        prior_by_episode[scan, obj, query] = previous_exit.get(group)
        gap = previous_exit.get(group, entry) - entry
        rewind[scan, obj, query] = max(0, gap)
        skip[scan, obj, query] = max(0, -gap)
        advances += end - entry
        previous_exit[group] = end
    endpoint = sum(last[group] - entry for group, entry in first.items())
    summary = {"advances": advances, "endpoint": endpoint, "rewind": sum(rewind.values()),
               "forward_skip": sum(skip.values())}
    require(advances == endpoint + summary["rewind"] - summary["forward_skip"],
            "scan accounting identity failed")
    return rewind, prior_by_episode, summary


def event_paths(episode):
    events = [(episode["scan"], episode["exit"] - episode["entry"], episode["work_nodes"])]
    events.extend((event["site"], event["count"], event["roots"]) for event in episode["other_events"])
    return {site: (count, reachable(episode, roots)) for site, count, roots in events}


def local_ranks(sides):
    hotspot, local_count = Counter(), Counter()
    for episode in sides[0]:
        for site, (count, definitions) in event_paths(episode).items():
            for unit in {node["unit"] for node, _ in definitions.values()
                         if node["statement"] == site and node["unit"] is not None}:
                hotspot[unit] += count
    for side, sign in zip(sides, (1, -1)):
        for episode in side:
            for node in episode["nodes"]:
                if node["unit"] is not None:
                    local_count[node["unit"]] += sign
    scores = {}
    if sides[0]:
        scores["target_hotspot"] = hotspot
    if all(sides):
        scores["local_count"] = local_count
    return scores


def observed_ranks(obs):
    sides = [obs[name]["episodes"] for name in ("target", "reference")]
    scores = local_ranks(sides)
    mappings = [{key(episode): episode for episode in side} for side in sides]
    if not mappings[0] or mappings[0].keys() != mappings[1].keys():
        return {"reason": "unmatched_episodes"}, scores
    if any(episode["extent"] != mappings[1][identity]["extent"]
           for identity, episode in mappings[0].items()):
        return {"reason": "mismatched_object_extent"}, scores
    (target_rewinds, target_prior, target_account), (reference_rewinds, reference_prior, reference_account) = (
        map(account_side, sides)
    )
    scores.update({arm: Counter() for arm in ("rewind", "change_impact", "value_impact", "entry_vote")})
    paths, assigned = [], Counter()
    joint = unassigned = 0
    for identity, target in mappings[0].items():
        reference = mappings[1][identity]
        target_events, reference_events = map(event_paths, (target, reference))
        for site in target_events.keys() | reference_events.keys():
            target_count, target_work = target_events.get(site, (0, {}))
            reference_count, reference_work = reference_events.get(site, (0, {}))
            delta = target_count - reference_count
            if delta > 0:
                for unit in units_in(target_work) | units_in(reference_work):
                    scores["change_impact"][unit] += delta
                for unit in value_changed_units(target_work, reference_work):
                    scores["value_impact"][unit] += delta
        entry_paths = [reachable(row, row["entry_nodes"]) for row in (target, reference)]
        entry_units = units_in(entry_paths[0]) | units_in(entry_paths[1])
        if target["entry"] != reference["entry"]:
            scores["entry_vote"].update(entry_units)
        delta = target_rewinds[identity] - reference_rewinds[identity]
        if delta == 0:
            continue
        if target["entry"] == reference["entry"] or target_prior[identity] != reference_prior[identity]:
            unassigned += delta
            continue
        if len(entry_units) == 1:
            unit, = entry_units
            assigned[unit] += delta
            for side, episode, defs in zip(("target", "reference"), (target, reference), entry_paths):
                graph = {node["id"]: node["statement"] for node in episode["nodes"]}
                for node, path in defs.values():
                    if node["unit"] == unit:
                        paths.append({"episode": list(identity), "side": side, "unit": unit,
                                      "distance": delta, "path": [graph[item] for item in path]})
                        break
        elif entry_units:
            joint += delta
        else:
            unassigned += delta
    scores["rewind"].update(assigned)
    delta = target_account["rewind"] - reference_account["rewind"]
    require(sum(assigned.values()) + joint + unassigned == delta, "unbalanced source attribution")
    return {"target": target_account, "reference": reference_account, "net_rewind_delta": delta,
            "assigned_distance": dict(assigned), "joint_distance": joint, "unassigned_distance": unassigned,
            "unexplained_work_delta": ((obs["target"]["work"] - obs["reference"]["work"])
                                       - (target_account["advances"] - reference_account["advances"])),
            "paths": paths}, scores


def recommendation(units, scores, alert, status=None):
    if status is not None:
        return {"status": status, "alert": alert, "candidates": [], "ranking": []}
    ordered = [unit for unit in units if scores[unit] > 0]
    groups = defaultdict(list)
    for unit in ordered:
        groups[scores[unit]].append(unit)
    ranking = [groups[score] for score in sorted(groups, reverse=True)]
    status = "abstain" if not ranking else "ranked" if len(ranking[0]) == 1 else "tie"
    return {"status": status, "alert": alert, "candidates": ordered, "ranking": ranking}


def analyze_case(case):
    streams = defaultdict(list)
    for obs in case["observations"]:
        streams[obs["stream"]].append(obs)
    screens = [{"stream": stream, **fit_stream(rows)} for stream, rows in sorted(streams.items())]
    output = {"id": case["id"], "span_map_sha256": case["span_map_sha256"],
              "screen": screens, "accounting": []}
    fits = [screen["fit"] for screen in screens]
    if any(fit is None for fit in fits):
        status = ("measurement_failure" if any(s["status"] == "output_failure" for s in screens)
                  else "insufficient")
        output["arms"] = {arm: recommendation([], {}, None, status) for arm in ARMS}
        return output
    alert = all(fit["slope"] >= 0.50 and fit["largest_ratio"] >= 1.50 for fit in fits)
    if not alert:
        output["arms"] = {arm: recommendation([], {}, False, "no_alert") for arm in ARMS}
        return output
    sizes = set.intersection(*({point["size"] for point in screen["points"]} for screen in screens))
    units = case["units"]
    all_scores = {"diff_order": Counter({unit: len(units) - i for i, unit in enumerate(units)})}
    supported = set(ARMS) if sizes else {"diff_order"}
    for screen in screens:
        if not sizes:
            break
        stream, n = screen["stream"], max(sizes)
        obs = next(obs for obs in streams[stream] if obs["size"] == n)
        account, scores = observed_ranks(obs)
        output["accounting"].append({"stream": stream, "size": n, **account})
        supported.intersection_update(set(scores) | {"diff_order"})
        for arm, arm_scores in scores.items():
            all_scores.setdefault(arm, Counter()).update(arm_scores)
    output["arms"] = {
        arm: recommendation(units, all_scores.get(arm, Counter()), True,
                            "unsupported" if arm not in supported else None)
        for arm in ARMS
    }
    return output


def predict(traces, registration, registration_sha256):
    validate_traces(traces)
    require(registration["schema"] == "eapg.paired.registration.v1"
            and set(registration["arms"]) == set(ARMS), "registration does not pin these prediction arms")
    registered = {case["id"]: (case["units"], case["span_map_sha256"]) for case in registration["cases"]}
    observed = {case["id"]: (case["units"], case["span_map_sha256"]) for case in traces["cases"]}
    require(len(registration["cases"]) == len(registered) and observed == registered,
            "trace cases, source maps, or canonical change units differ from the draw")
    results = [analyze_case(case) for case in traces["cases"]]
    ledger = {"schema": "eapg.paired.predictions.v1", "registration_sha256": registration_sha256,
              "cases": [{k: row[k] for k in ("id", "span_map_sha256", "arms")} for row in results]}
    evidence = [{k: row[k] for k in ("id", "span_map_sha256", "screen", "accounting")} for row in results]
    return ledger, evidence


def check_workloads(traces, workloads):
    fields(workloads, "schema cases", "workload manifest")
    require(workloads["schema"] == "eapg.paired.workloads.v1" and isinstance(workloads["cases"], list),
            "invalid workload manifest")
    cases = {}
    for item in workloads["cases"]:
        fields(item, "id streams sizes", "workload case")
        require(identifier(item["id"]) and item["id"] not in cases
                and distinct_ids(item["streams"]) and item["streams"]
                and isinstance(item["sizes"], list) and all(nat(size) for size in item["sizes"]),
                "invalid or duplicate workload case")
        cases[item["id"]] = [(stream, size) for stream in item["streams"] for size in item["sizes"]]
    actual = {case["id"]: sorted((obs["stream"], obs["size"]) for obs in case["observations"])
              for case in traces["cases"]}
    require(actual == {case: sorted(grid) for case, grid in cases.items()},
            "trace observations differ from the registered workload grid")


def main():
    from .score import validate_committed_draw

    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("traces", "traces-sha256", "registration", "registration-sha256", "output", "evidence"):
        cli.add_argument(f"--{name}", required=True)
    cli.add_argument("--workloads", help="Pinned workload grid, required for confirmatory predictions")
    args = cli.parse_args()
    registration = read_pinned(args.registration, args.registration_sha256)
    validate_committed_draw(registration)
    require(registration["pins"]["methods"] == digest(Path(__file__).read_bytes()),
            "active predictor differs from the committed methods")
    traces = read_pinned(args.traces, args.traces_sha256)
    ledger, evidence = predict(traces, registration, args.registration_sha256)
    if registration["phase"] == "confirmatory":
        require(args.workloads, "a confirmatory registration requires its committed workload grid")
        check_workloads(traces, read_pinned(args.workloads, registration["pins"]["workloads"]))
    require(len({Path(path).resolve() for path in (args.output, args.evidence)}) == 2
            and not Path(args.output).exists() and not Path(args.evidence).exists(),
            "prediction outputs must be separate new files")
    print(write_new(args.output, ledger), args.output)
    print(write_new(args.evidence, {"traces_sha256": args.traces_sha256,
                                   "registration_sha256": args.registration_sha256, "cases": evidence}),
          args.evidence)


if __name__ == "__main__":
    main()
