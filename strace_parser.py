from pathlib import Path
import re
from typing import List, Set

# Paths that are never interesting (noise)
IGNORE_PREFIXES = (
    "/proc",
    "/dev",
    "/sys",
    "/tmp",
    "/run",
)

# Paths we want to capture for non-module files (only on success)
INTERESTING_PREFIXES = (
    "/project",
    "/projectnb",
    "/usr/local",
)

PATH_RE = re.compile(r'"(/[^"]+)"')

# Collapse /share/pkg.X/PACKAGE/VERSION/install[/...] → install root
MODULE_INSTALL_RE = re.compile(
    r'^(/share/pkg\.[^/]+/[^/]+/[^/]+/install)(?:/.*)?$'
)

# Error patterns — used only when filtering non-module paths
ERROR_PATTERNS = (
    " = -1 ",
    "ENOENT",
    "EACCES",
    "ENOTDIR",
    "EISDIR",
)


def parse_strace_file(strace_path: Path) -> List[str]:
    """
    Parse strace output and return a sorted list of paths to include in the
    Singularity %files section.

    Strategy:
    - /share/pkg.*  modules: extract install root from EVERY line, including
      failed probes (ENOENT etc.).  The kernel probes many hwcap variants before
      finding the right lib; those probe failures still prove the module is used.
    - All other interesting paths: only keep successfully accessed paths
      (skip lines containing error codes).
    """
    module_roots: Set[str] = set()
    other_paths: Set[str] = set()

    with strace_path.open(errors="ignore") as f:
        for line in f:
            paths_in_line = PATH_RE.findall(line)
            is_error_line = any(err in line for err in ERROR_PATTERNS)

            for path in paths_in_line:
                # --- /share/pkg module paths ---
                m = MODULE_INSTALL_RE.match(path)
                if m:
                    # Always capture, even from failed probes
                    module_roots.add(m.group(1))
                    continue

                # Skip /share/pkg sub-paths that didn't match the install regex
                # (e.g. bare "/share/pkg.8" directory entries — not useful)
                if path.startswith("/share/pkg"):
                    continue

                # --- Other interesting paths (only on success) ---
                if is_error_line:
                    continue

                if any(path.startswith(p) for p in IGNORE_PREFIXES):
                    continue

                if any(path.startswith(p) for p in INTERESTING_PREFIXES):
                    other_paths.add(path)

    return sorted(module_roots | other_paths)


def summarize_modules(strace_path: Path) -> List[str]:
    """Return human-readable module names detected (e.g. 'python3/3.12.4')."""
    names: Set[str] = set()
    with strace_path.open(errors="ignore") as f:
        for line in f:
            for path in PATH_RE.findall(line):
                m = MODULE_INSTALL_RE.match(path)
                if m:
                    # /share/pkg.8/python3/3.12.4/install → python3/3.12.4
                    parts = Path(m.group(1)).parts
                    # parts: ('/', 'share', 'pkg.8', 'python3', '3.12.4', 'install')
                    if len(parts) >= 6:
                        names.add(f"{parts[3]}/{parts[4]}")
    return sorted(names)


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1])
    print("=== Module install roots ===")
    for p in parse_strace_file(path):
        print(p)
    print("\n=== Detected modules ===")
    for name in summarize_modules(path):
        print(f"  module load {name}")