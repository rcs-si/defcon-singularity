#!/usr/bin/env python3
from pathlib import Path
import argparse
from strace_parser import parse_strace_file
import os
import json

def load_env_vars(path):
    """Load environment variables from env -0 output file."""
    env_vars = {}
    raw = Path(path).read_bytes()
    for entry in raw.split(b"\x00"):
        if b"=" in entry:
            key, value = entry.split(b"=", 1)
            key = key.decode()
            value = value.decode()
            # Ignore shell noise
            if key not in ("PWD", "OLDPWD", "SHLVL", "_"):
                env_vars[key] = value
    return env_vars


def detect_conda_env(env_vars: dict) -> dict:
    """
    Detect conda environment from environment variables.
    Returns a dict with conda_prefix and conda_env_name if found.
    """
    conda_info = {}
    
    # Check for CONDA_PREFIX (active conda environment)
    if "CONDA_PREFIX" in env_vars:
        conda_info["conda_prefix"] = env_vars["CONDA_PREFIX"]
    
    # Check for CONDA_DEFAULT_ENV or derive from CONDA_PREFIX
    if "CONDA_DEFAULT_ENV" in env_vars:
        conda_info["conda_env_name"] = env_vars["CONDA_DEFAULT_ENV"]
    elif "CONDA_PREFIX" in env_vars:
        # Extract env name from path (e.g., /path/to/envs/myenv -> myenv)
        conda_info["conda_env_name"] = Path(env_vars["CONDA_PREFIX"]).name
    
    return conda_info


DEF_TEMPLATE = """Bootstrap: localimage
From: /projectnb/rcs-intern/brian/alma8_singularity/images/scc-alma8.simg

%files
{files_section}

%post
    yum -y update
    yum -y install python3 python3-pip
{conda_install_section}

%environment
{env_section}
    export PATH=/usr/local/bin:$PATH
"""

DEF_TEMPLATE_WITH_CONDA = """Bootstrap: localimage
From: /projectnb/rcs-intern/brian/alma8_singularity/images/scc-alma8.simg

%files
{files_section}

%post
    yum -y update
    yum -y install python3 python3-pip
    # Initialize conda and clone environment
    source /opt/miniconda3/etc/profile.d/conda.sh || source /usr/local/etc/profile.d/conda.sh || true

%environment
{env_section}
    export PATH=/usr/local/bin:$PATH
    # Source conda initialization if available
    if [ -f /opt/miniconda3/etc/profile.d/conda.sh ]; then
        source /opt/miniconda3/etc/profile.d/conda.sh
    fi
"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate Singularity container definition from strace output"
    )
    parser.add_argument("trace", help="Path to strace.out")
    parser.add_argument("--env", help="env -0 output file", required=True)
    parser.add_argument("--run-command", required=True, 
                       help="Command to run in the container")
    parser.add_argument("--output", required=True,
                       help="Output Singularity definition file")
    parser.add_argument("--detect-conda", action="store_true",
                       help="Detect and include conda environment information")
    args = parser.parse_args()

    trace_path = Path(args.trace)
    env_vars = load_env_vars(args.env)
    
    # Detect conda environment if requested
    conda_info = {}
    if args.detect_conda:
        conda_info = detect_conda_env(env_vars)
        if conda_info:
            print(f"Detected conda environment: {conda_info}")

    files = parse_strace_file(trace_path)
    files_lines = "\n".join(f"    {p}" for p in files)

    env_lines = "\n".join(f"    export {k}=\"{v}\"" for k, v in env_vars.items())
    
    # Prepare conda installation section
    conda_install_section = ""
    if conda_info:
        conda_install_section = (
            "\n    # NOTE: Conda environment detected in original environment\n"
            "    # If needed, copy conda environment packages from source system\n"
            f"    # Original conda prefix: {conda_info.get('conda_prefix', 'N/A')}\n"
            f"    # Original conda env: {conda_info.get('conda_env_name', 'N/A')}"
        )
    
    template = DEF_TEMPLATE_WITH_CONDA if conda_info else DEF_TEMPLATE

    def_content = template.format(
        files_section=files_lines,
        env_section=env_lines,
        conda_install_section=conda_install_section,
    )

    Path(args.output).write_text(def_content)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
