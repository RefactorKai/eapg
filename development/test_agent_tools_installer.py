import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Agent tools installer requires a POSIX shell and filesystem")


INSTALLER = Path(__file__).parent / "tools" / "install_agent_tools.sh"


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


@pytest.fixture
def install_env(tmp_path):
    root = tmp_path / "repo"
    target = root / "development/tools/install_agent_tools.sh"
    target.parent.mkdir(parents=True)
    shutil.copyfile(INSTALLER, target)
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    executable(python, "exit 0\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    executable(bin_dir / "curl", """while [ "$#" -gt 0 ]; do
    if [ "$1" = "-o" ]; then shift; output=$1; fi
    shift
done
printf '%s\\n' 'test "$RTK_VERSION" = v1.2.1 || exit 8' 'test "$RTK_EDITION" = oss || exit 9' 'mkdir -p "$RTK_INSTALL_DIR"' 'printf "#!/bin/sh\\necho rtk 1.2.1\\n" > "$RTK_INSTALL_DIR/rtk"' 'chmod +x "$RTK_INSTALL_DIR/rtk"' > "$output"
""")
    executable(bin_dir / "sha256sum", 'cat >/dev/null\nexit "${CHECKSUM_STATUS:-0}"\n')
    executable(bin_dir / "uv", """test "${UV_STATUS:-0}" = 0 || exit "$UV_STATUS"
test "$1 $2 $3" = "pip install --python" || exit 7
test "$5" = "ast-grep-cli==0.51.3" || exit 6
printf '#!/bin/sh\\necho ast-grep 0.51.3\\n' > "$(dirname "$4")/ast-grep"
chmod +x "$(dirname "$4")/ast-grep"
""")
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    return target, env, home, python


def run_install(install_env, **extra):
    target, env, _, _ = install_env
    return subprocess.run(["bash", str(target)], env={**env, **extra}, capture_output=True, text=True)


def test_agent_tools_install_empty_and_repeat(install_env):
    for _ in range(2):
        result = run_install(install_env)
        assert result.returncode == 0, result.stderr
        assert "rtk 1.2.1" in result.stdout
        assert "ast-grep 0.51.3" in result.stdout
    assert (install_env[2] / ".local/bin/rtk").is_file()


def test_agent_tools_checksum_failure_stops_install(install_env):
    result = run_install(install_env, CHECKSUM_STATUS="1")
    assert result.returncode != 0
    assert not (install_env[2] / ".local/bin/rtk").exists()


def test_agent_tools_requires_repo_venv(install_env):
    install_env[3].unlink()
    result = run_install(install_env)
    assert result.returncode != 0
    assert "Activate/setup the repo .venv first." in result.stderr


def test_agent_tools_propagates_package_failure(install_env):
    result = run_install(install_env, UV_STATUS="12")
    assert result.returncode == 12
    assert "Ready:" not in result.stdout
