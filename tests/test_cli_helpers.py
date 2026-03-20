from pathlib import Path
from types import SimpleNamespace

from defcon_singularity.cli import _load_raw_command, load_env_vars, parse_qsub


def test_parse_qsub_extracts_sections() -> None:
    script = """#!/bin/bash -l
#$ -pe omp 4
module purge
module load python3/3.13.8
python3 myscript.py
"""
    parsed = parse_qsub(script)

    assert parsed["shebang"] == "#!/bin/bash -l"
    assert parsed["directives"] == ["#$ -pe omp 4"]
    assert parsed["has_purge"] is True
    assert parsed["module_loads"] == ["module load python3/3.13.8"]
    assert parsed["commands"] == ["python3 myscript.py"]
    assert parsed["scheduler"] == "sge"


def test_load_env_vars_filters_shell_noise(tmp_path: Path) -> None:
    env_file = tmp_path / "env.out"
    env_file.write_bytes(
        b"PATH=/usr/bin\x00"
        b"PWD=/tmp/work\x00"
        b"BASH_FUNC_module%%=() { :; }\x00"
        b"CUSTOM=value\x00"
    )

    env_vars = load_env_vars(env_file)

    assert env_vars == {"PATH": "/usr/bin", "CUSTOM": "value"}


def test_load_raw_command_uses_command_file_when_present(tmp_path: Path) -> None:
    run_script = tmp_path / "job.run.sh"
    run_script.write_text(
        "#!/bin/bash -l\n"
        "module load gcc/12.2.0\n"
        "python3 task.py\n"
    )

    args = SimpleNamespace(command_file=str(run_script), command=None)
    assert _load_raw_command(args) == "module load gcc/12.2.0 && python3 task.py"
