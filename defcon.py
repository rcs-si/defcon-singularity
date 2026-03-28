#!/usr/bin/env python3
"""
defcon — DEFinition CONtainer generator
========================================
Analyses a job's runtime dependencies via strace and produces a Singularity
.def file that can reproduce the environment inside a container.

Stages count DOWN to DEFCON 1 (package ready), like the real threat-level scale.

  Stage 1 (DEFCON 3 -> 2):
    defcon stage1 -i input.qsub -o output.qsub [--scheduler sge|slurm]

    Reads your job script, wraps it with strace instrumentation, and writes a
    new job script that:
      1. Captures the runtime environment (env -0)
      2. Runs your original commands under strace
      3. Automatically calls "defcon stage2" to produce the .def

    Then just:  qsub output.qsub   (or sbatch)

  Stage 2 (DEFCON 2 -> 1):
    defcon stage2 -t trace.out -e env.out --command-file job.run.sh -o container.def

    Parses the strace + env files and writes a Singularity definition.
    Called automatically from the instrumented job script.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from strace_parser import parse_strace_file, summarize_modules, parse_blocked_module_libs

# ── DEFCON ascii art ──────────────────────────────────────────────────────────

BANNER = r"""
  ██████╗ ███████╗███████╗ ██████╗ ██████╗ ███╗   ██╗
  ██╔══██╗██╔════╝██╔════╝██╔════╝██╔═══██╗████╗  ██║
  ██║  ██║█████╗  █████╗  ██║     ██║   ██║██╔██╗ ██║
  ██║  ██║██╔══╝  ██╔══╝  ██║     ██║   ██║██║╚██╗██║
  ██████╔╝███████╗██║     ╚██████╗╚██████╔╝██║ ╚████║
  ╚═════╝ ╚══════╝╚═╝      ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝
"""

DEFCON_STATUS = {
    3: "⚠️  DEFCON 3  — Instrumented job ready. Submit it to proceed.",
    2: "🔶 DEFCON 2  — Job complete. Parsing dependencies…",
    1: "✅ DEFCON 1  — Container definition ready. You are go for launch.",
}

# ── Singularity templates ─────────────────────────────────────────────────────

DEF_TEMPLATE = """\
Bootstrap: localimage
From: /projectnb/rcs-intern/brian/alma8_singularity/images/scc-alma8.simg

%files
{files_section}

%setup
    # rsync -rL dereferences cyclic symlinks that break %%files cp -r
{rsync_section}

%environment
{env_section}

%runscript
    {run_command}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

# Env vars that are session-specific and meaningless (or harmful) inside a container
_ENV_BLOCKLIST = {
    "PWD", "OLDPWD", "SHLVL", "_", "LS_COLORS",
    # Terminal / SSH session
    "SSH_CLIENT", "SSH_CONNECTION", "SSH_TTY", "SSH_AUTH_SOCK",
    "TERM", "TERMINFO", "COLORTERM", "COLUMNS", "LINES",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_SESSION_ID",
    "HOSTNAME", "HISTCONTROL", "HISTSIZE", "HISTFILE",
    "LESSOPEN", "LESSCLOSE", "MAIL", "LOGNAME",
    "S_COLORS", "which_declare",
    # Singularity sets these itself
    "SINGULARITY_CACHEDIR", "SINGULARITY_BIND", "SINGULARITYENV_PREPEND_PATH",
    # Fix #1: SGE / job scheduler runtime vars — meaningless inside a container
    "JOB_ID", "JOB_NAME", "JOB_SCRIPT",
    "NHOSTS", "NQUEUES", "NSLOTS",
    "QUEUE", "REQNAME", "REQUEST", "RESTARTED",
    "ENVIRONMENT",          # SGE "BATCH" flag
    "TMP", "TMPDIR",        # scratch dirs that won't exist in the container
    "USER", "HOME", "SHELL",
    "MANPATH",
    "ARC",
    # Fix #1: Lmod / module-system vars not caught by _is_module_system_var prefix check
    "MODULESHOME", "MODULEPATH_ROOT",
    "BASH_ENV",             # points to lmod init script — not wanted in container
}

