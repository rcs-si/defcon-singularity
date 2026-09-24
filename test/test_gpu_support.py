"""GPU capture and launch regression tests without GPU hardware."""

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
from environments.gpu import inspect_trace, render_launcher
from tracer import render_instrumented_job
from job_parser import parse_qsub


class GPUSupportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.trace = self.root / 'trace'
        self.trace.write_text('')

    def accesses(self, *paths):
        self.trace.write_text(''.join(f'openat(0, "{path}", 0) = 3\n' for path in paths))

    def test_detects_nvidia_and_amd_but_ignores_failed_probes(self):
        self.accesses('/dev/nvidia0', '/dev/kfd')
        self.assertEqual(inspect_trace(self.trace), (['amd', 'nvidia'], []))
        self.trace.write_text('openat(0, "/dev/nvidia0", 0) = -1 ENOENT\n')
        self.assertEqual(inspect_trace(self.trace), ([], []))
        self.assertEqual(inspect_trace(self.trace, 'amd'), (['amd'], []))
        self.assertEqual(inspect_trace(self.trace, 'none'), ([], []))
        with self.assertRaises(ValueError):
            inspect_trace(self.trace, 'invalid')

    def test_application_library_alone_detects_backend(self):
        for path, backend in [('/usr/lib/libcufft.so.11', 'nvidia'),
                              ('/usr/lib/libMIOpen.so.1', 'amd')]:
            with self.subTest(path=path):
                self.accesses(path)
                plan = resolve_dependencies(self.trace)
                self.assertEqual(plan.gpu_backends, [backend])
                self.assertIn(path, plan.blocked_libs)

    def test_nvidia_toolkit_and_application_libraries_exclude_host_driver(self):
        toolkit = '/share/pkg.8/cuda/12.4/install'
        self.accesses(toolkit + '/lib64/libcudart.so.12',
                      toolkit + '/lib64/stubs/libcuda.so',
                      '/usr/lib/libcublas.so.12', '/dev/nvidia0')
        plan = resolve_dependencies(self.trace)
        self.assertEqual(plan.gpu_backends, ['nvidia'])
        self.assertEqual(plan.gpu_roots, [toolkit])
        self.assertIn(toolkit, plan.copy_roots)
        self.assertIn('/usr/lib/libcublas.so.12', plan.blocked_libs)
        self.assertNotIn(toolkit + '/lib64/stubs/libcuda.so', plan.blocked_libs)
        self.assertNotIn('/dev/nvidia0', plan.project_files)
        definition = render_definition(plan, {}, 'base.sif')
        self.assertIn("--exclude='libcuda.so*'", definition)
        self.assertIn('singularity exec --nv', definition)
        self.assertIn('org.defcon.gpu nvidia', definition)

    def test_amd_toolkit_and_exclusions(self):
        self.accesses('/opt/rocm-6.3/lib/librocblas.so.4', '/dev/kfd')
        plan = resolve_dependencies(self.trace, exclude_paths=['/opt/rocm-6.3'])
        self.assertEqual(plan.gpu_roots, [])
        self.assertEqual(plan.blocked_libs, [])
        plan = resolve_dependencies(self.trace)
        self.assertEqual(plan.copy_roots, ['/opt/rocm-6.3'])
        definition = render_definition(plan, {}, 'base.sif')
        self.assertIn('/opt/rocm-6.3/bin', definition)
        self.assertIn('/opt/rocm-6.3/lib', definition)
        self.assertIn('singularity exec --rocm', definition)

    def test_visibility_comes_from_current_allocation_and_drivers_take_precedence(self):
        plan = resolve_dependencies(self.trace, gpu='nvidia')
        env = {'CUDA_VISIBLE_DEVICES': '7', 'ROCR_VISIBLE_DEVICES': '3',
               'APPTAINERENV_CUDA_VISIBLE_DEVICES': '5', 'LD_LIBRARY_PATH': '/old/lib'}
        definition = render_definition(plan, env, 'base.sif')
        self.assertNotIn('VISIBLE_DEVICES=', definition)
        self.assertIn('export LD_LIBRARY_PATH=/.singularity.d/libs:/old/lib', definition)
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '7')

    def test_cpu_default_and_disabled_mode_do_not_add_gpu_runtime(self):
        self.assertEqual(resolve_dependencies(self.trace).gpu_backends, [])
        self.accesses('/dev/nvidia0')
        plan = resolve_dependencies(self.trace, gpu='none')
        self.assertEqual(plan.gpu_backends, [])
        self.assertNotIn('org.defcon.gpu', render_definition(plan, {}, 'base.sif'))

    def test_launcher_passes_exact_arguments_and_live_visibility(self):
        launcher = self.root / 'launch.sh'
        launcher.write_text(render_launcher(['nvidia']))
        runtime = self.root / 'fake runtime'
        runtime.write_text('#!/bin/sh\nprintf "%s\\n" "$CUDA_VISIBLE_DEVICES" "$@"\n')
        runtime.chmod(0o755)
        env = dict(os.environ, DEFCON_CONTAINER_RUNTIME=str(runtime), CUDA_VISIBLE_DEVICES='2')
        result = subprocess.run(['sh', str(launcher), 'image with spaces.sif', 'python', 'job with spaces.py', '$literal'], env=env, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines(), ['2', 'exec', '--nv', 'image with spaces.sif', 'python', 'job with spaces.py', '$literal'])
        result = subprocess.run(['sh', str(launcher)], capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_stage1_forwards_gpu_mode(self):
        wrapper = render_instrumented_job(parse_qsub('echo hello'), Path('run.sh'), 'out.def', 'base.sif', Path('defcon.py'), gpu='amd')
        args = shlex.split(wrapper.splitlines()[-1])
        self.assertEqual(args[args.index('--gpu') + 1], 'amd')

    def test_stage2_writes_executable_launcher(self):
        env = self.root / 'env'
        env.write_bytes(b'PATH=/usr/bin\0')
        output = self.root / 'gpu.def'
        with contextlib.redirect_stdout(io.StringIO()):
            main(['stage2', '-t', str(self.trace), '-e', str(env), '-o', str(output), '-s', 'base.sif', '--gpu', 'amd'])
        launcher = output.with_suffix('.run-container.sh')
        self.assertTrue(launcher.stat().st_mode & 0o111)
        self.assertIn('exec --rocm', launcher.read_text())
        subprocess.run(['sh', '-n', str(launcher)], check=True)


if __name__ == '__main__':
    unittest.main()
