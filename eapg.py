"""Unified CLI entrypoint for the EAPG research pipeline and artifact verification."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def _resolve_repo_root() -> Path:
    env_root = os.environ.get("EAPG_REPO_ROOT")
    for cand in ((Path(env_root).resolve(),) if env_root else ()) + (Path(__file__).resolve().parent, Path.cwd()):
        if (cand / "SHA256SUMS").exists() and (cand / "pipeline.py").exists():
            return cand
    raise FileNotFoundError(
        "EAPG source checkout not found. Run from a repository checkout or editable install (`pip install -e .`)."
    )


ROOT = _resolve_repo_root()
CALLER_CWD = Path.cwd()
CANDIDATE_ARCHIVE_SHA256 = "ab43a6e4882bbba6d2f54a9dc9be99dfeb031d5d5633c265e993d53109f41563"
CANDIDATE_PROSPECTIVE_SHA256 = "2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383"
RESULTS_MULTIAGENT = ROOT / "development/prospective_multiagent_results.json"
SKIPPED_TEST_STATUS = 3
VERIFY_SKIPPED_STATUS = 2

COMMON_VERIFY_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("-B", "verify_release.py"),
    ("-B", "development/replay_pilot_contrast.py"),
    ("-B", "development/replay_pilot_resplit.py"),
    ("-B", "-S", "development/replay_resplit_ablation.py", "--verify-manuscript-table", "--quiet"),
    ("-B", "development/verify_weighted_panel.py"),
    ("-B", "-S", "development/verify_manuscript_pilot.py"),
    ("-B", "-S", "artifacts/paired_development/replay.py"),
    ("-B", "-S", "development/test_prospective_multiagent_study.py"),
    ("-B", "development/test_assemble_pilot_resplit.py"),
    ("-B", "-S", "development/test_resplit_ablation.py"),
    ("-B", "-S", "development/test_predict_external_contract.py"),
    ("-B", "development/test_prediction_contract.py"),
    ("-B", "development/test_score_synthetic.py"),
    ("-B", "development/test_synthetic_frame.py"),
    ("-B", "development/test_synthetic_quarantine.py"),
    ("-B", "development/test_synthetic_oracle.py"),
    ("-B", "development/test_synthetic_trace.py"),
    ("-B", "development/test_synthetic_study_predict.py"),
    ("-B", "development/test_synthetic_study_score.py"),
)

FAST_VERIFY_COMMANDS: tuple[tuple[str, ...], ...] = COMMON_VERIFY_COMMANDS[:8]

REPLAY_TARGETS: dict[str, tuple[str, ...]] = {
    "release": ("-B", "verify_release.py"),
    "pilot": ("-B", "development/replay_pilot_contrast.py"),
    "resplit": ("-B", "development/replay_pilot_resplit.py"),
    "ablation": ("-B", "-S", "development/replay_resplit_ablation.py", "--verify-manuscript-table"),
    "library": ("-B", "development/verify_weighted_panel.py"),
    "manuscript": ("-B", "-S", "development/verify_manuscript_pilot.py"),
}


def _resolve_caller_path(path: Path) -> Path:
    return path if path.is_absolute() else (CALLER_CWD / path).resolve()


def _run_py(
    args: tuple[str, ...], *, verbose: bool = False, cwd: Path = ROOT, allowed_returncode: int = 0
) -> int:
    cmd = [sys.executable, *args]
    env = {**os.environ, "PYTHONUTF8": "1"}
    if verbose:
        print(f"+ {' '.join(args)}", flush=True)
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=not verbose, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        if proc.returncode != allowed_returncode:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
    return proc.returncode


def _run_verify_check(args: tuple[str, ...], *, verbose: bool) -> str | None:
    script_index = next(i for i, arg in enumerate(args) if not arg.startswith("-"))
    script = args[script_index]
    tests = Path(script).name.startswith("test_")
    reexec = (tests and script != "development/test_prospective_multiagent_study.py") or script in {
        "development/audit_pilot_baseline_domain.py", "development/build_candidate.py", "development/probe_gate1.py",
    }
    print(f"{'Re-executed' if reexec else 'Replay-only'}: {script}", flush=True)
    if tests:
        args = (*args[:script_index], "development/verify_unittest.py", *args[script_index:])
        if _run_py(args, verbose=verbose, allowed_returncode=SKIPPED_TEST_STATUS) == SKIPPED_TEST_STATUS:
            return script
    else:
        _run_py(args, verbose=verbose)
    return None


def _check_candidate_build(*, prospective: bool, verbose: bool = False) -> Path | None:
    with TemporaryDirectory(prefix="eapg_cand_") as td:
        out = Path(td) / ("prospective.py" if prospective else "candidate_pipeline.py")
        flags = ("--prospective", str(out)) if prospective else (str(out),)
        _run_verify_check(("-B", "development/build_candidate.py", *flags), verbose=verbose)
        expected = CANDIDATE_PROSPECTIVE_SHA256 if prospective else CANDIDATE_ARCHIVE_SHA256
        actual = sha256(out.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Built candidate hash mismatch: expected {expected}, got {actual}")
    return None


def _run_linux_checks(*, with_probes: bool, verbose: bool) -> list[str]:
    with TemporaryDirectory(prefix="eapg_linux_") as td:
        prosp = Path(td) / "prospective.py"
        _run_verify_check(("-B", "development/build_candidate.py", "--prospective", str(prosp)), verbose=verbose)
        if sha256(prosp.read_bytes()).hexdigest() != CANDIDATE_PROSPECTIVE_SHA256:
            raise RuntimeError("Prospective candidate SHA-256 mismatch")
        linux_cmds: list[tuple[str, ...]] = [
            ("-B", "artifacts/phase2_data/test_phase2_ast.py", "--pipeline", str(prosp)),
            ("-B", "artifacts/phase2_data/test_phase2_selection.py", "--pipeline", str(prosp)),
            ("-B", "development/test_backward_slice.py", "--pipeline", str(prosp)),
            ("-B", "development/test_synthetic_intervention.py", "--pipeline", str(prosp)),
            ("-B", "development/test_synthetic_arms.py"),
            ("-B", "development/audit_pilot_baseline_domain.py"),
            ("-B", "development/test_synthetic_study_custodian.py"),
            ("-B", "development/test_synthetic_source_fingerprints.py"),
            ("-B", "development/test_audit_synthetic_frame_domain.py"),
            ("-B", "development/test_audit_scalar_intake.py"),
        ]
        if with_probes:
            linux_cmds.append(("-B", "development/probe_gate1.py", "--probes-only"))
        return [script for cmd in linux_cmds if (script := _run_verify_check(cmd, verbose=verbose))]


def cmd_verify(args: argparse.Namespace, *, summarize_success: bool = True) -> int:
    mode = args.mode
    if mode == "auto":
        mode = "linux" if sys.platform.startswith("linux") else "common"
    if mode == "reexec":
        _run_py(("-B", "development/reexec_pilot.py"), verbose=args.verbose)
        print("Verified EAPG artifact checks cleanly (reexec: pilot Table I re-executed through frozen pipeline.py).")
        return 0

    commands = FAST_VERIFY_COMMANDS if mode == "fast" else COMMON_VERIFY_COMMANDS
    skipped = [script for cmd in commands if (script := _run_verify_check(cmd, verbose=args.verbose))]
    _check_candidate_build(prospective=False, verbose=args.verbose)

    ran = f"{len(commands)} + candidate_build"
    if mode == "linux":
        skipped.extend(_run_linux_checks(with_probes=args.with_probes, verbose=args.verbose))
        ran += f" + {10 + int(args.with_probes)} linux"
    elif mode == "wsl2":
        if sys.platform != "win32" or not ROOT.drive:
            raise RuntimeError("--mode wsl2 is supported only from Windows hosts with a WSL distro")
        wsl_root = f"/mnt/{ROOT.drive.rstrip(':').lower()}/" + "/".join(ROOT.parts[1:])
        script = "\n".join([
            "set -e",
            'export PYTHONPATH="$HOME/.local/share/eapg-phase2/deps"',
            f'cd "{wsl_root}"',
            "python3 -B -c 'import eapg; raise SystemExit(eapg.cmd_verify("
            "eapg.build_parser().parse_args(), summarize_success=False))' verify --mode linux"
            + (" --with-probes" if args.with_probes else "") + (" --verbose" if args.verbose else ""),
            "",
        ])
        cmd = ["wsl", "-d", args.wsl_distro, "--", "bash", "-s"]
        status = subprocess.run(cmd, input=script.encode("utf-8")).returncode
        if status not in (0, VERIFY_SKIPPED_STATUS):
            raise subprocess.CalledProcessError(status, cmd)
        if status == VERIFY_SKIPPED_STATUS:
            skipped.append("the WSL Linux suite (see above)")
        ran += " + wsl2_linux"
    else:
        print(f"Not selected in {mode} mode: Linux/WSL2 checks, including paired intervention sandbox tests.")

    if skipped:
        print(f"SKIPPED: tests in {', '.join(skipped)} ({mode}; all non-skipped checks passed).")
        return 0 if args.allow_skips else VERIFY_SKIPPED_STATUS
    if summarize_success:
        print(f"Verified selected EAPG artifact checks ({mode}: {ran}).")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    targets = list(REPLAY_TARGETS) if args.stage == "all" else [args.stage]
    for name in targets:
        print(f"=== replay: {name} ===")
        _run_py(REPLAY_TARGETS[name], verbose=True)
    return 0


def cmd_build_candidate(args: argparse.Namespace) -> int:
    cmd = ["-B", "development/build_candidate.py"]
    if args.prospective:
        cmd.append("--prospective")
    cmd.append(str(_resolve_caller_path(args.output)))
    _run_py(tuple(cmd), verbose=True)
    return 0


def cmd_study(args: argparse.Namespace) -> int:
    cmd = ["-B", "development/run_prospective_multiagent_study.py"]
    if args.reuse_ledgers:
        cmd.append("--reuse-saved-part-a-ledgers")
    if args.wsl2_part_a_only:
        cmd.append("--wsl2-part-a-only")
    for flag, val in (
        ("--pipeline", args.pipeline),
        ("--attestations-dir", args.attestations_dir),
        ("--workdir", args.workdir),
        ("--wsl2-ledgers-dir", args.wsl2_ledgers_dir),
        ("--output", args.output),
    ):
        if val is not None:
            cmd.extend((flag, str(_resolve_caller_path(val))))
    _run_py(tuple(cmd), verbose=True)
    return 0


def cmd_build_paper(args: argparse.Namespace) -> int:
    manuscript_dir = ROOT / "manuscript"
    for cmd in (
        ("pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "paper.tex"),
        ("bibtex", "paper"),
        ("pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "paper.tex"),
        ("pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "paper.tex"),
    ):
        proc = subprocess.run(cmd, cwd=manuscript_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            raise subprocess.CalledProcessError(proc.returncode, cmd)
    log_text = (manuscript_dir / "paper.log").read_text(encoding="utf-8", errors="replace")
    overfull = [ln for ln in log_text.splitlines() if "Overfull \\hbox" in ln]
    undef = [ln for ln in log_text.splitlines() if "undefined" in ln.lower() and "warning" in ln.lower()]
    if args.clean:
        for ext in (".aux", ".bbl", ".blg", ".log", ".out"):
            (manuscript_dir / f"paper{ext}").unlink(missing_ok=True)
    print(f"Built {manuscript_dir / 'paper.pdf'} ({len(overfull)} overfull hboxes, {len(undef)} undefined warnings).")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    manifest = [line.split("  ", 1) for line in (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line]
    pinned_ok = sum(sha256((ROOT / rel).read_bytes()).hexdigest() == digest for digest, rel in manifest)
    status = {
        "repo_root": str(ROOT),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "sha256sums_verified": f"{pinned_ok}/{len(manifest)}",
        "manuscript_pdf_bytes": (ROOT / "manuscript/paper.pdf").stat().st_size if (ROOT / "manuscript/paper.pdf").exists() else None,
        "multiagent_results_sha256": sha256(RESULTS_MULTIAGENT.read_bytes()).hexdigest() if RESULTS_MULTIAGENT.exists() else None,
        "tools": {tool: shutil.which(tool) for tool in ("g++", "git", "bwrap", "systemd-run", "systemctl", "prlimit", "wsl", "pdflatex", "bibtex")},
    }
    print(json.dumps(status, indent=2))
    return 0 if pinned_ok == len(manifest) else 1


def build_parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="eapg", description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)

    p_ver = sub.add_parser("verify", help="Run archived release checks, table verifiers, and unit tests.")
    p_ver.add_argument("--mode", choices=("auto", "fast", "common", "linux", "wsl2", "reexec"), default="auto",
                       help="reexec: recompile and re-profile pilot Table I from its embedded sources (requires g++).")
    p_ver.add_argument("--with-probes", action="store_true", help="Include Bubblewrap Gate 1 isolation probes on Linux/WSL2.")
    p_ver.add_argument("--allow-skips", action="store_true", help="Allow a zero exit status when tests are skipped.")
    p_ver.add_argument("--wsl-distro", default="Ubuntu", help="WSL distro name for --mode wsl2.")
    p_ver.add_argument("-v", "--verbose", action="store_true")
    p_ver.set_defaults(func=cmd_verify)

    p_rep = sub.add_parser("replay", help="Replay empirical evidence strata and manuscript table checks.")
    p_rep.add_argument("--stage", choices=(*REPLAY_TARGETS, "all"), default="all")
    p_rep.set_defaults(func=cmd_replay)

    p_cand = sub.add_parser("build-candidate", help="Materialize patched Phase 2 / prospective pipeline.")
    p_cand.add_argument("output", type=Path)
    p_cand.add_argument("--prospective", action="store_true")
    p_cand.set_defaults(func=cmd_build_candidate)

    p_st = sub.add_parser("study", help="Run or reassemble the multi-agent Part A/B study.")
    p_st.add_argument("--reuse-ledgers", action="store_true")
    p_st.add_argument("--wsl2-part-a-only", action="store_true")
    p_st.add_argument("--pipeline", type=Path, default=None)
    p_st.add_argument("--attestations-dir", type=Path, default=None)
    p_st.add_argument("--workdir", type=Path, default=None)
    p_st.add_argument("--wsl2-ledgers-dir", type=Path, default=None)
    p_st.add_argument("--output", type=Path, default=None)
    p_st.set_defaults(func=cmd_study)

    p_pdf = sub.add_parser("build-paper", help="Compile manuscript/paper.pdf with pdflatex + bibtex.")
    p_pdf.add_argument("--clean", action="store_true", help="Remove intermediate LaTeX build files after compiling.")
    p_pdf.set_defaults(func=cmd_build_paper)

    p_stat = sub.add_parser("status", help="Inspect SHA256SUMS integrity, artifacts, and installed toolchain.")
    p_stat.set_defaults(func=cmd_status)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
