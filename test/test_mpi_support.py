"""MPI capture and launcher tests without a scheduler or MPI installation."""

import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from cli import main
from dependency_resolver import resolve_dependencies
from definition_generator import render_definition
from environments.mpi import inspect_mpi
from job_parser import parse_qsub
from tracer import render_instrumented_job


class MPISupportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.trace = self.root / 'trace'
        self.trace.write_text('')

    def test_detects_successful_mpi_access_and_job_command(self):
        root = '/share/pkg.8/openmpi/4.1/install'
        self.trace.write_text(
            f'openat(0, "{root}/lib/libmpi.so.40", 0) = -1 ENOENT\n'
        )
        self.assertEqual(inspect_mpi(self.trace), (False, []))
        self.trace.write_text(f'openat(0, "{root}/lib/libmpi.so.40", 0) = 3\n')
        self.assertEqual(inspect_mpi(self.trace), (True, [root]))
        self.assertEqual(inspect_mpi(self.trace, 'none'), (False, []))
        self.trace.write_text('')
        job = self.root / 'job.sh'
        job.write_text('# mpirun ignored\nmpirun -n 2 ./solver\n')
        self.assertEqual(inspect_mpi(self.trace, command_file=job), (True, []))
        self.assertEqual(inspect_mpi(self.trace, 'on'), (True, []))

    def test_copies_complete_mpi_root_and_filters_rank_state(self):
        root = '/share/pkg.8/openmpi/4.1/install'
        self.trace.write_text(f'openat(0, "{root}/lib/libmpi.so.40", 0) = 3\n')
        plan = resolve_dependencies(self.trace)
        self.assertTrue(plan.mpi_enabled)
        self.assertEqual(plan.mpi_roots, [root])
        self.assertEqual(plan.copy_roots, [root])
        self.assertEqual(plan.blocked_libs, [])
        env = {'PATH': '/usr/bin', 'OMPI_COMM_WORLD_RANK': '7',
               'PMIX_RANK': '7', 'SLURM_JOB_ID': 'old', 'KEEP': 'yes'}
        definition = render_definition(plan, env, 'base.sif')
        self.assertIn(f'rsync -a {root}/', definition)
        self.assertIn(f'{root}/bin', definition)
        self.assertIn(f'{root}/lib', definition)
        self.assertIn('org.defcon.mpi enabled', definition)
        self.assertIn('export KEEP=yes', definition)
        self.assertNotIn('OMPI_COMM_WORLD_RANK=', definition)
        self.assertNotIn('PMIX_RANK=', definition)
        self.assertNotIn('SLURM_JOB_ID=', definition)
        self.assertEqual(env['OMPI_COMM_WORLD_RANK'], '7')
        self.assertFalse(resolve_dependencies(self.trace, mpi='none').mpi_enabled)

    def test_explicit_root_outside_module_layout(self):
        root = '/opt/site/mpi'
        plan = resolve_dependencies(self.trace, mpi='on', mpi_root=root)
        self.assertEqual(plan.copy_roots, [root])
        definition = render_definition(plan, {'PATH': '/usr/bin'}, 'base.sif')
        self.assertIn(f'rsync -a {root}/', definition)
        self.assertIn(f'{root}/bin', definition)
        self.assertIn(f'{root}/lib64', definition)
        self.assertTrue(resolve_dependencies(self.trace, mpi_root=root).mpi_enabled)
        with self.assertRaisesRegex(ValueError, 'absolute path'):
            resolve_dependencies(self.trace, mpi='on', mpi_root='relative/mpi')

    def test_stage1_forwards_mode_and_stage2_writes_launcher(self):
        wrapper = render_instrumented_job(
            parse_qsub('mpirun ./solver'), Path('run.sh'), 'out.def',
            'base.sif', Path('defcon.py'), mpi='on', mpi_root='/opt/site/mpi',
        )
        args = shlex.split(wrapper.splitlines()[-1])
        self.assertEqual(args[args.index('--mpi') + 1], 'on')
        self.assertEqual(args[args.index('--mpi-root') + 1], '/opt/site/mpi')
        env = self.root / 'env'
        env.write_bytes(b'PATH=/usr/bin\0')
        output = self.root / 'mpi.def'
        with contextlib.redirect_stdout(io.StringIO()):
            main(['stage2', '-t', str(self.trace), '-e', str(env), '-o', str(output),
                  '-s', 'base.sif', '--mpi', 'on', '--gpu', 'nvidia'])
        launcher = output.with_suffix('.run-container.sh')
        self.assertTrue(launcher.stat().st_mode & 0o111)
        self.assertEqual(output.read_text().count('%labels'), 1)
        subprocess.run(['sh', '-n', str(launcher)], check=True)
        fake_mpi = self.root / 'fake mpi'
        fake_mpi.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        fake_mpi.chmod(0o755)
        runtime = self.root / 'fake runtime'
        runtime.touch()
        vars = dict(os.environ, DEFCON_MPI_LAUNCHER=str(fake_mpi),
                    DEFCON_CONTAINER_RUNTIME=str(runtime))
        result = subprocess.run(
            ['sh', str(launcher), 'image with spaces.sif', '4', 'python', 'job with spaces.py', '$literal'],
            env=vars, text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.splitlines(),
                         ['-n', '4', str(runtime), 'exec', '--nv', 'image with spaces.sif',
                          'python', 'job with spaces.py', '$literal'])
        self.assertEqual(subprocess.run(['sh', str(launcher), 'image.sif', '0', 'x'],
                                        capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
