from pathlib import Path

from defcon_singularity.strace_parser import (
    parse_blocked_module_libs,
    parse_strace_file,
    summarize_modules,
)


def test_parse_strace_file_extracts_module_roots_and_interesting_paths(tmp_path: Path) -> None:
    trace = tmp_path / "trace.out"
    trace.write_text(
        'openat(AT_FDCWD, "/share/pkg.8/python3/3.12.0/install/bin/python3", O_RDONLY) = 3\n'
        'openat(AT_FDCWD, "/share/pkg.8/gcc/12.2.0/install/lib64/libstdc++.so.6", O_RDONLY) = 3\n'
        'openat(AT_FDCWD, "/projectnb/demo/work/run.py", O_RDONLY) = 3\n'
        'openat(AT_FDCWD, "/projectnb/demo/work", O_RDONLY) = 3\n'
        'openat(AT_FDCWD, "/projectnb/demo/missing.py", O_RDONLY) = -1 ENOENT (No such file)\n'
    )

    paths = parse_strace_file(trace)

    assert "/share/pkg.8/python3/3.12.0/install" in paths
    assert "/projectnb/demo/work/run.py" in paths
    assert "/share/pkg.8/gcc/12.2.0/install" not in paths
    assert "/projectnb/demo/work" not in paths


def test_parse_blocked_module_libs_and_module_summary(tmp_path: Path) -> None:
    trace = tmp_path / "trace.out"
    trace.write_text(
        'openat(AT_FDCWD, "/share/pkg.8/gcc/12.2.0/install/lib64/libstdc++.so.6", O_RDONLY) = 3\n'
        'openat(AT_FDCWD, "/share/pkg.8/python3/3.12.0/install/lib64/libpython3.12.so", O_RDONLY) = 3\n'
        'openat(AT_FDCWD, "/share/pkg.8/gcc/12.2.0/install/lib64/libstdc++.so.6", O_RDONLY) = -1 ENOENT (No such file)\n'
    )

    libs = parse_blocked_module_libs(trace)
    modules = summarize_modules(trace)

    assert libs == ["/share/pkg.8/gcc/12.2.0/install/lib64/libstdc++.so.6"]
    assert modules == ["python3/3.12.0"]