def _is_blocked_env(key: str) -> bool:
    if key in _ENV_BLOCKLIST:
        return True
    # Shell functions exported as env vars (bash exports them as BASH_FUNC_name%%)
    if "%%" in key or key.startswith("BASH_FUNC_"):
        return True
    # Fix #1: catch all SGE_ prefixed vars (SGE_ROOT, SGE_CELL, SGE_O_*, etc.)
    if key.startswith("SGE_"):
        return True
    # Fix #2: catch all Lmod/module-system vars here too so they're blocked
    # in load_env_vars (not just in the diff path via _is_module_system_var)
    if key.startswith("LMOD") or key.startswith("MODULEPATH"):
        return True
    return False


def load_env_vars(path: Path) -> dict:
    """Parse an env -0 dump file into a dict, filtering session noise."""
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


def _is_module_system_var(key: str) -> bool:
    """Return True for Lmod/module-system internals that should never go in the .def."""
    if key.startswith("LMOD") or key.startswith("MODULEPATH"):
        return True
    # _ModuleTable001_, _ModuleTable002_, … Lmod state blobs
    if re.match(r'^_ModuleTable\w+_$', key):
        return True
    # Fix #1: remaining module-system vars not covered by prefix checks
    if key in {"MODULESHOME", "MODULEPATH_ROOT", "BASH_ENV"}:
        return True
    return False


def diff_env_vars(pre_env: dict, post_env: dict) -> dict:
    """
    Return variables that are new or changed in post_env relative to pre_env,
    skipping Lmod/module-system internals and session-specific noise.
    These are the vars set (or modified) by 'module load' / conda activate and
    belong in the .def %environment section.
    """
    diff = {}
    for key, value in post_env.items():
        if _is_module_system_var(key) or _is_blocked_env(key):
            continue
        if key not in pre_env or pre_env[key] != value:
            diff[key] = value
    return diff


def parse_qsub(script_text: str) -> dict:
    """
    Split a qsub/sbatch script into:
      - shebang      : first line if it starts with #!
      - directives   : scheduler directive lines (#$ or #SBATCH)
      - has_purge    : True if 'module purge' appears anywhere in the script
      - module_loads : 'module load ...' lines (excluding purge)
      - commands     : all other non-blank, non-comment lines (excluding purge)
      - scheduler    : 'sge' or 'slurm' (guessed from directives)
    """
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
        elif re.match(r'^module\s+purge\b', stripped):
            has_purge = True  # hoisted to top of run wrapper, not kept inline
        elif re.match(r'^module\s+load\b', stripped):
            module_loads.append(stripped)
        elif stripped and not stripped.startswith("#"):
            # Skip only defcon-injected env capture line, not user commands
            if re.match(r'^env\s+-0\s+>', stripped):
                continue
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


# ── Stage 1 ───────────────────────────────────────────────────────────────────

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
    # Paths for the strace job's output files (use $TMPDIR if available on cluster)
    trace_file = "$TMPDIR/defcon_trace.out"
    env_file   = "$TMPDIR/defcon_env.out"

    # ── wrapper run-script (what strace actually executes) ──
    run_script_path = output_path.with_suffix(".run.sh")
    purge_lines = (
        ["# module purge detected — running it first to start from a clean state",
         "module purge", ""]
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
    ] + parsed["commands"] + [
        "",
        "# Capture environment after job completes (conda activate already ran above)",
        "env -0 > $TMPDIR/defcon_env_post.out",
    ]

    run_script_path.write_text("\n".join(run_script_lines) + "\n")
    run_script_path.chmod(0o755)

    # ── defcon self-path so stage2 can be called from the job ──
    defcon_exe = Path(sys.argv[0]).resolve()

    # ── instrumented job script ──
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
        f"strace -f -e trace=file -s 4096 -o {trace_file} bash {run_script_path}",
        "",
        "# Automatically generate Singularity definition (DEFCON 1)",
        (
            f'python3 {defcon_exe} stage2'
            f' -t {trace_file}'
            f' -e {env_file}'
            f' --env-post $TMPDIR/defcon_env_post.out'
            f' --command-file {run_script_path}'
            f' -o {def_out}'
        ),
    ]

    output_path.write_text("\n".join(job_lines) + "\n")
    output_path.chmod(0o755)

    print(f"  Input script  : {input_path}")
    print(f"  Run wrapper   : {run_script_path}")
    print(f"  Instrumented  : {output_path}")
    print(f"  .def will be  : {def_out}")
    print()

    if scheduler == "sge":
        print(f"  Next step:  qsub {output_path}")
    else:
        print(f"  Next step:  sbatch {output_path}")
    print()
    print(DEFCON_STATUS[3])
    print()


