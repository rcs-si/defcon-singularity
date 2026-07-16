#!/usr/bin/env python3
"""
defcon — DEFinition CONtainer generator
========================================
Analyses a job's runtime dependencies via strace and produces a Singularity
.def file that can reproduce the environment inside a container.

Stages count DOWN to DEFCON 1 (package ready), like the real threat-level scale.

  Stage 1 (DEFCON 2):
    defcon stage1 -i input.qsub -o output.qsub -s base.sif [--scheduler sge|slurm]

    Reads your job script, wraps it with strace instrumentation, and writes a
    new job script that:
      1. Captures the runtime environment (env -0)
      2. Runs your original commands under strace
      3. Automatically calls "defcon stage2" to produce the .def

    Then submit the generated job script:
      qsub output.qsub
      sbatch output.qsub

  Stage 2 (DEFCON 1):
    defcon stage2 -t trace.out -e env.out -s base.sif -o container.def

    Parses the strace + env files and writes a Singularity definition.
    Called automatically from the instrumented job script.

  Build/run:
    singularity build --fakeroot container.sif container.def
    singularity run container.sif < job.qsub

    Or, with exec:
    singularity exec container.sif bash < job.qsub
"""

import argparse
import re
import shlex
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

from strace_parser import parse_strace_file, summarize_modules, parse_blocked_module_libs


BANNER = r"""
  ██████╗ ███████╗███████╗ ██████╗ ██████╗ ███╗   ██╗
  ██╔══██╗██╔════╝██╔════╝██╔════╝██╔═══██╗████╗  ██║
  ██║  ██║█████╗  █████╗  ██║     ██║   ██║██╔██╗ ██║
  ██║  ██║██╔══╝  ██╔══╝  ██║     ██║   ██║██║╚██╗██║
  ██████╔╝███████╗██║     ╚██████╗╚██████╔╝██║ ╚████║
  ╚═════╝ ╚══════╝╚═╝      ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝
"""

DEFCON_STATUS = {
    3: "⚠️ — Instrumented job ready. Submit it to proceed.",
    2: "🔶 — Job complete. Parsing dependencies…",
    1: "✅ — Container definition ready.",
}


DEF_TEMPLATE = """\
Bootstrap: localimage
From: {singularity_image}

%files
{files_section}

%setup
    # rsync -rL dereferences cyclic symlinks that break %%files cp -r
{rsync_section}

%post
    # This disables the module command, as all of the variables
    # set by Lmod are captured in the environment section. 
    # This way the original job script (with "module load" commands)
    # can run without modification.
    cat > /usr/local/bin/module << 'EOF'
#!/bin/sh
exit 0
EOF
    chmod +x /usr/local/bin/module
    
    
%environment
{env_section}

%runscript
    exec /bin/bash "$@"
"""

# Environment variables that don't get brought into the .def file
_ENV_BLOCKLIST = {
    "PWD", "OLDPWD", "SHLVL", "_", "LS_COLORS",
    "SSH_CLIENT", "SSH_CONNECTION", "SSH_TTY", "SSH_AUTH_SOCK",
    "TERM", "TERMINFO", "COLORTERM", "COLUMNS", "LINES",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_SESSION_ID",
    "HOSTNAME", "HISTCONTROL", "HISTSIZE", "HISTFILE",
    "LESSOPEN", "LESSCLOSE", "MAIL", "LOGNAME",
    "S_COLORS", "which_declare", "USER", "DISPLAY",
    "SINGULARITY_CACHEDIR", "SINGULARITY_BIND", "SINGULARITYENV_PREPEND_PATH",
}

_MODULE_INSTALL_ROOT_RE = re.compile(r"^/share/pkg\.[^/]+/[^/]+/[^/]+/install$")


def _is_blocked_env(key: str) -> bool:
    if key in _ENV_BLOCKLIST:
        return True
    if "%%" in key or key.startswith("BASH_FUNC_"):
        return True
    return False


