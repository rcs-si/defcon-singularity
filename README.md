# defcon_singularity - Definition Container generator

defcon analyzes a job's runtime file dependencies via `strace` and produces a
Singularity `.def` file that reproduces the environment inside a container.

## Documentation

- User guide: [`docs/guide.md`](docs/guide.md)
- Examples (Python, R, C, Bash): [`docs/examples/`](docs/examples/)

## Example qsubs

These moved from the old `test/` location and are now available at `docs/examples/`:

- `docs/examples/Python/pytest.qsub`
- `docs/examples/R/rtest.qsub`
- `docs/examples/C/ctest.qsub`
- `docs/examples/Bash/bashtest.qsub`

## Install

```bash
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```
