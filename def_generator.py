#!/usr/bin/env python3
from pathlib import Path
import argparse
from strace_parser import parse_strace_file

def load_env_vars(path):
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


DEF_TEMPLATE = """Bootstrap: localimage
From: /projectnb/rcs-intern/brian/alma8_singularity/images/scc-alma8.simg

%files
{files_section}

%post
    yum -y update
    yum -y install python3 python3-pip

%environment
{env_section}
    export PATH=/usr/local/bin:$PATH
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", help="Path to strace.out")
    parser.add_argument("--env", help="env -0 output file", required=True)
    parser.add_argument("--run-command", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace)
    env_vars = load_env_vars(args.env)

    files = parse_strace_file(trace_path)
    files_lines = "\n".join(f"    {p}" for p in files)

    env_lines = "\n".join(f"    export {k}=\"{v}\"" for k, v in env_vars.items())

    def_content = DEF_TEMPLATE.format(
        files_section=files_lines,
        env_section=env_lines,
        run_command=args.run_command,
    )

    Path(args.output).write_text(def_content)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
