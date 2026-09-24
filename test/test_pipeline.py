"""Independent pipeline tests requiring no scheduler, strace, or Singularity."""

import contextlib
import io
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from cli import build_parser, main
from definition_generator import prepare_environment, render_definition
from dependency_resolver import DependencyPlan, resolve_dependencies
from environments import load_env_vars
from environments.conda import prepare_environment as prepare_conda
from environments.modules import runtime_paths
from job_parser import parse_qsub
from tracer import render_instrumented_job


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_scheduler_metadata_and_default_shell(self):
        parsed = parse_qsub('#SBATCH --time=10\nmodule purge\nmodule load python\necho hi\n')
        self.assertEqual(parsed['scheduler'], 'slurm')
        self.assertEqual(parsed['shebang'], '#!/bin/bash -l')
        self.assertEqual(parsed['directives'], ['#SBATCH --time=10'])
        self.assertTrue(parsed['has_purge'])
        self.assertEqual(parsed['module_loads'], ['module load python'])
        self.assertEqual(parse_qsub('echo hi')['scheduler'], 'sge')

    def test_wrapper_preserves_directives_and_forwards_overrides(self):
        wrapper = render_instrumented_job(
            parse_qsub('#!/bin/bash\n#$ -cwd\necho hi'), Path('/jobs/run.sh'),
            '/jobs/out.def', 'base.sif', Path('/tools/defcon.py'),
            '/project/extra', '/project/cache',
        )
        self.assertTrue(wrapper.startswith('#!/bin/bash\n'))
        self.assertIn('#$ -cwd', wrapper)
        command = shlex.split(wrapper.splitlines()[-1])
        self.assertEqual(command[:3], ['python3', '/tools/defcon.py', 'stage2'])
        self.assertEqual(command[-4:], ['--inc', '/project/extra', '--exc', '/project/cache'])
        self.assertIn('${TMPDIR}/defcon_trace.out', command)
        subprocess.run(['bash', '-n'], input=wrapper, text=True, check=True)

    def test_resolver_separates_modules_support_libraries_and_project_files(self):
        trace = self.root / 'trace'
        module = '/share/pkg.8/python/3.12/install'
        lib = '/share/pkg.8/gcc/12/install/lib64/libstdc++.so.6'
        trace.write_text(
            f'openat(0, "{module}/lib/missing", 0) = -1 ENOENT\n'
            f'openat(0, "{lib}", 0) = 3\n'
            'openat(0, "/project/job", 0) = 3\n'
            'openat(0, "/project/job/main.py", 0) = 3\n'
            'openat(0, "/project/job/missing", 0) = -1 ENOENT\n'
        )
        plan = resolve_dependencies(trace, ['/extra', '/project/job/cache'], ['/project/job/cache'])
        self.assertEqual(plan.copy_roots, [module])
        self.assertEqual(plan.modules, ['python/3.12'])
        self.assertEqual(plan.blocked_libs, [lib])
        self.assertEqual(plan.project_files, ['/extra', '/project/job/main.py'])

    def test_environment_dump_filters_host_state_and_preserves_equals(self):
        env = self.root / 'env'
        env.write_bytes(b'PWD=/host\0BASH_FUNC_module%%=function\0VALUE=a=b\0INVALID\0')
        self.assertEqual(load_env_vars(env), {'VALUE': 'a=b'})

    def test_module_paths_do_not_add_conda_libraries(self):
        bins, libs, all_libs = runtime_paths(['/module', '/conda'], ['/conda'], ['/support/libx.so'])
        self.assertEqual(bins, ['/module/bin', '/conda/bin'])
        self.assertEqual(libs, ['/module/lib64', '/module/lib'])
        self.assertEqual(all_libs, libs + ['/support'])

    def test_conda_handler_cleans_activation_without_mutating_snapshot(self):
        base = self.root / 'base'
        hook = base / 'etc/profile.d/conda.sh'
        hook.parent.mkdir(parents=True)
        hook.touch()
        env = self.root / 'envs/science'
        snapshot = {'CONDA_PREFIX': '/host', '_CE_M': 'x', 'KEEP': 'yes'}
        prepared, bins = prepare_conda(snapshot, [str(base), str(env)])
        self.assertEqual(prepared, {'KEEP': 'yes', 'CONDA_ENVS_PATH': str(env.parent)})
        self.assertEqual(bins, [str(base / 'condabin')])
        self.assertEqual(snapshot['CONDA_PREFIX'], '/host')
        self.assertEqual(prepare_conda(snapshot, []), (snapshot, []))

    def test_renderer_is_repeatable_and_does_not_mutate_environment(self):
        plan = DependencyPlan([], ['/module'], [], ['/module'], ['/project/main.py'], [], ['/module/cache'])
        snapshot = {'PATH': '/module/bin:/usr/bin', 'VALUE': 'a $HOME'}
        before = dict(snapshot)
        result = render_definition(plan, snapshot, 'base.sif')
        self.assertEqual(snapshot, before)
        self.assertEqual(result, render_definition(plan, snapshot, 'base.sif'))
        self.assertIn('From: base.sif', result)
        self.assertIn('    /project/main.py', result)
        self.assertIn('--exclude=/cache', result)
        self.assertIn("export VALUE='a $HOME'", result)
        self.assertEqual(prepare_environment(plan, snapshot)['PATH'], '/module/bin:/usr/local/bin:/usr/bin')

    def test_cli_stage1_uses_stable_entrypoint_and_scheduler_override(self):
        source = self.root / 'job.qsub'
        source.write_text('#!/bin/bash\n#$ -cwd\ncat <<EOF\nhello\nEOF\n')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main(['stage1', '-i', str(source), '-s', 'base.sif', '--scheduler', 'slurm'])
        wrapper = self.root / 'job_defcon.qsub'
        self.assertIn('sbatch', stdout.getvalue())
        self.assertEqual(wrapper.with_suffix('.run.sh').read_text(), source.read_text())
        command = shlex.split(wrapper.read_text().splitlines()[-1])
        self.assertEqual(Path(command[1]), Path(__file__).resolve().parents[1] / 'defcon.py')
        self.assertTrue(wrapper.stat().st_mode & 0o111)

    def test_cli_reports_missing_trace(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(SystemExit, 'trace file not found'):
            main(['stage2', '-t', str(self.root / 'missing'), '-e', 'env', '-s', 'base.sif', '-o', 'out.def'])

    def test_cli_accepts_legacy_options(self):
        args = build_parser().parse_args(['stage2', '-t', 'trace', '-e', 'env', '-s', 'base.sif', '-o', 'out.def', '--command-file', 'run.sh', '-inc', '/extra', '-exc', '/skip'])
        self.assertEqual((args.include, args.exclude, args.command_file), ('/extra', '/skip', 'run.sh'))

    def test_script_entrypoint_runs_stage2(self):
        trace, env, output = [self.root / name for name in ('trace', 'env', 'out.def')]
        trace.write_text('')
        env.write_bytes(b'PATH=/usr/bin\0')
        entrypoint = Path(__file__).resolve().parents[1] / 'defcon.py'
        subprocess.run([sys.executable, str(entrypoint), 'stage2', '-t', str(trace), '-e', str(env), '-s', 'base.sif', '-o', str(output)], check=True, capture_output=True, text=True, cwd=self.root)
        self.assertIn('# (no project files detected)', output.read_text())


if __name__ == '__main__':
    unittest.main()
