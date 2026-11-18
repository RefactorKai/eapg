"""Run one preprocessing, compilation, or execution stage in a Linux sandbox."""

from contextlib import ExitStack
from math import isqrt
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory, TemporaryFile
from types import SimpleNamespace
from uuid import uuid4


FILE_CAP = 8 * 1024**2
SCRATCH_CAP = 64 * 1024**2
COUNTER_CAP = 65_536
MAX_SCALE = isqrt((2**64 - 1) // 5)

# This scope supervisor runs outside the candidate's PID namespace. Its receipt
# and cgroup controls have no mount in the candidate's filesystem.
SCOPE = r'''
set -eu
receipt=$1
shift
scope=$(cut -d: -f3 /proc/self/cgroup)
dir=/sys/fs/cgroup$scope
printf '%s\n' "$dir" > "$receipt"
test "$(cat "$dir/memory.max")" = 805306368
test "$(cat "$dir/memory.swap.max")" = 0
test "$(cat "$dir/pids.max")" = 24
read -r quota period < "$dir/cpu.max"
test "$quota" = "$period"
rc=0
"$@" || rc=$?
for metric in memory.events pids.events cpu.stat; do
    while read -r key value; do
        printf '%s.%s %s\n' "$metric" "$key" "$value"
    done < "$dir/$metric"
done >> "$receipt"
exit "$rc"
'''


def invoke(command, *, data=b"", binary=None, timeout=12, counter_scale=None):
    if sys.platform != "linux" or os.getuid() == 0:
        raise RuntimeError("Gate 1 requires an unprivileged Linux user with systemd and Bubblewrap")
    systemd_run, systemctl, bwrap = (shutil.which(name) for name in ("systemd-run", "systemctl", "bwrap"))
    if not all((systemd_run, systemctl, bwrap)):
        raise RuntimeError("Gate 1 requires systemd-run, systemctl and Bubblewrap")
    if binary is not None and not 0 < len(binary) <= FILE_CAP:
        raise ValueError("Executable must fit the per-file limit")
    unit = f"eapg-gate1-{uuid4().hex}.scope"
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    with ExitStack() as resources, TemporaryDirectory(prefix="eapg-gate1-") as stage, TemporaryFile() as stdin, \
            TemporaryFile() as stdout, TemporaryFile() as stderr:
        receipt = Path(stage) / "scope"
        args = [
            systemd_run, "--user", "--scope", "--quiet", f"--unit={unit}",
            "--property=MemoryMax=768M", "--property=MemorySwapMax=0",
            "--property=TasksMax=24", "--property=CPUQuota=100%", "--property=KillMode=control-group",
            "--property=OOMPolicy=continue", "--property=TimeoutStopSec=2s",
            "/bin/sh", "-c", SCOPE, "eapg-scope", str(receipt),
            bwrap, "--unshare-all", "--unshare-user", "--disable-userns", "--assert-userns-disabled",
            "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
            "--setenv", "TMPDIR", "/tmp", "--setenv", "HOME", "/tmp",
            "--ro-bind", "/usr/bin", "/usr/bin", "--ro-bind", "/usr/include", "/usr/include",
            "--ro-bind", "/usr/lib", "/usr/lib", "--ro-bind", "/usr/lib64", "/usr/lib64",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc", "--remount-ro", "/proc", "--dev", "/dev", "--remount-ro", "/dev",
            "--size", str(SCRATCH_CAP), "--tmpfs", "/tmp", "--chdir", "/tmp",
        ]
        if Path("/usr/libexec/gcc").is_dir():
            args += ["--ro-bind", "/usr/libexec/gcc", "/usr/libexec/gcc"]
        for path in ("/usr/lib/wsl", "/usr/lib/modules"):
            if Path(path).is_dir():
                args += ["--tmpfs", path, "--remount-ro", path]
        if binary is not None:
            program = Path(stage) / "program"
            program.write_bytes(binary)
            program.chmod(0o500)
            args += ["--ro-bind", str(program), "/program"]
        counter = None
        if counter_scale is not None:
            if binary is None or type(counter_scale) is not int or not 0 < counter_scale <= MAX_SCALE:
                raise ValueError("Counter collection requires a binary and a positive scale with a 64-bit tick ceiling")
            counter_path = Path(stage) / "counter"
            counter = resources.enter_context(counter_path.open("x+b"))
            args += ["--bind", str(counter_path), "/eapg-counter", "--setenv", "EAPG_N", str(counter_scale),
                     "--setenv", "EAPG_COUNTER_FD", "3"]
            command = ["/bin/sh", "-c", 'exec 3>/eapg-counter; exec "$@"', "eapg-counter", *command]
        args += ["--remount-ro", "/", "--", "/usr/bin/prlimit", "--cpu=8:8", "--as=536870912:536870912",
                 f"--fsize={FILE_CAP}:{FILE_CAP}", "--core=0:0", "--", *command]
        stdin.write(data)
        stdin.seek(0)
        with subprocess.Popen(args, stdin=stdin, stdout=stdout, stderr=stderr, env=env,
                              start_new_session=True) as child:
            try:
                child.wait(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                child.kill()
                timed_out = True
            finally:
                control = [systemctl, "--user"]
                try:
                    subprocess.run([*control, "stop", unit], env=env, capture_output=True, timeout=10)
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)
                state = [*control, "show", "-P", "ActiveState", unit]
                active = subprocess.check_output(state, env=env, timeout=5).strip()
                if active == b"failed":
                    subprocess.run([*control, "reset-failed", unit], env=env, timeout=5, check=True)
                    active = subprocess.check_output(state, env=env, timeout=5).strip()
                if active != b"inactive":
                    raise RuntimeError(f"Sandbox scope did not stop: {unit} ({active!r})")
        stdout.seek(0)
        stderr.seek(0)
        out, err = stdout.read(FILE_CAP + 1), stderr.read(FILE_CAP + 1)
        if max(len(out), len(err)) > FILE_CAP:
            raise RuntimeError("Sandbox output exceeded the per-file limit")
        if not receipt.exists():
            raise RuntimeError(f"Sandbox scope did not start: {err[:2000]!r}")
        cgroup, *events = receipt.read_text().splitlines()
        remaining = Path(cgroup) / "cgroup.events"
        try:
            if "populated 0" not in remaining.read_text().splitlines():
                raise RuntimeError(f"Sandbox scope still has processes: {cgroup}")
        except FileNotFoundError:
            pass
        if not events and not timed_out:
            raise RuntimeError(f"Sandbox scope limit check failed: {err[:2000]!r}")
        wire = counter.read(COUNTER_CAP + 1) if counter is not None else b""
        return SimpleNamespace(returncode=child.returncode, stdout=out, stderr=err, timed_out=timed_out,
                               cgroup=cgroup, events=dict(line.split() for line in events), counter_wire=wire)


class SandboxStageFailure(RuntimeError):
    def __init__(self, result):
        super().__init__(f"Sandbox stage failed: exit={result.returncode}, timeout={result.timed_out}, "
                         f"stderr={result.stderr[:2000]!r}")
        self.result = result


def checked_output(result):
    if result.timed_out or result.returncode != 0:
        raise SandboxStageFailure(result)
    return result.stdout


def preprocess(source):
    return checked_output(invoke(["g++", "-E", "-x", "c++", "-"], data=source))


def compile_cpp(source, *flags):
    command = ["/bin/sh", "-c", 'g++ -std=c++17 -O2 "$@" -x c++ - -o /tmp/program && exec cat /tmp/program',
               "eapg-compile", *flags]
    return checked_output(invoke(command, data=source, timeout=25))


def execute(binary, data=b"", *, timeout=12, counter_scale=None):
    return invoke(["/program"], data=data, binary=binary, timeout=timeout, counter_scale=counter_scale)
