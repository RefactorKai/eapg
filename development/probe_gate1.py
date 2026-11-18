"""Exercise the Gate 1 launcher using only locally authored fixtures."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
from tempfile import TemporaryDirectory
from threading import Barrier
from uuid import uuid4

from gate1_sandbox import FILE_CAP, SCRATCH_CAP, checked_output, compile_cpp, execute, invoke, preprocess


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def python(code, *args, **options):
    return invoke(["python3", "-I", "-c", code, *args], **options)


def probe_boundaries():
    signals = []
    previous = signal.signal(signal.SIGUSR1, lambda *_: signals.append(True))
    try:
        with TemporaryDirectory() as directory:
            secret = Path(directory) / "host-only.h"
            secret.write_text("#define GATE1_HOST_VISIBLE 1\n")
            try:
                preprocess(f'#include "{secret}"\n'.encode())
            except RuntimeError as exc:
                require("No such file or directory" in str(exc), "Preprocessor did not deny the host include")
            else:
                raise RuntimeError("Preprocessor reached the host include")
            result = python(r'''
from pathlib import Path
import os, signal, socket, sys
supervisor, secret = sys.argv[1:]
assert not any(Path(p).exists() for p in (secret, '/home', '/mnt/c', '/mnt/d', '/init', '/run/user'))
assert not Path(f'/proc/{supervisor}').exists()
try:
    os.kill(int(supervisor), signal.SIGUSR1)
except ProcessLookupError:
    pass
else:
    raise RuntimeError('Candidate could signal the host supervisor')
assert {name for _, name in socket.if_nameindex()} == {'lo'}
with socket.socket() as client:
    client.settimeout(1)
    assert client.connect_ex(('198.51.100.1', 443)) != 0
for mount in ('/', '/usr/lib', '/usr/bin', '/usr/include', '/proc', '/dev'):
    assert os.statvfs(mount).f_flag & os.ST_RDONLY, mount
assert not Path('/usr/lib/wsl/drivers').exists()
assert not Path('/dev/shm').exists() or os.statvfs('/dev/shm').f_flag & os.ST_RDONLY
''', str(os.getpid()), str(secret))
            checked_output(result)
    finally:
        signal.signal(signal.SIGUSR1, previous)
    require(not signals, "Supervisor received a candidate signal")

    source = b'#include <cstdio>\n#define N 2\nint main() { int x; if (std::scanf("%d", &x) != 1) return 1; std::printf("%d\\n", N * x); }\n'
    require(b"2 * x" in preprocess(source), "Authored preprocessing fixture did not expand N")
    binary = compile_cpp(source)
    require(checked_output(execute(binary, b"21\n")) == b"42\n", "Authored binary did not match its oracle")


def probe_private_scratch():
    barrier = Barrier(2)
    markers = [uuid4().hex for _ in range(2)]

    def contender(mark, peer):
        barrier.wait(timeout=5)
        result = python(r'''
from pathlib import Path
import os, sys, time
mark, peer = sys.argv[1:]
p = Path('/tmp/marker')
assert not p.exists()
p.write_text(mark)
start = time.monotonic_ns()
for _ in range(40):
    assert p.read_text() == mark
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal() or proc.name in {'1', str(os.getpid())}:
            continue
        try:
            assert peer.encode() not in (proc / 'cmdline').read_bytes()
        except FileNotFoundError:
            pass
    time.sleep(0.05)
print(os.readlink('/proc/self/ns/pid'), start, time.monotonic_ns())
''', mark, peer)
        namespace, start, end = checked_output(result).split()
        return result.cgroup, namespace, int(start), int(end)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(contender, *markers)
        second = pool.submit(contender, *reversed(markers))
        group_a, ns_a, start_a, end_a = first.result()
        group_b, ns_b, start_b, end_b = second.result()
    require(group_a != group_b and ns_a != ns_b and max(start_a, start_b) < min(end_a, end_b),
            "Concurrent probes did not overlap in distinct scopes and PID namespaces")

    result = python(r'''
import errno, os
assert not os.path.exists('/tmp/marker')
stat = os.statvfs('/tmp')
assert stat.f_frsize * stat.f_blocks == 64 * 1024**2
data = bytes(2 * 1024**2)
used = 0
try:
    for n in range(40):
        with open(str(n), 'wb', buffering=0) as stream:
            used += stream.write(data)
except OSError as exc:
    assert exc.errno == errno.ENOSPC, exc
else:
    raise RuntimeError('Aggregate scratch quota was not enforced')
print(used)
''')
    require(int(checked_output(result)) == SCRATCH_CAP, "Scratch did not stop at the aggregate quota")


def probe_resource_limits():
    for fd in (1, 2):
        result = python("import os,sys\nfor _ in range(256): os.write(int(sys.argv[1]), b'x'*65536)", str(fd))
        require(result.returncode != 0 and len(result.stdout if fd == 1 else result.stderr) == FILE_CAP,
                f"Output descriptor {fd} did not stop at the file limit")
    result = python("import mmap; mmap.mmap(-1, 600*1024**2)")
    require(result.returncode != 0 and b"Cannot allocate memory" in result.stderr, "Address-space limit failed")

    processes = python(r'''
import errno, os, time
children = []
try:
    for _ in range(30):
        child = os.fork()
        if child == 0:
            time.sleep(30)
            os._exit(0)
        children.append(child)
except OSError as exc:
    assert exc.errno == errno.EAGAIN
else:
    raise RuntimeError('Cgroup did not enforce its task limit')
finally:
    for child in children:
        os.kill(child, 9)
        os.waitpid(child, 0)
print(len(children))
''')
    require(0 < int(checked_output(processes)) < 24 and int(processes.events["pids.events.max"]) > 0,
            "Kernel did not report aggregate process quota pressure")

    memory = python(r'''
import mmap, os, time
for _ in range(2):
    if os.fork() == 0:
        size = 420 * 1024**2
        with mmap.mmap(-1, size) as area:
            for offset in range(0, size, 4096):
                area[offset] = 1
            time.sleep(2)
        os._exit(0)
statuses = [os.wait()[1] for _ in range(2)]
assert any(os.WIFSIGNALED(s) and os.WTERMSIG(s) == 9 for s in statuses), statuses
''')
    checked_output(memory)
    require(int(memory.events["memory.events.oom_kill"]) > 0, "Kernel did not report aggregate memory quota pressure")

    cpu = python(r'''
import os, time
end = time.monotonic() + 2
if os.fork() == 0:
    while time.monotonic() < end:
        pass
    os._exit(0)
while time.monotonic() < end:
    pass
os.wait()
''')
    checked_output(cpu)
    require(int(cpu.events["cpu.stat.nr_throttled"]) > 0, "Kernel did not report aggregate CPU throttling")


def probe_cleanup():
    for fail in (True, False):
        result = python(r'''
import os, signal, sys, time
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print(os.readlink('/proc/self/ns/pid'), flush=True)
        time.sleep(60)
    os._exit(0)
os.wait()
time.sleep(0.2)
if sys.argv[1] == 'True':
    os._exit(7)
time.sleep(60)
''', str(fail), timeout=2)
        require(result.stdout.startswith(b"pid:["), "Descendant did not escape the original session")
        require(result.timed_out is not fail and (not fail or result.returncode == 7),
                "Cleanup fixture did not exercise its intended exit path")
        scope_events = Path(result.cgroup) / "cgroup.events"
        try:
            require("populated 0" in scope_events.read_text().splitlines(), "Descendant cgroup survived cleanup")
        except FileNotFoundError:
            pass
        namespace = result.stdout.decode().strip()
        for proc in Path("/proc").iterdir():
            if not proc.name.isdecimal():
                continue
            try:
                require(os.readlink(proc / "ns/pid") != namespace, "Descendant namespace survived cleanup")
            except (FileNotFoundError, PermissionError):
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes-only", action="store_true", required=True)
    parser.parse_args()
    require(__debug__, "Run without Python optimization")
    for probe in (probe_boundaries, probe_private_scratch, probe_resource_limits, probe_cleanup):
        probe()
        print(json.dumps({"probe": probe.__name__, "status": "passed"}), flush=True)


if __name__ == "__main__":
    main()
