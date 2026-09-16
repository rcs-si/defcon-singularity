"""Extract scheduler metadata without rewriting the original shell program."""

import re


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
