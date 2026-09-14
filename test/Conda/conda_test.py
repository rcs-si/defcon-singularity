"""Exercise Python and compiled dependencies from the active Conda environment."""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix or Path(prefix).resolve() != Path(sys.prefix).resolve():
        raise RuntimeError("Python must run from the activated Conda environment")

    print(f"Conda environment: {os.environ.get('CONDA_DEFAULT_ENV')}")
    print(f"Python: {sys.executable}")
    print(f"NumPy {np.__version__}: {np.__file__}")
    print(f"pandas {pd.__version__}: {pd.__file__}")

    matrix = np.array([[3.0, 1.0], [1.0, 2.0]])
    solution = np.linalg.solve(matrix, np.array([9.0, 8.0]))
    np.testing.assert_allclose(solution, [2.0, 3.0])

    frame = pd.DataFrame({"group": ["a", "a", "b"], "value": [1, 2, 4]})
    totals = frame.groupby("group")["value"].sum().to_dict()
    if totals != {"a": 3, "b": 4}:
        raise RuntimeError(f"Unexpected pandas result: {totals}")

    print("Conda smoke test passed")


if __name__ == "__main__":
    main()
