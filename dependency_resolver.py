"""Resolve traced paths and user overrides into an explicit copy plan."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

from environments.gpu import application_libraries, inspect_trace, is_host_driver
from environments.modules import _is_module_install_root
from environments.mpi import inspect_mpi
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
    gpu_backends: List[str] = field(default_factory=list)
    gpu_roots: List[str] = field(default_factory=list)
    mpi_enabled: bool = False
    mpi_roots: List[str] = field(default_factory=list)


def resolve_dependencies(
    trace_path: Path,
    include_paths: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
    gpu: str = "auto",
    mpi: str = "auto",
    command_file=None,
    mpi_root: str | None = None,
) -> DependencyPlan:
    """Apply exclusions last and copy nested installation roots only once."""
    gpu_backends, gpu_roots = inspect_trace(trace_path, gpu)
    mpi_enabled, mpi_roots = inspect_mpi(trace_path, mpi, command_file)
    mpi_enabled = mpi_enabled or (bool(mpi_root) and mpi != 'none')
    if mpi_enabled and mpi_root:
        if not Path(mpi_root).is_absolute():
            raise ValueError('--mpi-root must be an absolute path')
        mpi_roots.append(mpi_root)
    mpi_roots = _apply_path_overrides(mpi_roots, [], exclude_paths)
    gpu_roots = _apply_path_overrides(gpu_roots, [], exclude_paths)
    conda_roots = _apply_path_overrides(parse_conda_roots(trace_path), [], exclude_paths)
    files = _apply_path_overrides(
        parse_strace_file(trace_path) + conda_roots + gpu_roots + mpi_roots, include_paths, exclude_paths,
    )
    gpu_libs = application_libraries(trace_path) if gpu_backends else []
    blocked_libs = _apply_path_overrides(
        parse_blocked_module_libs(trace_path) + gpu_libs, [], exclude_paths,
    )
    if gpu_backends:
        files = [p for p in files if not is_host_driver(p)]
        blocked_libs = [p for p in blocked_libs if not is_host_driver(p)]
    # A complete MPI tree includes transport plugins and helper binaries; the
    # individual library copies would duplicate files already in that tree.
    blocked_libs = [p for p in blocked_libs if not _path_is_under_any(p, mpi_roots)]
    module_roots = [f for f in files if _is_module_install_root(f)]
    copy_roots = sorted(set(module_roots + conda_roots + gpu_roots + mpi_roots))
    copy_roots = [root for root in copy_roots if not any(
        root != parent and _path_is_under(root, parent) for parent in copy_roots
    )]
    project_files = [f for f in files if not _path_is_under_any(f, copy_roots)]
    return DependencyPlan(
        summarize_modules(trace_path), module_roots, conda_roots, copy_roots,
        project_files, blocked_libs, list(exclude_paths), gpu_backends, gpu_roots,
        mpi_enabled, mpi_roots,
    )
