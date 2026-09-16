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
import sys
from pathlib import Path

from definition_generator import render_definition
from dependency_resolver import resolve_dependencies
from environments import load_env_vars
from job_parser import parse_qsub
from path_utils import _parse_path_list, _path_is_under_any
from tracer import render_instrumented_job

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

    run_script_path = output_path.with_suffix(".run.sh")
    # Preserve ordering and shell syntax, including multiline Conda hooks and
    # heredocs. Scheduler directives are harmless comments in this run script.
    run_script_lines = script_text.splitlines()

    run_script_path.write_text("\n".join(run_script_lines) + "\n")
    run_script_path.chmod(0o755)

    wrapper = render_instrumented_job(
        parsed, run_script_path, def_out, args.singularity_image,
        Path(__file__).with_name("defcon.py").resolve(), args.include, args.exclude,
    )
    output_path.write_text(wrapper)
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
    plan = resolve_dependencies(trace_path, include_paths, exclude_paths)
    modules = plan.modules
    blocked_libs = plan.blocked_libs

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

    if plan.conda_roots:
        print("  Conda prefixes (copied in full):")
        for root in plan.conda_roots:
            print(f"    {root}")
    def_content = render_definition(plan, env_vars, singularity_image)

    output_path.write_text(def_content)

    print()
    print(f"  Written: {output_path}")
    print()
    print(DEFCON_STATUS[1])
    print()


def build_parser():
    """Build the argument parser independently of process arguments."""
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

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.stage == "stage1":
        stage1(args)
    elif args.stage == "stage2":
        stage2(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
