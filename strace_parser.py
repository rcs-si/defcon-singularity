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

# Modules skipped even if strace detects them — low-level runtime libraries
# (BLAS, compilers, MPI) that either already exist in the base image or contain
# cyclic symlinks that break rsync/cp during the Singularity build.
MODULE_BLOCKLIST = {
    "flexiblas",
    "gcc",
    "intel",
    "openmpi",
    "mvapich2",
    "cuda",
    "miniconda",
}

# Error patterns — used only when filtering non-module paths
ERROR_PATTERNS = (
    " = -1 ",
    "ENOENT",
    "EACCES",
    "ENOTDIR",
    "EISDIR",
)


def parse_blocked_module_libs(strace_path: Path) -> List[str]:
    """
    For blocklisted modules (gcc, intel, flexiblas etc.), return the individual
    .so files that were actually successfully opened — not the whole install tree.
    These are needed as runtime dependencies but their install dirs can't be
    safely rsync'd due to cyclic symlinks.
    """
    libs: Set[str] = set()
    with strace_path.open(errors="ignore") as f:
        for line in f:
            # Only successfully opened files
            if any(err in line for err in ERROR_PATTERNS):
                continue
            for path in PATH_RE.findall(line):
                m = MODULE_INSTALL_RE.match(path)
                if not m:
                    continue
                module_name = Path(m.group(1)).parts[3]
                if module_name not in MODULE_BLOCKLIST:
                    continue
                # Only capture actual .so files, not directories or other files
                if re.search(r'\.so(\.\d+)*$', path):
                    # Normalise double slashes introduced by strace
                    libs.add(re.sub(r'//+', '/', path))
    return sorted(libs)


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
                    # Extract module name (e.g. 'gcc' from /share/pkg.8/gcc/12.2.0/install)
                    module_name = Path(m.group(1)).parts[3]
                    if module_name not in MODULE_BLOCKLIST:
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

    # For project paths, drop bare directories when a more specific child path
    # exists — e.g. drop /projectnb/foo if /projectnb/foo/test.py is present.
    # This prevents accidentally copying the whole project directory into the
    # container just because Python stat()'d it while loading a script.
    pruned: Set[str] = set()
    sorted_others = sorted(other_paths)
    for path in sorted_others:
        # Keep this path only if no other path starts with it + "/"
        is_parent = any(
            other.startswith(path + "/")
            for other in sorted_others
            if other != path
        )
        if not is_parent:
            pruned.add(path)

    return sorted(module_roots | pruned)


def summarize_modules(strace_path: Path) -> List[str]:
    """Return human-readable module names detected (e.g. 'python3/3.12.4')."""
    names: Set[str] = set()
    with strace_path.open(errors="ignore") as f:
        for line in f:
            for path in PATH_RE.findall(line):
                m = MODULE_INSTALL_RE.match(path)
                if m:
                    parts = Path(m.group(1)).parts
                    if len(parts) >= 6 and parts[3] not in MODULE_BLOCKLIST:
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