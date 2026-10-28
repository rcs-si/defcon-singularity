"""Deterministic NumPy/SciPy linear algebra with an optional compiled solver path."""
import argparse
import json
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--size', type=int, default=32)
p.add_argument('--scale', type=float, default=1)
p.add_argument('--solver', choices=['numpy', 'scipy'], default='numpy')
a = p.parse_args()
rng = np.random.default_rng(42)
x = rng.normal(size=(a.size, a.size))
matrix = x.T @ x + a.size * np.eye(a.size)
b = rng.normal(size=a.size) * a.scale
if a.solver == 'scipy':
    from scipy.linalg import solve
    result = solve(matrix, b, assume_a='pos')
else:
    result = np.linalg.solve(matrix, b)
print(json.dumps({'result': result.tolist(), 'residual': float(np.linalg.norm(matrix @ result-b))}))
