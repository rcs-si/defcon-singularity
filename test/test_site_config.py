"""Exercise site edits through the real TOML loader and dependency consumers."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from config import CONFIG_PATH, load_config


class SiteConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.text = CONFIG_PATH.read_text()

    def test_rejects_missing_keys_wrong_types_and_invalid_patterns(self):
        path = self.root / 'site.toml'
        cases = [
            ('DEFAULT_BASE_IMAGE =', '# DEFAULT_BASE_IMAGE =', 'DEFAULT_BASE_IMAGE'),
            ('IGNORE_PREFIXES = ["/proc", "/dev", "/sys", "/tmp", "/run"]',
             'IGNORE_PREFIXES = "/tmp"', 'IGNORE_PREFIXES'),
            ("(?P<name>[^/]+)", "(?:[^/]+)", 'requires named groups'),
            ("(?P<root>/usr/local/cuda", "(?P<root>[/usr/local/cuda", 'invalid NVIDIA_TOOLKIT_PATTERN'),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                path.write_text(self.text.replace(old, new))
                with self.assertRaisesRegex(ValueError, message):
                    load_config(path)

    def test_site_edits_apply_to_all_module_consumers_from_another_cwd(self):
        site = self.root / 'installation'
        site.mkdir()
        repository = CONFIG_PATH.parent
        shutil.copyfile(repository / 'config.py', site / 'config.py')
        text = self.text.replace('/share/pkg\\.[^/]+', '/software/stack/modules')
        text = text.replace('"/share/pkg"', '"/software/stack/modules"')
        text = text.replace('"/usr/local",', '"/work",')
        text = text.replace('"/tmp"', '"/work/ignored"')
        text = text.replace('"gcc"', '"vendor-cc"')
        text = text.replace('"cuda"', '"vendor-cuda"')
        text = text.replace('"openmpi"', '"vendor-mpi"')
        text = text.replace('/opt/rocm', '/opt/vendor-rocm')
        text = text.replace(load_config()['DEFAULT_BASE_IMAGE'], '/site/base.sif')
        (site / 'defcon.toml').write_text(text)
        base = '/software/stack/modules'
        python = f'{base}/python/3.12/install'
        compiler = f'{base}/vendor-cc/12/install/lib/libstdc++.so.6'
        cuda = f'{base}/vendor-cuda/12/install'
        mpi = f'{base}/vendor-mpi/5/install'
        trace = self.root / 'trace'
        trace.write_text(
            f'openat(AT_FDCWD, "{python}/lib/missing", O_RDONLY) = -1 ENOENT\n'
            f'openat(AT_FDCWD, "{compiler}", O_RDONLY) = 3\n'
            f'openat(AT_FDCWD, "{cuda}/lib/libcudart.so", O_RDONLY) = 3\n'
            f'openat(AT_FDCWD, "{mpi}/bin/mpirun", O_RDONLY) = 3\n'
            'openat(AT_FDCWD, "/opt/vendor-rocm-6/lib/librocblas.so", O_RDONLY) = 3\n'
            'openat(AT_FDCWD, "/work/data", O_RDONLY) = 3</work/data>\n'
            'openat(AT_FDCWD, "/work/missing", O_RDONLY) = -1 ENOENT\n'
            'openat(AT_FDCWD, "/work/ignored/cache", O_RDONLY) = 3\n'
            f'newfstatat(AT_FDCWD, "{base}", 0) = 0\n'
        )
        script = '''
import json
from pathlib import Path
import sys
from cli import build_parser
from dependency_resolver import resolve_dependencies
plan = resolve_dependencies(Path(sys.argv[1]))
print(json.dumps({
    'modules': plan.modules, 'module_roots': plan.module_roots,
    'blocked_libs': plan.blocked_libs, 'project_files': plan.project_files,
    'gpu_backends': plan.gpu_backends, 'gpu_roots': plan.gpu_roots,
    'mpi_roots': plan.mpi_roots,
    'image': build_parser().parse_args(['stage1', '-i', 'job']).singularity_image,
}))
'''
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(site), str(repository)]))
        result = subprocess.run(
            [sys.executable, '-c', script, str(trace)], cwd=self.root, env=env,
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        self.assertEqual(data['modules'], ['python/3.12'])
        self.assertEqual(data['module_roots'], [python, cuda, mpi])
        self.assertEqual(data['blocked_libs'], [
            '/opt/vendor-rocm-6/lib/librocblas.so', compiler, f'{cuda}/lib/libcudart.so',
        ])
        self.assertEqual(data['project_files'], ['/work/data'])
        self.assertEqual(data['gpu_backends'], ['amd', 'nvidia'])
        self.assertEqual(data['gpu_roots'], ['/opt/vendor-rocm-6', cuda])
        self.assertEqual(data['mpi_roots'], [mpi])
        self.assertEqual(data['image'], '/site/base.sif')


if __name__ == '__main__':
    unittest.main()
