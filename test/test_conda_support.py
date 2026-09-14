"""Regression tests for Conda capture without a cluster or Conda installation."""

import argparse
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

import defcon
from strace_parser import parse_conda_roots


class CondaSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.prefix("miniconda")
        hook = self.base / "etc/profile.d/conda.sh"
        hook.parent.mkdir(parents=True)
        hook.touch()
        self.env = self.prefix("custom envs/defcon-test")
        self.trace = self.root / "trace"
        self.trace.write_text(
            f'openat(AT_FDCWD, "{hook}", O_RDONLY) = 3\n'
            f'execve("{self.env}/bin/python", ["python"], 0x0) = 0\n'
        )

    def prefix(self, name):
        prefix = self.root / name
        (prefix / "conda-meta").mkdir(parents=True)
        return prefix

    def definition(self, exclude=None):
        env_file = self.root / "env"
        env_file.write_bytes(b"PATH=/usr/bin:/bin\0CONDA_PREFIX=/old/env\0CONDA_SHLVL=2\0")
        output = self.root / "container.def"
        with contextlib.redirect_stdout(io.StringIO()):
            defcon.stage2(argparse.Namespace(
                trace=str(self.trace), env=str(env_file), output=str(output),
                singularity_image="base.sif", include=None, exclude=exclude,
            ))
        return output.read_text()

    def test_detects_prefixes_outside_project_and_module_paths(self):
        self.assertEqual(parse_conda_roots(self.trace), sorted(map(str, [self.base, self.env])))

    def test_failed_probe_does_not_capture_unused_environment(self):
        unused = self.prefix("unused")
        with self.trace.open("a") as trace:
            trace.write(f'openat(AT_FDCWD, "{unused}/missing", O_RDONLY) = -1 ENOENT\n')
        self.assertNotIn(str(unused), parse_conda_roots(self.trace))

    def test_non_conda_job_keeps_module_capture(self):
        module = "/share/pkg.8/python3/3.12.4/install"
        self.trace.write_text(f'execve("{module}/bin/python", [], 0x0) = 0\n')
        definition = self.definition()
        self.assertIn(f"rsync -rL {module}/", definition)
        self.assertNotIn("export CONDA_ENVS_PATH=", definition)

    def test_definition_copies_prefixes_and_supports_named_activation(self):
        definition = self.definition()
        self.assertIn(str(self.base / "condabin"), definition)
        self.assertIn("export CONDA_ENVS_PATH=" + defcon._shell_quote(str(self.env.parent)), definition)
        self.assertNotIn("export CONDA_PREFIX=", definition)
        self.assertNotIn("export CONDA_SHLVL=", definition)
        setup = definition.split("%setup\n", 1)[1].split("%post", 1)[0]
        self.assertEqual(setup.count("    rsync -rL"), 2)
        subprocess.run(["bash", "-n"], input=setup, text=True, check=True)

    def test_nested_prefix_copied_once_and_exclusions_respected(self):
        nested = self.prefix("miniconda/envs/unused")
        with self.trace.open("a") as trace:
            trace.write(f'execve("{nested}/bin/python", [], 0x0) = 0\n')
        definition = self.definition(str(nested))
        self.assertIn("--exclude=/envs/unused", definition)
        self.assertEqual(definition.count("    rsync -rL"), 2)
        definition = self.definition()
        self.assertEqual(definition.count("    rsync -rL"), 2)

    def test_stage1_preserves_module_order_and_multiline_shell_syntax(self):
        script = self.root / "job.qsub"
        original = '#!/bin/bash -l\n#$ -cwd\nset -e\nmodule load miniconda\neval "$(\n  conda shell.bash hook\n)"\nconda activate defcon-test\npython conda_test.py\n'
        script.write_text(original)
        output = self.root / "job_defcon.qsub"
        with contextlib.redirect_stdout(io.StringIO()):
            defcon.stage1(argparse.Namespace(
                input=str(script), output=str(output), def_out=None,
                singularity_image="base.sif", scheduler=None,
                include=None, exclude=None,
            ))
        run_script = output.with_suffix(".run.sh")
        self.assertEqual(run_script.read_text(), original)
        subprocess.run(["bash", "-n", str(run_script)], check=True)

    def test_environment_values_are_not_evaluated_as_shell_code(self):
        value = "$(printf unexpected) $HOME `printf unexpected` 'quoted'"
        result = subprocess.run(
            ["bash", "-c", "export VALUE=" + defcon._shell_quote(value) + '; printf "%s" "$VALUE"'],
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout, value)


if __name__ == "__main__":
    unittest.main()
