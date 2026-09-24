"""Environment module detection and runtime search paths."""

from pathlib import Path
import re

from path_utils import _clean_path

_MODULE_INSTALL_ROOT_RE = re.compile(r"^/share/pkg\.[^/]+/[^/]+/[^/]+/install$")


def _is_module_install_root(path: str) -> bool:
    return bool(_MODULE_INSTALL_ROOT_RE.match(_clean_path(path)))


def runtime_paths(module_roots, conda_roots, blocked_libs):
    """Return binary and library directories in their container search order."""
    bins = [str(Path(root) / "bin") for root in module_roots]
    libs = [str(Path(root) / name) for root in module_roots
            if root not in conda_roots for name in ("lib64", "lib")]
    blocked_dirs = sorted({str(Path(lib).parent) for lib in blocked_libs})
    return bins, libs, libs + [d for d in blocked_dirs if d not in libs]
