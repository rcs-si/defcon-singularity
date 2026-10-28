"""Optional-package tests use synthetic data, not simulated research findings."""
import importlib.util
import math
import random
import unittest
from evaluation.adaptive import select
from evaluation.models import fit


@unittest.skipUnless(importlib.util.find_spec('sklearn'), 'optional sklearn unavailable')
class GPTests(unittest.TestCase):
    def test_entropy_selects_unseen_affordable_candidate(self):
        spec = {'factors': {'size': [1, 2, 3, 4], 'branch': ['a', 'b']}}
        history = [{'configuration': {'size': 1, 'branch': 'a'}, 'success': True},
                   {'configuration': {'size': 4, 'branch': 'b'}, 'success': False}]
        result = select(spec, history, 1)
        self.assertTrue(0 <= result['predicted_failure'] <= 1)
        self.assertNotIn(result['configuration'], [h['configuration'] for h in history])
        self.assertIn('entropy', result['acquisition'])


@unittest.skipUnless(importlib.util.find_spec('statsmodels'), 'optional statsmodels unavailable')
class ModelTests(unittest.TestCase):
    def test_logistic_fit(self):
        rng = random.Random(31)
        rows = [{'workload': str(w), 'x': i % 2,
                 'success': int(rng.random() < .2+.3*(i % 2)+.05*w)}
                for w in range(4) for i in range(40)]
        result = fit(rows, 'success ~ x')
        self.assertIn('variational', result['method'])
        self.assertIn('workload', result['summary'])

    def test_performance_fit(self):
        rng = random.Random(91)
        rows = []
        for node in range(8):
            node_effect = rng.gauss(0, .2)
            for workload in range(4):
                work_effect = rng.gauss(0, .1)
                for i in range(16):
                    rows.append({'node': str(node), 'workload': str(workload), 'condition': i % 2,
                                 'log_ratio': node_effect + work_effect + .3*(i % 2) + rng.gauss(0, .1)})
        result = fit(rows, 'log_ratio ~ condition', 'performance')
        self.assertTrue(result['converged'])
        self.assertIn('condition', result['summary'])
