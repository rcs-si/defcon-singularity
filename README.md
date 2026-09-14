# defcon_singularity - Definition Container generator

`defcon` analyses a job's runtime file dependencies via `strace` and produces a
Singularity `.def` file that reproduces the environment inside a container.

## Quickstart

You need to provide an input job script - `defcon` needs it to know which modules
to load, what command to run, and what scheduler directives to use (cores, time
limits, etc.). A minimal example (using the SGE scheduler):

```bash
#!/bin/bash -l
## This is file "my_job.qsub"
#$ -pe omp 4
#$ -l h_rt=1:00:00

module load python3/3.13.8
python3 myscript.py
```

Then run the pipeline:

```bash
# Stage 1: instrument your job script
python3 defcon.py stage1 -i my_job.qsub -o my_job_defcon.qsub

# Submit the instrumented job - it auto-calls Stage 2 when done
qsub my_job_defcon.qsub

# Stage 2: the container.def is ready
# build the container
singularity build --fakeroot container.sif my_job_defcon.def
# the container can now execute the original job script,
# so long as the hardware resources are available
singularity exec container.sif  ./my_job.qsub
```

## How it works

Stage 1:
```bash
python3 defcon.py stage1 -i input.qsub -o output.qsub
```

- Parses your qsub/sbatch script and extracts scheduler directives + commands
- Generates `output.run.sh` - the original commands, unchanged
- Generates `output.qsub` - an instrumented wrapper that:
  1. Captures `env -0` before any module loads
  2. Runs `output.run.sh` under `strace`
  3. Automatically calls `defcon stage2` to emit the `.def`

Stage 2 (DEFCON 2 to 1):

```bash
python3 defcon.py stage2 -t trace.out -e env.out --command-file job.run.sh -o container.def
```

- Parses the strace output to find all module install roots (`/share/pkg.*`)
  and project paths (`/projectnb`, `/project`, `/usr/local`)
- Writes a `Singularity` definition with `%files`, `%environment`, `%runscript`

## Tests

Sample test jobs are provided for Python, R, C, Bash, and Conda in `test/`.

To run the Conda smoke test, create its environment once on your cluster and
submit from the test directory (`-cwd` preserves this working directory):

```bash
cd test/Conda
module load miniconda
source "$(conda info --base)/etc/profile.d/conda.sh"
conda env create -f environment.yml
qsub conda_test.qsub
```

The job initializes Conda, activates `defcon-test`, and checks NumPy linear
algebra and pandas aggregation. To instrument it with DEFCON instead, run
from the same directory, replacing `/path/to/base.sif` with your base image:

```bash
python ../../defcon.py stage1 -i conda_test.qsub -o conda_test_defcon.qsub -s /path/to/base.sif
qsub conda_test_defcon.qsub
```

Conda support detects `conda-meta` directories above absolute paths accessed in
the trace. Stage 2 must run on a host where those installations are accessible.
It copies the detected base installation and environments at their original
absolute paths, including package metadata and activation hooks. This copies
whole directories and can make the image large, especially when the base holds
other environments or a package cache.

The generated environment adds Conda's `condabin` to `PATH` and the detected
environment parents to `CONDA_ENVS_PATH`, so the job can activate an environment
by name without relying on the host's `.condarc`. The job must explicitly
initialize Conda, as in `conda_test.qsub`; activation is replayed inside the
container. Keep the base image compatible with the cluster's OS and architecture.
Environments used only by relative paths or inside untraced jobs may require
additional capture. The working directory and job input files must also be
available when replaying the job.

Run the local regression tests with:

```bash
python3 -m unittest discover -s test -p 'test_*.py' -v
```

Run stage1 locally to generate instrumented scripts:

```bash
python3 defcon.py stage1 -i test/Python/pytest.qsub -o test/Python/test_job_defcon.qsub
python3 defcon.py stage1 -i test/R/rtest.qsub -o test/R/rtest_defcon.qsub
python3 defcon.py stage1 -i test/C/ctest.qsub -o test/C/ctest_defcon.qsub
python3 defcon.py stage1 -i test/Bash/bashtest.qsub -o test/Bash/bashtest_defcon.qsub
```

Submit generated jobs on your cluster (SGE example):

```bash
qsub test/Python/test_job_defcon.qsub
qsub test/R/rtest_defcon.qsub
qsub test/C/ctest_defcon.qsub
qsub test/Bash/bashtest_defcon.qsub
```

Expected artifacts after successful runs include:

- Generated `.def` files in each test directory
- Scheduler stdout/stderr logs under each `test/*/outputs/` directory

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
-c / --command   Command to embed in %runscript (optional)
--command-file   Script file to extract %runscript commands from (optional)
-o / --output    Output Singularity definition file
```

## Files

| File | Purpose |
|------|---------|
| `defcon.py` | Unified CLI - stage1 and stage2 |
| `strace_parser.py` | Parse strace output; extract module paths |
| `test/` | End-to-end examples and sample outputs |
