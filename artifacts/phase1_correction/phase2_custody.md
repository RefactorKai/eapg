# Phase 2 custody runner and local verification

From the repository root, run the custody fixtures with Python and the installed tree-sitter packages. The full suite additionally requires Windows and MSYS2 GCC with signed-overflow trap support. It compiles and runs only built-in fixtures.

```powershell
python -X utf8 artifacts/phase1_correction/phase2_custody_and_probes.py --static-only
python -X utf8 artifacts/phase1_correction/phase2_custody_and_probes.py
```

The reference-map test uses the frozen Pass 0–2 code, verifies that span tracing leaves its node list unchanged, and tests nested synthetic braces. Pre-brace and normalized spans are half-open UTF-8 byte offsets. The GCC marker pass must align with the authoritative expansion before raw line numbers are exported. Macro names on mapped raw lines indicate invocation evidence. Line markers alone do not establish complete nested or token-level expansion provenance.

The Windows probes put a gated worker and its children in a Job Object, drain both output streams with a shared bound, and confirm zero live job processes after termination. The clean control's supervisor record is written outside the fixture process. The forgery probe checks that stdout and stderr markers cannot substitute for that record. These tests cover the four requested failure cases and the clean control. The local Job Object harness does not implement the external guest's network, filesystem, or identity isolation, nor an authenticated profiling-counter channel. The external runner must validate those separately before preprocessing or executing human submissions.

## Linux execution gate

Ubuntu WSL2 initially returned `HCS_E_SERVICE_NOT_AVAILABLE`. An elevated check found Virtual Machine Platform disabled. Enabling the feature and restarting Windows restored Ubuntu startup. The [development run](../phase2_data/README.md#first-validation-workload) records the verified Bubblewrap, cgroup, and counter fixtures and the first PIE development result.

From an administrator PowerShell session, inspect `VirtualMachinePlatform` with `Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform` and inspect the boot setting with `bcdedit /enum`. If the feature is disabled, enable it before retrying WSL2. If the boot configuration explicitly sets `hypervisorlaunchtype Off`, follow Microsoft's boot configuration and restart steps. If both settings are already correct, check firmware virtualization and, for a virtualized host, whether its hypervisor exposes the required extensions. The confirmation is a successful `wsl.exe --distribution Ubuntu --exec /bin/true`. [Microsoft WSL troubleshooting](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting#installation-issues)

Once a disposable Linux guest is runnable, use Bubblewrap as the candidate namespace layer and `prlimit` as a second layer of per-process limits. Validate the exact launcher inside the chosen guest before pinning it. Use explicit filesystem and network isolation, a read-only toolchain and staged inputs, bounded private scratch, and guest-wide or cgroup limits for aggregate memory and process counts. A writable bind and per-file size limits alone leave aggregate scratch use unbounded. Use an outer wall-clock timeout and confirm cleanup after parent and child failures. Probe inaccessible Windows mount paths and credentials, denied network access, scratch and resource ceilings, and the same isolation for the two GCC preprocessing passes as for execution. Keep external preprocessing and execution gated until these checks pass. [Bubblewrap security model](https://github.com/containers/bubblewrap#security) · [Linux resource limits](https://man7.org/linux/man-pages/man2/getrlimit.2.html) · [Linux cgroup limits](https://docs.kernel.org/admin-guide/cgroup-v2.html)

### Counter transport acceptance

Register the normal-exit callback after the instrumented main starts. Bind emission to the original process ID and a once-only guard. The callback emits the full node-counter table and returns. The tick-cap path emits the capped record and uses `std::_Exit(97)` so the normal callback is bypassed. The supervisor pairs a validated normal record with exit 0 and a validated capped record with exit 97. Missing, duplicate, oversized, truncated, or status-mismatched records fail validation. The emitter must handle interrupted or short writes. A high-numbered descriptor may reduce accidental collisions, but it remains accessible to code in the process. [Normal-exit callbacks](https://man7.org/linux/man-pages/man3/atexit.3.html) · [Write semantics](https://man7.org/linux/man-pages/man2/write.2.html)

The Linux development launcher passed fixtures for an early return, a helper calling `std::exit(0)`, a forked child exiting, a tick cap, a closed descriptor, a forged or duplicate record, and an abnormal exit. The development counter transport uses a separate inherited descriptor and verifies the record alongside the process exit status. Counter contents remain in-process telemetry. The Windows fixture results establish only the local Job Object behavior.

## Seal a pinned test frame

The CLI consumes a local JSON export of the official PIE test frame. Supply its verified SHA-256 from the pinned export record. Each pair must carry `split: "test"`, globally unique `pair_id`, `problem_id`, `slow_code`, `fast_code`, and `test_indices`. Optional fields are `slow_sub_id`, `fast_sub_id`, and an array of known problem `aliases`. The top-level object carries `release`, `usage_terms`, and `pairs`. It must cover all 41 official test problems. Keep the frame and the full private custody manifest under custodian control.

```powershell
python -X utf8 artifacts/phase1_correction/phase2_custody_and_probes.py --frame <pinned-frame.json> --frame-sha256 <verified-sha256> --manifest <new-manifest.json>
```

This mode reads source as data for static fingerprinting. It keeps the first pair by stable pair ID for each canonical slow-source key within a problem, then draws up to four distinct slow programs. The v2 manifest stores the slow-source key for each draw so negative-control nomination can exclude it. The runner writes a new manifest containing the seed, release and input hashes, drawn pair IDs, test indices, static groups, exclusions, and a digest of the canonical manifest JSON. It uses the original 100-pair pilot and checks the pilot file's SHA-256. Full source text stays in the input frame. Treat the digest as an integrity check and store it separately in the custody ledger. Final prompt-fingerprint quarantine remains pending until slow-side features are serialized.
