"""CUDA/CPU matrix multiplication or inference; no silent GPU fallback."""
import argparse
import json
import torch

p = argparse.ArgumentParser()
p.add_argument('--size', type=int, default=32)
p.add_argument('--batch', type=int, default=8)
p.add_argument('--scale', type=float, default=1)
p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
p.add_argument('--kind', choices=['matmul', 'inference'], default='matmul')
a = p.parse_args()
if a.device == 'cuda' and not torch.cuda.is_available():
    raise RuntimeError('Requested CUDA device unavailable')
torch.manual_seed(42)
torch.use_deterministic_algorithms(True)
x = torch.randn(a.batch, a.size, dtype=torch.float64).to(a.device) * a.scale
w = torch.randn(a.size, a.size, dtype=torch.float64).to(a.device)
with torch.no_grad():
    result = x @ w
    if a.kind == 'inference':
        result = torch.relu(result)
if a.device == 'cuda':
    torch.cuda.synchronize()
print(json.dumps({'result': result.cpu().tolist(), 'device': str(result.device),
                  'torch': torch.__version__, 'cuda': torch.version.cuda}))
