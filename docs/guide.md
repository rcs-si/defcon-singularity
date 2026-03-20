# defcon User Guide

## Install

```bash
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

## Quickstart

You need to provide an input job script — defcon needs it to know which modules
to load, what command to run, and what scheduler directives to use (cores, time
limits, etc.). A minimal example:

```bash
#!/bin/bash -l
#$ -pe omp 4
#$ -l h_rt=1:00:00

module load python3/3.13.8
python3 myscript.py
```

Then run the pipeline:

```bash
# Stage 1: instrument your job script
defcon stage1 -i my_job.qsub -o my_job_defcon.qsub

# Submit the instrumented job — it auto-calls stage2 when done
qsub my_job_defcon.qsub

# DEFCON 1: container.def is ready
singularity build --fakeroot container.sif my_job_defcon.def
singularity run container.sif
```

## How it works

Stage 1 (DEFCON 3 to 2):

```bash
defcon stage1 -i input.qsub -o output.qsub
```

- Parses your qsub/sbatch script and extracts scheduler directives + commands
- Generates output.run.sh — the original commands, unchanged
- Generates output.qsub — an instrumented wrapper that:
  1. Captures env -0 before any module loads
  2. Runs output.run.sh under strace
  3. Automatically calls defcon stage2 to emit the .def

Stage 2 (DEFCON 2 to 1):

```bash
defcon stage2 -t trace.out -e env.out --command-file job.run.sh -o container.def
```

- Parses the strace output to find all module install roots (`/share/pkg.*`)
  and project paths (`/projectnb`, `/project`, `/usr/local`)
- Writes a Singularity definition with `%files`, `%environment`, `%runscript`

## Options

### stage1

```text
-i / --input     Input job script (.qsub or .sh)
-o / --output    Output instrumented script (default: <input>_defcon.qsub)
--def-out        Where stage2 writes the .def (default: <o>.def)
--scheduler      sge | slurm  (auto-detected from directives)
```

### stage2

```text
-t / --trace     strace output file
-e / --env       env -0 dump file
--command-file   Script file to extract run commands from (recommended)
-c / --command   Command to embed in %runscript (legacy fallback)
-o / --output    Output Singularity definition file
```

## Files

| File | Purpose |
|------|---------|
| `src/defcon_singularity/cli.py` | Unified CLI — stage1 and stage2 |
| `src/defcon_singularity/strace_parser.py` | Parse strace output; extract module paths |
| `defcon.py` | Backward-compatible script wrapper |

## Packaging and release

Build artifacts:

```bash
python -m build
```

Run tests:

```bash
pytest
```

Check distribution metadata before upload:

```bash
twine check dist/*
```
