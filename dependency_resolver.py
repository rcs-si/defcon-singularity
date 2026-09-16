"""Resolve traced paths and user overrides into an explicit copy plan."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from environments.modules import _is_module_install_root
from path_utils import _apply_path_overrides, _path_is_under, _path_is_under_any
from strace_parser import (
    parse_strace_file, parse_conda_roots, parse_blocked_module_libs,
    summarize_modules,
)


@dataclass
class DependencyPlan:
    """Selected dependencies, independent of CLI arguments and output format."""

    modules: List[str]
    module_roots: List[str]
    conda_roots: List[str]
    copy_roots: List[str]
    project_files: List[str]
    blocked_libs: List[str]
    exclude_paths: List[str]


def resolve_dependencies(
    trace_path: Path,
    include_paths: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
) -> DependencyPlan:
    """Apply exclusions last and copy nested installation roots only once."""
    conda_roots = _apply_path_overrides(parse_conda_roots(trace_path), [], exclude_paths)
    files = _apply_path_overrides(
        parse_strace_file(trace_path) + conda_roots, include_paths, exclude_paths,
    )
    blocked_libs = _apply_path_overrides(
        parse_blocked_module_libs(trace_path), [], exclude_paths,
    )
    module_roots = [f for f in files if _is_module_install_root(f)]
    copy_roots = sorted(set(module_roots + conda_roots))
    copy_roots = [root for root in copy_roots if not any(
        root != parent and _path_is_under(root, parent) for parent in copy_roots
    )]
    project_files = [f for f in files if not _path_is_under_any(f, copy_roots)]
    return DependencyPlan(
        summarize_modules(trace_path), module_roots, conda_roots, copy_roots,
        project_files, blocked_libs, list(exclude_paths),
    )