def _clean_path(path: str) -> str:
    cleaned = path.strip()
    if len(cleaned) > 1:
        cleaned = cleaned.rstrip("/")
    return cleaned


def _parse_path_list(raw: str | None) -> List[str]:
    if not raw:
        return []

    seen = set()
    paths = []
    for piece in raw.split(","):
        path = _clean_path(piece)
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _path_is_under(path: str, root: str) -> bool:
    path = _clean_path(path)
    root = _clean_path(root)
    return path == root or path.startswith(root + "/")


def _path_is_under_any(path: str, roots: Iterable[str]) -> bool:
    return any(_path_is_under(path, root) for root in roots)


def _apply_path_overrides(
    detected_paths: Sequence[str],
    include_paths: Sequence[str],
    exclude_paths: Sequence[str],
) -> List[str]:
    """
    --inc force-adds paths.
    --exc removes detected or forced paths.
    If a path is both included and excluded, exclusion wins.
    """
    merged = {_clean_path(p) for p in detected_paths if _clean_path(p)}
    merged.update(_clean_path(p) for p in include_paths if _clean_path(p))

    if exclude_paths:
        merged = {p for p in merged if not _path_is_under_any(p, exclude_paths)}

    return sorted(merged)


def _is_module_install_root(path: str) -> bool:
    return bool(_MODULE_INSTALL_ROOT_RE.match(_clean_path(path)))


def _shell_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _shlex_join(parts: Sequence[str]) -> str:
    #return " ".join(shlex.quote(str(part)) for part in parts)
    # actually we don't want to shlex.quote() because we want the command
    # line in the shell to result ${TMPDIR}
    return " ".join(str(part) for part in parts)


def load_env_vars(path: Path) -> dict:
    env_vars = {}
    raw = path.read_bytes()
    for entry in raw.split(b"\x00"):
        if b"=" in entry:
            key, value = entry.split(b"=", 1)
            k = key.decode(errors="replace")
            v = value.decode(errors="replace")
            if not _is_blocked_env(k):
                env_vars[k] = v
    return env_vars


def parse_qsub(script_text: str) -> dict:
    lines = script_text.splitlines()
    shebang = ""
    directives = []
    module_loads = []
    commands = []
    has_purge = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith("#!"):
            shebang = stripped
        elif stripped.startswith("#$") or stripped.startswith("#SBATCH"):
            directives.append(stripped)
        elif re.match(r"^module\s+purge\b", stripped):
            has_purge = True
        elif re.match(r"^module\s+load\b", stripped):
            module_loads.append(stripped)
        elif stripped and not stripped.startswith("#"):
            commands.append(stripped)

    scheduler = "slurm" if any("#SBATCH" in d for d in directives) else "sge"

    return {
        "shebang": shebang or "#!/bin/bash -l",
        "directives": directives,
        "has_purge": has_purge,
        "module_loads": module_loads,
        "commands": commands,
        "scheduler": scheduler,
    }


