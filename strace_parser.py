from pathlib import Path
import re
from typing import List, Set

IGNORE_PREFIXES = (
    "/proc",
    "/dev",
    "/sys",
    "/tmp",
    "/run",
    "/user",  # Ignore user-specific temporary files
)

# Paths we want to capture for the container
INTERESTING_PREFIXES = (
    "/share/pkg",  # Wildcard match for /share/pkg.* (e.g., /share/pkg.8, /share/pkg.9)
    "/project",
    "/projectnb",  # Project NB systems
    "/usr/local",
    # add /usr2/youruser if we want it
)

PATH_RE = re.compile(r'"([^"]+)"')

# Match /share/pkg.*/PACKAGE/VERSION/install[/anything...] or /share/pkg.{wildcard}/...
INSTALL_ROOT_RE = re.compile(r"^(/share/pkg\.[^/]+/[^/]+/[^/]+/install)(?:/.*)?$")

# Common error codes to skip in strace output
ERROR_PATTERNS = (
    " = -1 ",  # General error
    "ENOENT",  # No such file or directory
    "EACCES",  # Permission denied
    "ENOTDIR",  # Not a directory
    "EISDIR",   # Is a directory
)

def looks_interesting(path: str) -> bool:
    for p in IGNORE_PREFIXES:
        if path.startswith(p):
            return False
    return any(path.startswith(p) for p in INTERESTING_PREFIXES) or path.startswith("/project")


def parse_strace_file(strace_path: Path) -> List[str]:
    raw_paths: Set[str] = set()

    with strace_path.open(errors="ignore") as f:
        for line in f:
            # Skip failed syscalls - check for any error pattern
            if any(error in line for error in ERROR_PATTERNS):
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
            # Keep non /share/pkg stuff (e.g., /projectnb, /usr/local)
            if not p.startswith("/share/pkg"):
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
