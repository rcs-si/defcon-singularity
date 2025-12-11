from pathlib import Path
import re
from typing import List, Set

IGNORE_PREFIXES = (
    "/proc",
    "/dev",
    "/sys",
    "/tmp",
    "/run",
)

# what should these be?
INTERESTING_PREFIXES = (
    "/share/pkg.8",
    "/project",
    "/usr/local",
    # add /projectnb, /usr2/youruser if we want it
)

PATH_RE = re.compile(r'"([^"]+)"')

# Match /share/pkg.8/PACKAGE/VERSION/install[/anything...]
INSTALL_ROOT_RE = re.compile(r"^(/share/pkg\.8/[^/]+/[^/]+/install)(?:/.*)?$")

def looks_interesting(path: str) -> bool:
    for p in IGNORE_PREFIXES:
        if path.startswith(p):
            return False
    return any(path.startswith(p) for p in INTERESTING_PREFIXES) or path.startswith("/project")


def parse_strace_file(strace_path: Path) -> List[str]:
    raw_paths: Set[str] = set()

    with strace_path.open(errors="ignore") as f:
        for line in f:
            # Skip failed syscalls (ENOENT, EACCES, etc.)
            if " = -1 " in line:
                continue

            m = PATH_RE.search(line)
            if not m:
                continue

            path = m.group(1)
            if not path.startswith("/"):
                continue

            if looks_interesting(path):
                raw_paths.add(path)

    module_install_roots: Set[str] = set()
    other_paths: Set[str] = set()

    for p in raw_paths:
        m = INSTALL_ROOT_RE.match(p)
        if m:
            # Collapse ANY file under .../install/... to just .../install
            module_install_roots.add(m.group(1))
        else:
            # Keep non /share/pkg.8 stuff (e.g., /projectnb, /usr/local)
            if not p.startswith("/share/pkg.8"):
                other_paths.add(p)

    # Final list = all distinct module install roots + other non-module paths
    final_paths = sorted(module_install_roots | other_paths)
    return final_paths


if __name__ == "__main__":
    import sys
    try:
        for p in parse_strace_file(Path(sys.argv[1])):
            print(p)
    except BrokenPipeError:
        pass
