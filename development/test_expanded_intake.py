import csv
from io import StringIO

import pytest

from development.paired_study.expanded_draw import read_problem_metadata
from development.paired_study.expanded_freeze import describe_sources
from development.paired_study.expanded_intake import (
    CODENET, CONTEST, GITHUB, PIE_TRAIN, REPOSITORY, alias_clusters, audit, digest,
    codenet_candidates, contest_candidate, extend, fingerprints, rank,
)
from development.paired_study.expanded_repositories import changed_cpp_paths


def test_code_net_filters_only_metadata_and_requires_train_allowlist():
    header = "problem_id,language,status,cpu_time,user_id,original_language,date,submission_id\n"
    rows = [
        ("p00001", "C++", "Accepted", cpu, user, compiler, date, sid)
        for cpu, user, compiler, date, sid in [
            (300, "u1", "GCC", 1, "s1"), (200, "u1", "GCC", 2, "s2"),
            (100, "u1", "GCC", 3, "s3"), (50, "u1", "Clang", 4, "s4"),
            (25, "u2", "GCC", 5, "s5"), (0, "u1", "GCC", 6, "s6"),
        ]
    ]
    source = StringIO(header)
    source.seek(0, 2)
    csv.writer(source).writerows(rows)
    source.seek(0)
    kwargs = {"judges": {"p00001": "AIZU"}, "train_problems": {"p00001"},
              "published_submissions": {"s1"}}
    assert [x["id"] for x in codenet_candidates("p00001", source, **kwargs)] == ["p00001/s2/s3"]
    with pytest.raises(ValueError, match="allowlist"):
        list(codenet_candidates("p00002", source, **kwargs))


def test_judge_metadata_binding(tmp_path):
    raw = b"id,name,dataset\np00001,Example,AIZU\np00002,Example 2,AtCoder\n"
    (tmp_path / "problem_list.csv").write_bytes(raw)
    assert read_problem_metadata(tmp_path) == ({"p00001": "AIZU", "p00002": "AtCoder"}, digest(raw))


def test_draw_is_permutation_invariant_and_does_not_split_aliases():
    judges = {p: "AIZU" for p in ("a", "b", "c", "d", "e", "f")}
    aliases = alias_clusters(judges, {"a": ["linked"], "b": ["linked"]})
    train = [contest_candidate(PIE_TRAIN, judges, p, "s" + p, "f" + p) for p in "abce"]
    net = [contest_candidate(CODENET, judges, p, "s" + p, "f" + p) for p in "abdf"]
    repo = [{"id": "2", "cluster": "repository/x/y"}, {"id": "1", "cluster": "repository/x/y"}]
    options = dict(aliases=aliases, old_clusters={"contest/aizu/b"}, slots=4, repo_slots=1)
    draw = extend(train, net, repo, **options)
    assert draw == extend(reversed(train), reversed(net), reversed(repo), **options)
    assert [x.get("corpus", GITHUB) for x in draw] == [GITHUB, PIE_TRAIN, CODENET, PIE_TRAIN]
    assert not {x.get("problem_id") for x in draw}.intersection("ab")
    assert draw[0]["id"] == min(repo, key=lambda x: rank(GITHUB, x["cluster"], x["id"]))["id"]


def test_template_normalizes_renaming_and_literals_without_executing():
    left = fingerprints(b' int f() { return g(42, "a"); }\r\n')
    right = fingerprints(b'int x(){return y(17,"b");} // note')
    assert left["template"] == right["template"]
    assert left["normalized_source"] != right["normalized_source"]
    assert left["template"] != fingerprints(b'int x(){return y(17)+2;}')["template"]


def test_hashes_bind_both_sides_and_duplicate_order_does_not_matter():
    row = {"frame": CONTEST, "slow_id": "s1", "fast_id": "s2"}
    slow, fast = {"s1.cpp": b"one"}, {"s2.cpp": b"two"}
    seen = set()
    hashed = describe_sources(row, (slow, fast), seen)
    assert hashed["slow"]["sha256"] == digest(b"one")
    assert hashed["fast"]["sha256"] == digest(b"two")
    assert describe_sources(row, (fast, slow), seen)["intake_stop"] == "intake_duplicate"
    assert describe_sources(row, (slow, {}), seen)["intake_stop"] == "intake_unretrievable"


def test_archive_touch_quarantines_transitive_and_cross_frame_links():
    expanded = [
        {"id": "a", "corpus": PIE_TRAIN, "frame": CONTEST, "cluster": "one", "aliases": ["x"],
         "fingerprints": [{"template": "a"}]},
        {"id": "b", "corpus": CODENET, "frame": CONTEST, "cluster": "two",
         "fingerprints": [{"template": "a", "normalized_source": "b"}]},
        {"id": "c", "corpus": GITHUB, "frame": REPOSITORY, "cluster": "three",
         "fingerprints": [{"normalized_source": "b"}]},
        {"id": "d", "corpus": GITHUB, "frame": REPOSITORY, "cluster": "four"},
        {"id": "e", "corpus": GITHUB, "frame": REPOSITORY, "cluster": "five",
         "intake_stop": "intake_unretrievable"},
    ]
    result = audit(expanded, [{"cluster": "archive", "aliases": ["x"]}])
    assert result["before_quarantine"] == {CONTEST: 1, REPOSITORY: 3, "Union": 3}
    assert result["after_quarantine"] == {CONTEST: 0, REPOSITORY: 2, "Union": 2}
    assert result["after_quarantine_and_intake"] == {CONTEST: 0, REPOSITORY: 1, "Union": 1}
    assert len(result["quarantined_pairs"]) == 3
    assert result["direct_collision_keys"] == {"alias": 1}
    assert result["representatives"] == {"four": GITHUB + ":d"}


def test_failed_representative_is_not_replaced():
    sorted_ids = sorted(("s0", "s1"), key=lambda k: rank(PIE_TRAIN, "cluster", k))
    first, second = ({"id": k, "frame": CONTEST, "corpus": PIE_TRAIN, "cluster": "cluster"} for k in sorted_ids)
    first["intake_stop"] = "intake_unretrievable"
    result = audit([second, first], [])
    assert result["after_quarantine_and_intake"]["Union"] == 1
    assert result["primary_after_quarantine_and_intake"]["Union"] == 0
    assert result["chosen_representatives"] == {"cluster": f"{PIE_TRAIN}:{first['id']}"}


def test_cpp_path_inventory_uses_correct_revision_and_checks_traversal():
    assert changed_cpp_paths([
        {"filename": "renamed/new.cpp", "previous_filename": "old.cpp", "status": "renamed"},
        {"filename": "remove.h", "status": "removed"},
        {"filename": "add.hpp", "status": "added"},
        {"filename": "docs.md", "status": "modified"},
    ]) == {"slow_paths": ["old.cpp", "remove.h"], "fast_paths": ["add.hpp", "renamed/new.cpp"]}
    with pytest.raises(ValueError, match="source path"):
        changed_cpp_paths([{"filename": "../outside.cpp", "status": "modified"}])
