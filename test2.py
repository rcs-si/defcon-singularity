import numpy as np
import pandas as pd
import scipy.linalg as la

# NumPy: matrix multiply (hits MKL/BLAS)
A = np.random.rand(100, 100)
B = np.random.rand(100, 100)
C = A @ B
print(f"Matrix multiply OK: shape={C.shape}, mean={C.mean():.4f}")

# NumPy: FFT (hits pocketfft)
signal = np.sin(np.linspace(0, 2 * np.pi, 1024))
spectrum = np.fft.fft(signal)
print(f"FFT OK: {len(spectrum)} bins, peak at bin {np.argmax(np.abs(spectrum))}")

# Pandas: groupby aggregation
df = pd.DataFrame({
    "group": np.repeat(["a", "b", "c"], 1000),
    "value": np.random.randn(3000),
})
summary = df.groupby("group")["value"].agg(["mean", "std", "count"])
print(f"Groupby OK:\n{summary}")

# Pandas: datetime index + resampling
dates = pd.date_range("2024-01-01", periods=365, freq="D")
ts = pd.Series(np.random.randn(365), index=dates)
monthly = ts.resample("ME").mean()
print(f"Resample OK: {len(monthly)} months, mean={monthly.mean():.4f}")

# SciPy: solve a linear system (hits LAPACK independently of numpy)
M = np.random.rand(200, 200)
M = M @ M.T + np.eye(200)  # make positive definite
b = np.random.rand(200)
x = la.solve(M, b)
residual = np.linalg.norm(M @ x - b)
print(f"Linear solve OK: residual={residual:.2e}")

print("\nAll tests passed.")