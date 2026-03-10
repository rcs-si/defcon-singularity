#!/usr/bin/env python3
"""
defcon — DEFinition CONtainer generator
========================================
Analyses a job's runtime dependencies via strace and produces a Singularity
.def file that can reproduce the environment inside a container.

Stages count DOWN to DEFCON 1 (package ready), like the real threat-level scale.

  Stage 1 (DEFCON 2):
    defcon stage1 -i input.qsub -o output.qsub [--scheduler sge|slurm]

    Reads your job script, wraps it with strace instrumentation, and writes a
    new job script that:
      1. Captures the runtime environment (env -0)
      2. Runs your original commands under strace
      3. Automatically calls "defcon stage2" to produce the .def

    Then just:  qsub output.qsub   (or sbatch)

  Stage 2 (DEFCON 1):
    defcon stage2 -t trace.out -e env.out -c "your command" -o container.def

    Parses the strace + env files and writes a Singularity definition.
    Called automatically from the instrumented job script.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from strace_parser import parse_strace_file, summarize_modules

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

%post
    yum -y update
    yum -y install python3 python3-pip

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
}

def _is_blocked_env(key: str) -> bool:
    if key in _ENV_BLOCKLIST:
        return True
    # Shell functions exported as env vars (bash exports them as BASH_FUNC_name%%)
    if "%%" in key or key.startswith("BASH_FUNC_"):
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


def parse_qsub(script_text: str) -> dict:
    """
    Split a qsub/sbatch script into:
      - shebang      : first line if it starts with #!
      - directives   : scheduler directive lines (#$ or #SBATCH)
      - module_loads : 'module load ...' lines
      - commands     : all other non-blank, non-comment lines
      - scheduler    : 'sge' or 'slurm' (guessed from directives)
    """
    lines = script_text.splitlines()
    shebang = ""
    directives = []
    module_loads = []
    commands = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith("#!"):
            shebang = stripped
        elif stripped.startswith("#$") or stripped.startswith("#SBATCH"):
            directives.append(stripped)
        elif re.match(r'^module\s+load\b', stripped):
            module_loads.append(stripped)
        elif stripped and not stripped.startswith("#"):
            commands.append(stripped)

    scheduler = "slurm" if any("#SBATCH" in d for d in directives) else "sge"

    return {
        "shebang": shebang or "#!/bin/bash -l",
        "directives": directives,
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
    # Build the runscript command: module loads first, then user commands, joined with &&
    all_steps = parsed["module_loads"] + parsed["commands"]
    full_command = " && ".join(all_steps)

    # Paths for the strace job's output files (use $TMPDIR if available on cluster)
    trace_file = "$TMPDIR/defcon_trace.out"
    env_file   = "$TMPDIR/defcon_env.out"

    # ── wrapper run-script (what strace actually executes) ──
    run_script_path = output_path.with_suffix(".run.sh")
    run_script_lines = [
        parsed["shebang"],
        "",
        "# === Generated by defcon stage1 — do not edit ===",
        "",
    ] + parsed["module_loads"] + [
        "",
        "# --- Original commands ---",
    ] + parsed["commands"]

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
            f' -c "{full_command}"'
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

    # Parse strace
    print("  Parsing strace output…")
    files = parse_strace_file(trace_path)
    modules = summarize_modules(trace_path)

    print(f"  Found {len(files)} module install root(s):")
    for m in modules:
        print(f"    {m}")

    # Parse environment
    print("  Loading environment variables…")
    env_vars = load_env_vars(env_path)

    # Build .def sections
    # Project files → %files (Singularity handles these with a simple bind copy)
    # Module install roots → %post rsync -rL (dereferences cyclic symlinks that
    # break Singularity's internal cp -r used by %files)
    project_files = [f for f in files if not f.startswith("/share/pkg")]
    module_roots  = [f for f in files if f.startswith("/share/pkg")]

    files_section = (
        "\n".join(f"    {p}" for p in project_files)
        if project_files else "    # (no project files detected)"
    )

    rsync_lines = []
    for root in module_roots:
        container_dest = f"${{SINGULARITY_ROOTFS}}{root}"
        rsync_lines.append(f"    mkdir -p {container_dest}")
        rsync_lines.append(f"    rsync -rL {root}/ {container_dest}/")
    rsync_section = "\n".join(rsync_lines)

    # Derive bin/ and lib64/ paths from each module install root and prepend
    # them to PATH / LD_LIBRARY_PATH so 'module load' is NOT needed at runtime.
    module_bins = []
    module_libs = []
    for f in files:
        fp = Path(f)
        if not f.startswith("/share/pkg"):
            continue
        module_bins.append(str(fp / "bin"))
        module_libs.append(str(fp / "lib64"))
        module_libs.append(str(fp / "lib"))

    # PATH: module bins first, then /usr/local/bin, then the rest from env
    existing_path = env_vars.get("PATH", "/usr/bin:/bin")
    base_path_parts = [p for p in existing_path.split(":") if p not in module_bins]
    env_vars["PATH"] = ":".join(module_bins + ["/usr/local/bin"] + base_path_parts)

    # LD_LIBRARY_PATH: module lib dirs prepended
    existing_ldpath = env_vars.get("LD_LIBRARY_PATH", "")
    base_ld_parts = [p for p in existing_ldpath.split(":") if p and p not in module_libs]
    env_vars["LD_LIBRARY_PATH"] = ":".join(module_libs + base_ld_parts)

    env_section = "\n".join(
        f"    export {k}={_shell_quote(v)}" for k, v in sorted(env_vars.items())
    )

    # Strip 'module load ...' from runscript — handled by PATH now
    raw_command = args.command or "bash"
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
        help="Instrument a job script for strace capture  [DEFCON 3→2]",
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
        help="Parse strace output and generate Singularity .def  [DEFCON 2→1]",
    )
    p2.add_argument("-t", "--trace",   required=True, metavar="TRACE.OUT",
                    help="strace output file")
    p2.add_argument("-e", "--env",     required=True, metavar="ENV.OUT",
                    help="env -0 dump file")
    p2.add_argument("-c", "--command", required=True, metavar="'CMD'",
                    help="Command to embed in %%runscript")
    p2.add_argument("-o", "--output",  required=True, metavar="CONTAINER.DEF",
                    help="Output Singularity definition file")

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