"""Run with a CUDA or ROCm build of PyTorch on an allocated GPU node."""

import torch


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("No GPU available: check allocation, runtime flag, and PyTorch build")
    # PyTorch exposes both NVIDIA CUDA and AMD ROCm through torch.cuda.
    values = torch.arange(16, dtype=torch.float32, device="cuda").reshape(4, 4)
    result = values @ torch.eye(4, device="cuda")
    torch.cuda.synchronize()
    torch.testing.assert_close(result.cpu(), values.cpu())
    print(f"GPU computation passed: {torch.cuda.get_device_name(0)}")


if __name__ == "__main__":
    main()
