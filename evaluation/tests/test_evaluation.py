import dataclasses
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

from evaluation.design import covering_array, validation_sample, candidates, interactions
from evaluation.dependencies import completeness, saturation, aggregate, inventory
from evaluation.equivalence import compare, metamorphic
from evaluation.statistics import break_even, reliability, performance, tost
from evaluation.adaptive import select
from evaluation.runner import run, execute, run_metamorphic, artifact_metadata

REPO = Path(__file__).resolve().parents[2]


class DesignTests(unittest.TestCase):
    def test_variable_strength_feasible_coverage(self):
        spec = {'factors': {'a': [1, 2], 'b': ['x', 'y', 'z'], 'c': [0, 1], 'd': [1, 2]},
                'forbidden': [{'a': 2, 'b': 'z'}], 'high_risk_groups': [['a', 'b', 'c']]}
        result = covering_array(spec)
        universe = set().union(*(interactions(r, result['groups']) for r in candidates(spec)))
        observed = set().union(*(interactions(r, result['groups']) for r in result['configurations']))
        self.assertEqual(universe, observed)
        self.assertLessEqual(len(result['configurations']), len(candidates(spec)))

    def test_sampling_reproducible_weighted_with_replacement(self):
        spec = {'factors': {'a': [0, 1]}, 'weights': {'a': [0, 1]}}
        a = validation_sample(spec, 10, 42)
        self.assertEqual(a, validation_sample(spec, 10, 42))
        self.assertEqual(a['configurations'], [{'a': 1}]*10)
        with self.assertRaises(ValueError):
            candidates({'factors': {'a': [1, 1]}})

    def test_adaptive_budget_and_holdout(self):
        spec = {'factors': {'x': [1, 2]}, 'default_cost_seconds': 10}
        self.assertIsNone(select(spec, [], 1)['configuration'])
        self.assertEqual(select(spec, [{'configuration': {'x': 1}, 'success': True}], 10)['configuration'], {'x': 2})
        with self.assertRaises(ValueError):
            select(spec, [{'dataset': 'validation'}], 10)


