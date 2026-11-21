"""Metadata-only draws and static overlap grouping for the expanded cohort."""

from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
import re

from artifacts.phase1_correction.phase2_custody_and_probes import KEYWORDS, LEX

from .quarantine import components


SEED = "eapg-expansion-v1"
PIE_TRAIN_SHA256 = "114d595edfc4186b8151da983289bd3ad1082931544e14c18bbe121a3d6c810e"
PIE_TRAIN_COUNT = 77967
PIE_TRAIN_PROBLEMS = 1474
PIE_TRAIN = "pie-train"
PIE_VALIDATION = "pie-validation"
CODENET = "codenet"
GITHUB = "github-performance-fix"
CONTEST = "Contest"
REPOSITORY = "Repository"
PIE_VALIDATION_SHA256 = "6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab"
ARCHIVED_LEDGER_SHA256 = "e9b5b65c26727538b887047fd16b863850619783e111957a95dcec2ed2c05345"

PIE_PINS = {
    PIE_TRAIN: ("pie_train.jsonl", "1jtUQ1d6wtc-F4J62RROuRXXNW2q13-WX", PIE_TRAIN_SHA256),
    PIE_VALIDATION: ("pie_val.jsonl", "1Z01XyFil-w2XN1i9TNn7idzZ2DzDz-XL", PIE_VALIDATION_SHA256),
}
CODE_NET_URL = (
    "https://codait-cos-dax.s3.us.cloud-object-storage.appdomain.cloud/"
    "dax-project-codenet/1.0.0/Project_CodeNet.tar.gz"
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(value).hexdigest()


def rank(corpus, cluster, pair=None):
    fields = [SEED, corpus, cluster]
    if pair is not None:
        fields.append(pair)
    return digest(canonical(fields)), fields[-1]


def problem_key(judges, problem):
    return "contest/" + judges[problem].casefold() + "/" + problem


def contest_candidate(corpus, judges, problem, slow, fast):
    return {
        "corpus": corpus, "frame": CONTEST, "cluster": problem_key(judges, problem),
        "problem_id": problem, "id": "/".join((problem, slow, fast)),
        "slow_id": slow, "fast_id": fast,
    }


def pinned_pie_rows(path, corpus):
    name, _, pin = PIE_PINS[corpus]
    if path.name != name:
        raise ValueError(f"expected the public {name} input")
    checksum = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
        if checksum.hexdigest() != pin:
            raise ValueError(f"expected the exact public {corpus} release")
        source.seek(0)
        yield from map(json.loads, source)


def read_pie_train(path, judges):
    """Read identifiers and released ordering, not code or new run outcomes."""
    rows = {}
    submissions = set()
    for row in pinned_pie_rows(path, PIE_TRAIN):
        problem, slow, fast = (row[key] for key in ("problem_id", "src_id", "tgt_id"))
        pair = contest_candidate(PIE_TRAIN, judges, problem, slow, fast)
        if pair["id"] in rows or slow == fast or not (
            row["src_status"] == row["tgt_status"] == "Accepted" and
            0 < row["tgt_agg_runtime"] < row["src_agg_runtime"]
        ):
            raise ValueError("unexpected PIE train metadata")
        rows[pair["id"]] = pair
        submissions.update((slow, fast))
    problems = {r["problem_id"] for r in rows.values()}
    if len(rows) != PIE_TRAIN_COUNT or len(problems) != PIE_TRAIN_PROBLEMS:
        raise ValueError("expected the exact public PIE train release")
    return list(rows.values()), problems, submissions


def codenet_candidates(problem, lines, *, judges, train_problems, published_submissions):
    if problem not in train_problems:
        raise ValueError("CodeNet problem is not on the public PIE train allowlist")
    trajectories = defaultdict(list)
    for row in csv.DictReader(lines):
        if row["problem_id"] != problem:
            raise ValueError("CodeNet metadata on wrong problem")
        if row["language"] != "C++" or row["status"] != "Accepted":
            continue
        cpu = row["cpu_time"]
        if cpu and int(cpu) > 0:
            trajectories[row["user_id"], row["original_language"]].append(
                (int(row["date"]), row["submission_id"], int(cpu)))
    for trajectory in trajectories.values():
        trajectory.sort()
        for (before, slow, slow_time), (after, fast, fast_time) in zip(trajectory, trajectory[1:]):
            if before < after and slow_time > fast_time and not (
                {slow, fast} & published_submissions
            ):
                yield contest_candidate(CODENET, judges, problem, slow, fast)


def representatives(corpus, rows, aliases):
    groups = {}
    for row in rows:
        group = aliases.get(row["cluster"], row["cluster"])
        candidate = rank(corpus, group, row["id"])
        if group not in groups or candidate < groups[group][0]:
            groups[group] = candidate, row
    for group in sorted(groups, key=lambda cluster: rank(corpus, cluster)):
        yield group, groups[group][1]


def extend(train, codenet, repositories, *, aliases, old_clusters, slots=500, repo_slots=100):
    if not 0 <= repo_slots <= slots <= 500:
        raise ValueError("extension exceeds the fixed pair cap")
    taken = {aliases.get(key, key) for key in old_clusters}
    selected = []
    for group, row in representatives(GITHUB, repositories, aliases):
        if len(selected) == repo_slots:
            break
        taken.add(group)
        selected.append(row)
    pools = [iter(representatives(corpus, rows, aliases))
             for corpus, rows in ((PIE_TRAIN, train), (CODENET, codenet))]
    while len(selected) < slots and pools:
        pool = pools.pop(0)
        for group, row in pool:
            if group not in taken:
                taken.add(group)
                selected.append(row)
                pools.append(pool)
                break
    return selected


def alias_clusters(judges, problem_aliases):
    keys = {
        problem_key(judges, p): {("alias", name) for name in aliases}
        for p, aliases in problem_aliases.items()
    }
    return {key: family[0] for family in components(keys) for key in family}


def fingerprints(raw):
    source = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").strip()
    text = source.decode("utf-8", errors="surrogateescape")
    template = []
    for token in LEX.finditer(text):
        kind = token.lastgroup
        value = token.group()
        if kind == "comment":
            continue
        if kind in {"num", "quoted", "raw"}:
            value = "<" + kind + ">"
        if kind == "id" and value not in KEYWORDS:
            value = "<id>"
        template.append(value)
    normalized_tokens = json.dumps(template, separators=(",", ":"), ensure_ascii=True)
    return {"normalized_source": digest(source), "template": digest(normalized_tokens.encode("ascii"))}


def cluster_keys(row):
    keys = {("cluster", row["cluster"])}
    keys.update(("alias", key) for key in row.get("aliases", ()))
    keys.update(("raw_source", value) for value in row.get("raw_source_hashes", ()))
    for source in row.get("fingerprints", ()):
        keys.update(source.items())
    return keys


def audit(expanded, archived):
    """Count distinct connected components and propagate direct archive collisions."""
    pool = list(expanded)
    expanded = {r["corpus"] + ":" + r["id"]: r for r in pool}
    if len(expanded) != len(pool):
        raise ValueError("duplicate pair inventory keys")
    archived = {"archive:" + str(i): row for i, row in enumerate(archived)}
    all_rows = expanded | archived
    keys = {label: cluster_keys(row) for label, row in all_rows.items()}
    archive_keys = set().union(*(keys[label] for label in archived))
    direct = Counter(key for key, _ in set().union(*(keys[label] for label in expanded)) & archive_keys)
    before, after, after_intake, primary = Counter(), Counter(), Counter(), Counter()
    quarantined = set()
    rep = {}
    chosen = {}
    group_by_row = {}
    for family in components(keys):
        members = [label for label in family if label in expanded]
        if not members:
            continue
        labels = {expanded[label]["frame"] for label in members} | {"Union"}
        before.update(labels)
        cluster = min(all_rows[label]["cluster"] for label in family)
        group_by_row.update({label: cluster for label in members})
        if len(family) != len(members):
            quarantined.update(members)
            continue
        after.update(labels)
        representative = min(members, key=lambda label: (
            rank(expanded[label]["corpus"], cluster, expanded[label]["id"]), label))
        chosen[cluster] = representative
        if not expanded[representative].get("intake_stop"):
            rep[cluster] = representative
            primary.update({expanded[representative]["frame"], "Union"})
        usable = [label for label in members if not expanded[label].get("intake_stop")]
        if usable:
            after_intake.update({expanded[label]["frame"] for label in usable} | {"Union"})
    return {
        "before_quarantine": {k: before[k] for k in (CONTEST, REPOSITORY, "Union")},
        "after_quarantine": {k: after[k] for k in (CONTEST, REPOSITORY, "Union")},
        "after_quarantine_and_intake": {k: after_intake[k] for k in (CONTEST, REPOSITORY, "Union")},
        "primary_after_quarantine_and_intake": {k: primary[k] for k in (CONTEST, REPOSITORY, "Union")},
        "direct_collision_keys": dict(direct),
        "quarantined_pairs": sorted(quarantined),
        "cluster_by_pair": group_by_row,
        "chosen_representatives": chosen,
        "representatives": rep,
    }


def index_pie_sources(path, corpus, ids):
    sources = {}
    for row in pinned_pie_rows(path, corpus):
        problem = row["problem_id"]
        for side in ("src", "tgt"):
            key = problem, row[f"{side}_id"]
            if key in ids:
                raw = row[f"{side}_code"].encode("utf-8")
                if key in sources and sources[key] != raw:
                    raise ValueError(f"source bytes disagree for {key}")
                sources[key] = raw
    if ids != sources.keys():
        raise ValueError("PIE release does not cover every pinned source")
    return sources


def archive_metadata(path, judges, aliases):
    data = Path(path).read_bytes()
    if digest(data) != ARCHIVED_LEDGER_SHA256:
        raise ValueError("expected the frozen 147-pair ledger")
    rows = []
    for record in json.loads(data)["rows"]:
        pins = record["pins"]
        if record["corpus"] == PIE_VALIDATION:
            p = pins["problem_id"]
            row = contest_candidate(PIE_VALIDATION, judges, p, pins["target_submission"],
                                    pins["reference_submission"])
            row["aliases"] = aliases.get(p, [])
        else:
            hashes = set()
            for entry in record.get("phase_a", {}).get("sources_sha256", {}).values():
                if isinstance(entry, dict):
                    hashes.update(x for x in entry.values()
                                  if isinstance(x, str) and re.fullmatch(r"[a-f0-9]{64}", x))
            row = {
                "cluster": "repository/" + pins["project"].casefold(), "frame": REPOSITORY,
                "id": pins["reference_commit"], "slow_id": pins["target_commit"],
                "fast_id": pins["reference_commit"], "repo": pins["project"],
                "raw_source_hashes": sorted(hashes),
            }
        rows.append(row)
    return rows
