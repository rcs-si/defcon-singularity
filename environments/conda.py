"""Prepare Conda activation from detected installation prefixes."""

from pathlib import Path


def prepare_environment(env_vars, conda_roots):
    """Return a fresh environment and Conda entry points; never mutate input."""
    result = dict(env_vars)
    if conda_roots:
        # Replay activation without inheriting an unrelated host environment.
        result = {k: v for k, v in result.items()
                  if not k.startswith("CONDA_") and k not in {
                      "_CE_CONDA", "_CE_M", "_CONDA_EXE", "_CONDA_ROOT",
                  }}
        result["CONDA_ENVS_PATH"] = ":".join(sorted({
            str(Path(root).parent) for root in conda_roots
            if not (Path(root) / "etc/profile.d/conda.sh").is_file()
        }))
    bins = [str(Path(root) / "condabin") for root in conda_roots
            if (Path(root) / "etc/profile.d/conda.sh").is_file()]
    return result, bins