def stage1(args):
    print(BANNER)

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_name(
        input_path.stem + "_defcon" + input_path.suffix
    )
    def_out = args.def_out or str(output_path.with_suffix(".def"))

    script_text = input_path.read_text()
    parsed = parse_qsub(script_text)

    scheduler = args.scheduler or parsed["scheduler"]

    trace_file = "${TMPDIR}/defcon_trace.out"
    env_file = "${TMPDIR}/defcon_env.out"

    run_script_path = output_path.with_suffix(".run.sh")
    purge_lines = (
        [
            "# module purge detected — running it first to start from a clean state",
            "module purge",
            "",
        ]
        if parsed["has_purge"] else []
    )

    run_script_lines = [
        parsed["shebang"],
        "",
    ] + purge_lines + [
        "# === Generated by defcon stage1 — do not edit ===",
        "",
    ] + parsed["module_loads"] + [
        "",
        "# --- Original commands ---",
    ] + parsed["commands"]

    run_script_path.write_text("\n".join(run_script_lines) + "\n")
    run_script_path.chmod(0o755)

    defcon_exe = Path(sys.argv[0]).resolve()

    stage2_cmd = [
        "python3",
        str(defcon_exe),
        "stage2",
        "-t", trace_file,
        "-e", env_file,
        "--command-file", str(run_script_path),
        "-o", def_out,
        "-s", args.singularity_image,
    ]

    if args.include:
        stage2_cmd.extend(["--inc", args.include])
    if args.exclude:
        stage2_cmd.extend(["--exc", args.exclude])

    job_lines = [
        parsed["shebang"],
        "",
        "# === Generated by defcon stage1 — submit this script ===",
        "",
    ] + parsed["directives"] + [
        "",
        "# Capture environment before modules alter it",
        f"env -0 > {env_file}",
        "",
        "# Run original script under strace",
        f"strace -f -e trace=file -s 4096 -o {trace_file} bash {shlex.quote(str(run_script_path))}",
        "",
        "# Automatically generate Singularity definition (DEFCON 1)",
        _shlex_join(stage2_cmd),
    ]

    output_path.write_text("\n".join(job_lines) + "\n")
    output_path.chmod(0o755)

    print(f"  Input script  : {input_path}")
    print(f"  Run wrapper   : {run_script_path}")
    print(f"  Instrumented  : {output_path}")
    print(f"  Base image    : {args.singularity_image}")
    print(f"  .def will be  : {def_out}")

    if args.include:
        print(f"  Force include : {args.include}")
    if args.exclude:
        print(f"  Force exclude : {args.exclude}")

    print()

    if scheduler == "sge":
        print(f"  Next step:  qsub {output_path}")
    else:
        print(f"  Next step:  sbatch {output_path}")

    print()
    print(DEFCON_STATUS[3])
    print()