class DependencyTests(unittest.TestCase):
    def test_sets_and_chao(self):
        result = completeness(['/a', '/a', '/ab'], ['/a', '/b'])
        self.assertEqual(result['recall'], .5)
        self.assertEqual(result['precision'], .5)
        result = saturation([['/a', '/b'], ['/a', '/c']])
        self.assertEqual(result['q1'], 2)
        self.assertEqual(result['q2'], 1)
        self.assertEqual(result['chao2_bias_corrected'], 3.25)
        self.assertIsNone(saturation([['/a']])['chao2_bias_corrected'])

    def test_independent_inventory_filters_failure_and_write(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'trace'
            trace.write_text('openat(AT_FDCWD, "/a", O_RDONLY) = 3\n'
                             'openat(AT_FDCWD, "/missing", O_RDONLY) = -1 ENOENT\n'
                             'openat(AT_FDCWD, "/output", O_WRONLY|O_CREAT) = 4\n')
            report = inventory([trace])
            self.assertEqual(set(report['paths']), {'/a'})
            self.assertFalse(report['paths']['/a'][0]['required'])

    def test_aggregation_matches_single_trace_and_unions_branches(self):
        from dependency_resolver import resolve_dependencies
        with tempfile.TemporaryDirectory() as directory:
            a, b = [Path(directory) / name for name in ('a', 'b')]
            a.write_text('openat(AT_FDCWD, "/project/example/a", O_RDONLY) = 3\n')
            b.write_text('openat(AT_FDCWD, "/project/example/b", O_RDONLY) = 3\n')
            self.assertEqual(dataclasses.asdict(aggregate([a])), dataclasses.asdict(resolve_dependencies(a)))
            self.assertEqual(aggregate([a, b]).project_files, ['/project/example/a', '/project/example/b'])
            self.assertEqual(aggregate([a, b], exclude_paths=['/project/example/b']).project_files,
                             ['/project/example/a'])


class OracleTests(unittest.TestCase):
    def test_nonfinite_shapes_and_tolerance(self):
        self.assertFalse(compare([math.nan], [math.nan])['equivalent'])
        self.assertFalse(compare([[1, 2]], [1, 2])['equivalent'])
        self.assertFalse(compare([], [])['equivalent'])
        self.assertTrue(compare([100.0], [100.1], rtol=.002)['equivalent'])
        self.assertFalse(compare([100.0], [100.1], atol=.01)['equivalent'])

    def test_relations(self):
        self.assertTrue(metamorphic([1, 2], [2, 4], 'scale', scale=2)['equivalent'])
        self.assertTrue(metamorphic([1, 2], [2, 1], 'permutation', permutation=[1, 0])['equivalent'])
        self.assertTrue(metamorphic(4, [1, 3], 'split_sum')['equivalent'])
        self.assertFalse(metamorphic([1, 2], [2, 5], 'scale', scale=2)['equivalent'])


class StatisticsTests(unittest.TestCase):
    def test_reliability_requires_validated_independent_draws(self):
        rows = [{'dataset': 'validation', 'sample_id': i, 'supported': True, 'success': True} for i in range(10)]
        report = reliability(rows)
        self.assertEqual(report['estimate'], 1)
        self.assertLess(report['ci'][0], 1)
        with self.assertRaises(ValueError):
            reliability(rows+rows)
        with self.assertRaises(ValueError):
            reliability([dict(rows[0], dataset='coverage')])
        with self.assertRaises(ValueError):
            reliability([dict(rows[0], success=None)])

    def test_break_even_all_slopes(self):
        self.assertEqual(break_even(10, 10, 1, 0, 3)['minimum_reuses'], 10)
        self.assertIsNone(break_even(10, 10, 3, 0, 1)['minimum_reuses'])
        self.assertEqual(break_even(0, 0, 3, 10, 1)['maximum_reuses'], 5)
        self.assertTrue(break_even(0, 0, 1, 0, 1)['lasting'])

    @unittest.skipUnless(importlib.util.find_spec('scipy'), 'optional scipy unavailable')
    def test_tost_and_log_ratios(self):
        self.assertTrue(tost([-.01, 0, .01, .02], -.1, .1)['equivalent'])
        self.assertFalse(tost([1, 2, 3], -.1, .1)['equivalent'])
        self.assertIsNone(tost([0, 0], -.1, .1)['equivalent'])
        self.assertAlmostEqual(performance([[1, 2], [2, 4]])['geometric_mean_ratio'], 2)


class RunnerTests(unittest.TestCase):
    def test_artifact_hash_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'trace'
            path.write_bytes(b'abc')
            report = artifact_metadata([path, path.with_name('missing')])
            self.assertEqual(report[0]['bytes'], 3)
            self.assertEqual(report[0]['sha256'], 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
            self.assertIn('unavailable', report[1])

    def test_preflight_only_exit_77_excludes(self):
        spec = json.loads((REPO/'evaluation/examples/local.json').read_text())
        design = {'dataset': 'validation', 'configurations': [{'size': 1, 'optional': 'no', 'threads': 1}]}
        with tempfile.TemporaryDirectory() as directory:
            for code in (77, 1):
                spec['preflight'] = [sys.executable, '-c', f'raise SystemExit({code})']
                output = Path(directory)/str(code)
                run(spec, design, output)
                outcome = json.loads((output/'outcomes.json').read_text())[0]
                self.assertEqual(outcome['supported'], code != 77)
                self.assertFalse(outcome['success'])

    def test_local_run_and_metamorphic(self):
        spec = json.loads((REPO/'evaluation/examples/local.json').read_text())
        design = {'dataset': 'validation', 'configurations': [{'size': 4, 'optional': 'no', 'threads': 1}]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'run'
            run(spec, design, output)
            outcomes = json.loads((output/'outcomes.json').read_text())
            self.assertTrue(outcomes[0]['success'])
            self.assertEqual(len(json.loads((output/'records.json').read_text())), 4)
            with self.assertRaises(FileExistsError):
                run(spec, design, output)
            mr = json.loads((REPO/'evaluation/examples/metamorphic.json').read_text())
            self.assertTrue(run_metamorphic(mr, Path(directory)/'mr')['container']['equivalent'])

    def test_timeout_and_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            report = execute([sys.executable, '-c', 'import time; time.sleep(10)'], Path(directory)/'timeout',
                             os.environ.copy(), .1, REPO)
            self.assertEqual(report['status'], 'timeout')
            report = execute(['/nonexistent/command'], Path(directory)/'missing', os.environ.copy(), 1, REPO)
            self.assertEqual(report['status'], 'infrastructure_failure')

    def test_no_oracle_and_wrong_output_are_not_success(self):
        spec = json.loads((REPO/'evaluation/examples/local.json').read_text())
        spec['blocks'] = 1
        spec['modes']['container']['argv'] = [sys.executable, '-c', 'print(123)']
        design = {'dataset': 'coverage', 'configurations': [{'size': 1, 'optional': 'no', 'threads': 1}]}
        with tempfile.TemporaryDirectory() as directory:
            run(spec, design, Path(directory)/'wrong')
            outcomes = json.loads((Path(directory)/'wrong/outcomes.json').read_text())
            self.assertFalse(outcomes[0]['success'])
            del spec['oracle']
            run(spec, design, Path(directory)/'unchecked')
            self.assertIsNone(json.loads((Path(directory)/'unchecked/outcomes.json').read_text())[0]['success'])


if __name__ == '__main__':
    unittest.main()
