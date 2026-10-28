import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from evaluation.diagnostics import classify, localize, ablate


class DiagnosticsTests(unittest.TestCase):
    def test_diagnosis_requires_evidence(self):
        rows = [{'sample_id': 0, 'success': False}]
        with self.assertRaises(ValueError):
            classify(rows, [{'sample_id': 0, 'category': 'missing_dependency'}])
        result = classify(rows, [{'sample_id': 0, 'category': 'missing_dependency', 'evidence': 'loader log'}])
        self.assertEqual(result[0]['diagnosis']['category'], 'missing_dependency')
        self.assertNotIn('diagnosis', rows[0])

    def test_first_file_divergence(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory)/'a', Path(directory)/'b'
            a.write_text('[1,2]'); b.write_text('[1,3]')
            report = localize([{'native': str(a), 'container': str(a)},
                               {'native': str(a), 'container': str(b), 'numeric': True, 'atol': .1, 'rtol': 0}])
            self.assertEqual(report['first_divergence'], 1)

    def test_ablation_masks_container_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'dependency'
            source.write_text('original')
            calls = []
            def fake_execute(argv, destination, *args, **kwargs):
                calls.append(argv)
                destination.mkdir()
                (destination/'stdout.txt').write_text('{"result":1}')
                return {'status': 'completed', 'directory': str(destination)}
            spec = {'image': '/example.sif', 'argv': ['/example'], 'oracle': {'field': 'result', 'atol': 0, 'rtol': 0},
                    'targets': [{'path': str(source), 'kind': 'file'}]}
            with patch('evaluation.diagnostics.execute', fake_execute):
                report = ablate(spec, Path(directory)/'output')
            self.assertEqual(source.read_text(), 'original')
            self.assertIn('--bind', calls[1])
            self.assertTrue(report[1]['comparison']['equivalent'])