def stage2(args):
    print(BANNER)
    print(DEFCON_STATUS[2])
    print()

    trace_path = Path(args.trace)
    env_path = Path(args.env)
    output_path = Path(args.output)
    singularity_image = args.singularity_image

    if not trace_path.exists():
        sys.exit(f"Error: trace file not found: {trace_path}")
    if not env_path.exists():
        sys.exit(f"Error: env file not found: {env_path}")

    include_paths = _parse_path_list(args.include)
    exclude_paths = _parse_path_list(args.exclude)

    print("  Parsing strace output…")
    detected_files = parse_strace_file(trace_path)
    detected_blocked_libs = parse_blocked_module_libs(trace_path)
    modules = summarize_modules(trace_path)

    files = _apply_path_overrides(
        detected_paths=detected_files,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
    )

    blocked_libs = _apply_path_overrides(
        detected_paths=detected_blocked_libs,
        include_paths=[],
        exclude_paths=exclude_paths,
    )

    print(f"  Found {len(modules)} module(s):")
    for m in modules:
        print(f"    {m}")

    if include_paths:
        print(f"  Force-including {len(include_paths)} path(s):")
        for path in include_paths:
            status = "excluded" if _path_is_under_any(path, exclude_paths) else "included"
            print(f"    {path} ({status})")

    if exclude_paths:
        print(f"  Force-excluding {len(exclude_paths)} path root(s):")
        for path in exclude_paths:
            print(f"    {path}")

    if blocked_libs:
        print(f"  Found {len(blocked_libs)} runtime lib(s) from support modules:")
        for lib in blocked_libs:
            print(f"    {lib}")

    print("  Loading environment variables…")
    env_vars = load_env_vars(env_path)

    project_files = [f for f in files if not _is_module_install_root(f)]
    module_roots = [f for f in files if _is_module_install_root(f)]

    all_files = sorted(set(project_files + blocked_libs))
    files_section = (
        "\n".join(f"    {p}" for p in all_files)
        if all_files else "    # (no project files detected)"
    )

    rsync_lines = []
    for root in module_roots:
        container_dest = f"${{SINGULARITY_ROOTFS}}{root}"
        rsync_lines.append(f"    mkdir -p {container_dest}")
        rsync_lines.append(f"    rsync -rL {root}/ {container_dest}/")

    rsync_section = "\n".join(rsync_lines) if rsync_lines else "    # (no module roots detected)"

    module_bins = []
    module_libs = []

    for root in module_roots:
        rp = Path(root)
        module_bins.append(str(rp / "bin"))
        module_libs.append(str(rp / "lib64"))
        module_libs.append(str(rp / "lib"))

    existing_path = env_vars.get("PATH", "/usr/bin:/bin")
    base_path_parts = [p for p in existing_path.split(":") if p and p not in module_bins]
    env_vars["PATH"] = ":".join(module_bins + ["/usr/local/bin"] + base_path_parts)

    existing_ldpath = env_vars.get("LD_LIBRARY_PATH", "")
    base_ld_parts = [p for p in existing_ldpath.split(":") if p and p not in module_libs]

    blocked_lib_dirs = sorted({str(Path(lib).parent) for lib in blocked_libs})
    all_lib_dirs = module_libs + [d for d in blocked_lib_dirs if d not in module_libs]

    env_vars["LD_LIBRARY_PATH"] = ":".join(all_lib_dirs + base_ld_parts)

    env_section = "\n".join(
        f"    export {k}={_shell_quote(v)}" for k, v in sorted(env_vars.items())
    )

    def_content = DEF_TEMPLATE.format(
        singularity_image=singularity_image,
        files_section=files_section,
        rsync_section=rsync_section,
        env_section=env_section,
    )

    output_path.write_text(def_content)

    print()
    print(f"  Written: {output_path}")
    print()
    print(DEFCON_STATUS[1])
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="defcon",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="stage", metavar="stage")

    p1 = sub.add_parser(
        "stage1",
        help="Instrument a job script for strace capture  [DEFCON 3->2]",
    )
    p1.add_argument("-i", "--input", required=True, metavar="INPUT.QSUB",
                    help="Input job script")
    p1.add_argument("-o", "--output", metavar="OUTPUT.QSUB",
                    help="Output instrumented job script")
    p1.add_argument("--def-out", metavar="CONTAINER.DEF",
                    help="Path where stage2 should write the .def")
    p1.add_argument("-s", "--singularity-image", required=True, metavar="BASE.SIF",
                    help="Singularity base image to use")
    p1.add_argument("--scheduler", choices=["sge", "slurm"],
                    help="Override scheduler detection")
    p1.add_argument("-inc", "--inc", dest="include", metavar="PATH1,PATH2,...",
                    help="Comma-separated paths to force include")
    p1.add_argument("-exc", "--exc", dest="exclude", metavar="PATH1,PATH2,...",
                    help="Comma-separated path roots to force exclude")

    p2 = sub.add_parser(
        "stage2",
        help="Parse strace output and generate Singularity .def  [DEFCON 2->1]",
    )
    p2.add_argument("-t", "--trace", required=True, metavar="TRACE.OUT",
                    help="strace output file")
    p2.add_argument("-e", "--env", required=True, metavar="ENV.OUT",
                    help="env -0 dump file")
    p2.add_argument("--command-file", metavar="JOB.RUN.SH",
                    help="Generated run script path; retained for compatibility")
    p2.add_argument("-o", "--output", required=True, metavar="CONTAINER.DEF",
                    help="Output Singularity definition file")
    p2.add_argument("-s", "--singularity-image", required=True, metavar="BASE.SIF",
                    help="Singularity base image to use")
    p2.add_argument("-inc", "--inc", dest="include", metavar="PATH1,PATH2,...",
                    help="Comma-separated paths to force include")
    p2.add_argument("-exc", "--exc", dest="exclude", metavar="PATH1,PATH2,...",
                    help="Comma-separated path roots to force exclude")

    args = parser.parse_args()

    if args.stage == "stage1":
        stage1(args)
    elif args.stage == "stage2":
        stage2(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()