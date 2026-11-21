"""Rebuild the bounded public GitHub inventory and read CppPerf archive pins."""

from hashlib import sha1
import json
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile

from .expanded_intake import GITHUB, REPOSITORY, digest
from .intake import CPPPERF_REVISION


REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REV = re.compile(r"[0-9a-f]{40}")
CXX = frozenset((".cpp", ".cc", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".tpp", ".ixx", ".cppm"))


def canonical_repo(name):
    if not REPO.fullmatch(name) or any(part in (".", "..") for part in name.split("/")):
        raise ValueError("invalid GitHub repository identity")
    return name.casefold()


def checked_path(name):
    path = PurePosixPath(name)
    if (str(path) != name or path.is_absolute() or ".." in path.parts or
            "\\" in name or not path.parts):
        raise ValueError("invalid pinned source path")
    return name


def changed_cpp_paths(files):
    sides = {"slow_paths": [], "fast_paths": []}
    for item in files:
        after = checked_path(item["filename"])
        before = checked_path(item.get("previous_filename", after))
        status = item["status"]
        if status not in {"added", "removed", "modified", "renamed", "changed", "copied"}:
            raise ValueError(f"unknown GitHub file status: {status}")
        if status not in {"added", "copied"} and (Path(before).suffix.lower() in CXX or Path(before).suffix == ".C"):
            sides["slow_paths"].append(before)
        if status != "removed" and (Path(after).suffix.lower() in CXX or Path(after).suffix == ".C"):
            sides["fast_paths"].append(after)
    return {side: sorted(set(paths)) for side, paths in sides.items()}


def repository_candidates(directory):
    pins, repositories, matches = {}, {}, []

    def load(name):
        raw = (directory / name).read_bytes()
        pins[name] = digest(raw)
        document = json.loads(raw)
        if document["incomplete_results"] is not False:
            raise ValueError(f"incomplete GitHub snapshot: {name}")
        return document["items"]

    for page in range(1, 6):
        suffix = "" if page == 1 else f"-{page}"
        repos = load(f"repository-cpp-snapshot{suffix}.json")
        if len(repos) != 100:
            raise ValueError("expected the complete bounded repository page")
        for row in repos:
            key = canonical_repo(row["repo"])
            if row["fork"] or row["private"] or row["language"] != "C++" or row["stars"] < 1000:
                raise ValueError("repository snapshot violates its fixed query")
            repositories.setdefault(key, row)
        for batch in range(1, 11):
            key = str(batch) if page == 1 else f"p{page}-b{batch}"
            matches.extend(load(f"repository-cpp-commits-{key}.json"))

    rows = {}
    for item in matches:
        repo = canonical_repo(item["repo"])
        meta = repositories.get(repo)
        if (not meta or item["fork"] or meta.get("license") in {None, "NOASSERTION", "OTHER"} or
                not re.search(r"\bfix performance\b", item["subject"], re.I) or len(item["parents"]) != 1):
            continue
        before, after = item["parents"][0], item["sha"]
        if not (REV.fullmatch(before) and REV.fullmatch(after)) or before == after:
            raise ValueError("invalid commit pin")
        key = f"{repo}/{after}"
        name = meta["repo"]
        row = {"corpus": GITHUB, "frame": REPOSITORY, "cluster": "repository/" + repo,
               "repo": name, "id": key, "slow_id": before, "fast_id": after, "source": "GitHub",
               "reported_license": meta["license"], "license": meta["license"],
               "url": f"https://github.com/{name}/commit/{after}",
               "source_evidence": "GitHub commit subject; speed not independently measured"}
        if key in rows and rows[key] != row:
            raise ValueError("inconsistent duplicate search result")
        rows[key] = row
    return {"snapshot_sha256": pins, "rows": sorted(rows.values(), key=lambda row: row["id"])}


def archive_paths(ledger, archive):
    rows = {}
    with ZipFile(archive) as bundle:
        for row in json.loads(ledger.read_bytes())["rows"]:
            pins = row["pins"]
            if "project" not in pins:
                continue
            project = pins["project"]
            repo_key = canonical_repo(project)
            raw = bundle.read(f"CppPerf-{CPPPERF_REVISION}/{pins['metadata_path']}")
            if sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest() != pins["metadata_blob"]:
                raise ValueError("CppPerf metadata Git blob mismatch")
            info = json.loads(raw)["commit_info"]
            before, after = pins["target_commit"], pins["reference_commit"]
            if info["old_sha"] != before or info["new_sha"] != after:
                raise ValueError("archive source pins disagree with the Git blob")
            paths = changed_cpp_paths(info["files_changed"])
            known_paths = set().union(*paths.values())
            for path in row.get("phase_a", {}).get("sources_sha256", {}):
                if path not in known_paths:
                    for side in paths:
                        paths[side].append(checked_path(path))
            key = f"{repo_key}/{after}"
            if key in rows:
                raise ValueError("duplicate archived commit identity")
            rows[key] = {"repo": project, "slow_id": before, "fast_id": after,
                         **{side: sorted(values) for side, values in paths.items()}}
    return rows