# ── Stage 2 ───────────────────────────────────────────────────────────────────

def stage2(args):
    print(BANNER)
    print(DEFCON_STATUS[2])
    print()

    trace_path = Path(args.trace)
    env_path   = Path(args.env)
    output_path = Path(args.output)

    if not trace_path.exists():
        sys.exit(f"Error: trace file not found: {trace_path}")
    if not env_path.exists():
        sys.exit(f"Error: env file not found: {env_path}")

    # Fix #2: exclude the defcon working directory AND all its ancestors that
    # fall under an INTERESTING_PREFIX, but stop before the prefix root itself
    # (e.g. exclude /projectnb/rcs-intern/reetom but NOT /projectnb, so that
    # other projectnb paths like the conda env are still captured).
    from strace_parser import INTERESTING_PREFIXES as _INTERESTING
    workdir_path = output_path.resolve().parent
    exclude_set = set()
    p = workdir_path
    while True:
        s = str(p)
        # Stop once we've reached the bare interesting prefix itself
        if s in _INTERESTING:
            break
        if not any(s.startswith(prefix + "/") for prefix in _INTERESTING):
            break
        exclude_set.add(s)
        parent = p.parent
        if parent == p:
            break
        p = parent
    exclude = tuple(exclude_set)

    # ── Load environment files early so we can detect conda paths ──
    print("  Loading environment variables…")
    pre_env = load_env_vars(env_path)

    env_post_path = Path(args.env_post) if args.env_post else None
    if env_post_path:
        if not env_post_path.exists():
            print(f"  WARNING: post-job env file not found: {env_post_path}")
            print("  Falling back to pre-job environment (module vars may be incomplete).")
            post_env = pre_env
            env_vars = pre_env
        else:
            post_env = load_env_vars(env_post_path)
            env_vars = diff_env_vars(pre_env, post_env)
            print(f"  Found {len(env_vars)} new/changed variable(s) from module loads.")
            if not env_vars:
                print("  WARNING: env diff is empty — falling back to pre-job environment.")
                env_vars = pre_env
    else:
        post_env = pre_env
        env_vars = pre_env

    # Auto-detect conda environment paths so they don't flood %files.
    # Conda envs are huge; they should be bind-mounted at runtime, not copied in.
    active_env = post_env if post_env is not pre_env else pre_env
    conda_paths: list = []
    for key in ("CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
        val = active_env.get(key, "")
        if val and val.startswith("/") and val not in conda_paths:
            conda_paths.append(val)
    if conda_paths:
        print("  Detected conda env(s) — excluding from %%files (bind-mount at runtime):")
        for cp in conda_paths:
            print(f"    {cp}")
        print(f"  Hint: singularity run --bind {conda_paths[0]} test_python.sif")
    exclude = tuple(set(exclude) | set(conda_paths))

    # ── Parse strace ──
    print("  Parsing strace output…")
    files = parse_strace_file(trace_path, exclude_paths=exclude)
    modules = summarize_modules(trace_path)
    blocked_libs = parse_blocked_module_libs(trace_path)

    print(f"  Found {len(modules)} module(s):")
    for m in modules:
        print(f"    {m}")
    if blocked_libs:
        print(f"  Found {len(blocked_libs)} runtime lib(s) from support modules (gcc/intel/flexiblas):")
        for lib in blocked_libs:
            print(f"    {lib}")

    # Build .def sections
    # Project files + individual .so files from support modules -> %files
    # Module install roots -> %setup rsync -rL (handles cyclic symlinks)
    project_files = [f for f in files if not f.startswith("/share/pkg")]
    module_roots  = [f for f in files if f.startswith("/share/pkg")]

    # Combine project files with individual runtime libs from blocked modules
    all_files = sorted(project_files + blocked_libs)
    files_section = (
        "\n".join(f"    {p}" for p in all_files)
        if all_files else "    # (no project files detected)"
    )

    rsync_lines = []
    for root in module_roots:
        container_dest = f"${{SINGULARITY_ROOTFS}}{root}"
        rsync_lines.append(f"    mkdir -p {container_dest}")
        rsync_lines.append(f"    rsync -rL {root}/ {container_dest}/")
    rsync_section = "\n".join(rsync_lines)

    if not env_post_path:
        # Fallback: reconstruct PATH / LD_LIBRARY_PATH from strace-detected module roots.
        # Superseded when --env-post is available (the diff already has correct values).
        module_bins = []
        module_libs = []
        for f in files:
            fp = Path(f)
            if not f.startswith("/share/pkg"):
                continue
            module_bins.append(str(fp / "bin"))
            module_libs.append(str(fp / "lib64"))
            module_libs.append(str(fp / "lib"))

        existing_path = env_vars.get("PATH", "/usr/bin:/bin")
        base_path_parts = [p for p in existing_path.split(":") if p not in module_bins]
        env_vars["PATH"] = ":".join(module_bins + ["/usr/local/bin"] + base_path_parts)

        existing_ldpath = env_vars.get("LD_LIBRARY_PATH", "")
        base_ld_parts = [p for p in existing_ldpath.split(":") if p and p not in module_libs]
        blocked_lib_dirs = sorted({str(Path(lib).parent) for lib in blocked_libs})
        all_lib_dirs = module_libs + [d for d in blocked_lib_dirs if d not in module_libs]
        env_vars["LD_LIBRARY_PATH"] = ":".join(all_lib_dirs + base_ld_parts)

    env_section = "\n".join(
        f"    export {k}={_shell_quote(v)}" for k, v in sorted(env_vars.items())
    )

    # Strip 'module load ...' from runscript — handled by PATH now
    raw_command = _load_raw_command(args)
    run_steps = [
        step.strip()
        for step in re.split(r"\s*&&\s*", raw_command)
        if not re.match(r"^module\s+", step.strip())
    ]
    run_command = " && ".join(run_steps) if run_steps else "bash"

    if raw_command != run_command:
        print("  Stripped 'module load' from runscript (modules are on PATH).")
    def_content = DEF_TEMPLATE.format(
        files_section=files_section,
        rsync_section=rsync_section,
        env_section=env_section,
        run_command=run_command,
    )

    output_path.write_text(def_content)

    print()
    print(f"  Written: {output_path}")
    print()
    print(DEFCON_STATUS[1])
    print()


def _load_raw_command(args) -> str:
    """
    Load the run command from --command-file when provided, else from --command.
    """
    if args.command_file:
        command_path = Path(args.command_file)
        if not command_path.exists():
            sys.exit(f"Error: command file not found: {command_path}")
        parsed = parse_qsub(command_path.read_text())
        all_steps = parsed["module_loads"] + parsed["commands"]
        if all_steps:
            return " && ".join(all_steps)
    return args.command or "bash"


def _shell_quote(value: str) -> str:
    """Wrap a value in double quotes, escaping inner double quotes."""
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="defcon",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="stage", metavar="stage")

    # stage1
    p1 = sub.add_parser(
        "stage1",
        help="Instrument a job script for strace capture  [DEFCON 3->2]",
    )
    p1.add_argument("-i", "--input",  required=True, metavar="INPUT.QSUB",
                    help="Input job script (qsub/sbatch)")
    p1.add_argument("-o", "--output", metavar="OUTPUT.QSUB",
                    help="Output instrumented job script (default: <input>_defcon.qsub)")
    p1.add_argument("--def-out", metavar="CONTAINER.DEF",
                    help="Path where stage2 should write the .def (default: <output>.def)")
    p1.add_argument("--scheduler", choices=["sge", "slurm"],
                    help="Override scheduler detection (sge or slurm)")

    # stage2
    p2 = sub.add_parser(
        "stage2",
        help="Parse strace output and generate Singularity .def  [DEFCON 2->1]",
    )
    p2.add_argument("-t", "--trace",    required=True, metavar="TRACE.OUT",
                    help="strace output file")
    p2.add_argument("-e", "--env",      required=True, metavar="ENV.OUT",
                    help="env -0 dump captured before the job (pre-module)")
    p2.add_argument("--env-post",       metavar="ENV_POST.OUT",
                    help="env -0 dump captured after the job; diff with --env gives module-set vars")
    p2.add_argument("-c", "--command", metavar="'CMD'",
                    help="Command to embed in %%runscript (legacy; use --command-file)")
    p2.add_argument("--command-file", metavar="JOB.RUN.SH",
                    help="Path to a script file from which run commands are extracted")
    p2.add_argument("-o", "--output",  required=True, metavar="CONTAINER.DEF",
                    help="Output Singularity definition file")

    args = parser.parse_args()

    if args.stage == "stage1":
        stage1(args)
    elif args.stage == "stage2":
        if not args.command and not args.command_file:
            parser.error("stage2 requires one of: -c/--command or --command-file")
        stage2(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()