# Pinned Gate 1 environment

On a disposable x86_64 Linux VM with Docker, cgroup v2 and non-root user
namespaces enabled, run from a committed checkout:

```sh
bash development/run_sandbox_container.sh python -B development/check_gate1_ci.py
bash development/run_sandbox_container.sh python -B eapg.py build-paper --clean
```

The image uses Ubuntu 26.04 by digest and the signed Ubuntu archive as of
2026-11-05 UTC for GCC 15.2, Bubblewrap 0.11.1, systemd 259, Python 3.14,
and TeX Live with `texlive-publishers`. Rebuild with a newer digest and
snapshot to take package security updates. `systemd` runs as PID 1; the
non-root user manager receives the CPU, cpuset, I/O, memory and PID controllers
and launches the unmodified Gate 1 sandbox. No `systemd-run` shim is used.

The launcher uses a privileged container for the outer systemd boot; this
container is **not** a host security boundary. Run only trusted checkouts on a
disposable VM. CI uses GitHub-hosted runners and does not start this job for
fork PRs. The container has networking disabled and no host mounts; only the
tracked tree at `HEAD` is copied in. Output files are discarded with the
container; copy out only intentional artifacts when adapting it for experiments.

For another trusted experiment, pass its command to the same launcher. CI
also uses it to re-execute pilot Table I with `eapg.py verify --mode reexec`.
