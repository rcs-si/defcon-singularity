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

Both stages use the site base image configured as `DEFAULT_BASE_IMAGE` in
`config.py` when `-s/--singularity-image` is omitted. Pass `-s BASE.SIF` to
override it for one invocation.

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
| `defcon.py` | Compatible executable entry point and legacy stage imports |
| `cli.py` | Argument parsing, stage orchestration, file I/O, and status output |
| `job_parser.py` | Scheduler and job metadata extraction |
| `tracer.py` | Instrumented job wrapper rendering |
| `dependency_resolver.py` | Dependency selection, overrides, and `DependencyPlan` |
| `definition_generator.py` | Container environment preparation and definition rendering |
| `environments/modules.py` | Module installation recognition and runtime search paths |
| `environments/conda.py` | Conda activation environment preparation |
| `environments/__init__.py` | Environment dump loading and host-variable filtering |
| `path_utils.py` | Shared lexical path and override rules |
| `strace_parser.py` | Parse strace output; extract module paths |
| `test/` | End-to-end examples and sample outputs |

## Testing and debugging individual stages

The CLI remains `python3 defcon.py stage1 ...` / `stage2 ...`. Keep the Python
modules and `environments/` directory alongside the entry point when deploying.

Stage 2 exposes an intermediate plan so dependency selection can be inspected
before generating a definition:

```python
from pathlib import Path
from dependency_resolver import resolve_dependencies
from environments import load_env_vars
from definition_generator import render_definition

plan = resolve_dependencies(
    Path("trace.out"), include_paths=["/project/extra"],
    exclude_paths=["/project/cache"],
)
print(plan.copy_roots, plan.project_files, plan.blocked_libs)
text = render_definition(plan, load_env_vars(Path("env.out")), "base.sif")
Path("container.def").write_text(text)
```

`job_parser.parse_qsub()` and `tracer.render_instrumented_job()` can likewise be
called without submitting a job. Renderers return text; the CLI writes files.
Environment preparation returns a new mapping, preserving the input snapshot.
The local tests cover these APIs and the existing Conda integration behavior
without requiring a scheduler, Conda, strace, or Singularity installation.

## GPU support (NVIDIA CUDA and AMD ROCm)

Both stages accept `--gpu auto|nvidia|amd|none` (default: `auto`). Automatic
recognition uses successful GPU device, library, or toolkit accesses in the
trace. Use an explicit backend when detection is inconclusive; `none` retains
the previous capture behavior without GPU-specific processing.

```bash
python3 defcon.py stage1 -i gpu_job.qsub -o gpu_capture.qsub -s base.sif --gpu nvidia
qsub gpu_capture.qsub  # or sbatch for a Slurm job
singularity build --fakeroot gpu.sif gpu_capture.def
# Run within a NEW scheduler GPU allocation:
./gpu_capture.run-container.sh gpu.sif bash gpu_job.qsub
```

The input job must request GPUs through your site's scheduler directives and
initialize its GPU framework. Stage 1 preserves those directives and forwards
the GPU option to stage 2. It does not request GPU resources for you.

When stage 2 identifies a GPU backend, it also writes an executable
`<definition-stem>.run-container.sh`. This launcher accepts `IMAGE COMMAND [ARGS...]`
and selects `--nv` for NVIDIA or `--rocm` for AMD. Set
`DEFCON_CONTAINER_RUNTIME=apptainer` to use Apptainer. You can also run directly:

```bash
singularity exec --nv gpu.sif bash gpu_job.qsub
# AMD:
apptainer exec --rocm gpu.sif bash gpu_job.qsub
```

GPU support captures recognized CUDA/ROCm toolkit roots (`/usr/local/cuda*`,
`/opt/rocm*`, and CUDA/ROCm module install roots), plus successfully accessed
GPU application libraries. Conda environments remain supported. `--inc` and
`--exc` still control dependency selection. Host driver libraries are omitted
from selected files and excluded from directory copies; the runtime supplies
matching host libraries. Generated definitions prioritize `/.singularity.d/libs`
and do not embed capture-job GPU visibility variables, allowing the current
allocation's settings to apply. The definition includes GPU runtime metadata
and help text, but a definition alone cannot enable device passthrough.

The execution node needs supported GPUs and drivers, and a GPU-enabled framework
compatible with those drivers in the image. This feature does not install
PyTorch, CUDA, ROCm, or host drivers. Automatic detection is heuristic and does
not prove successful GPU computation; relative paths and unrecognized/custom
toolkit layouts may require `--gpu` and `--inc`. Toolkit copies can be large.
The runtime behavior follows the [Apptainer GPU documentation](https://apptainer.org/docs/user/main/gpu.html).

For a hardware smoke test, run `python test/GPU/gpu_smoke.py` in your allocated
GPU environment, then run the same command inside the generated container.
It requires an existing CUDA or ROCm build of PyTorch and verifies an actual
GPU matrix multiplication. The ordinary unit tests use synthetic traces and a
fake container runtime, so they run without GPU hardware.

## MPI support

Both stages accept `--mpi auto|on|none` (default: `auto`). Auto mode recognizes
successful MPI library or launcher accesses in the trace, MPI module installs
under `/share/pkg.*`, and `mpirun`, `mpiexec`, or `srun` commands in the captured job
script. Use `--mpi on` when a remote rank is absent from the local trace. Use
`--mpi-root /absolute/mpi/prefix` when the MPI installation is outside the
recognized module layout or absent from the trace. Stage 1 passes these options
to stage 2.

When MPI is detected, stage 2 copies the full traced MPI module installation,
including its transport plugins, and writes `<definition-stem>.run-container.sh`.
It leaves captured rank and Slurm variables out of the definition so each rank
receives values from the current allocation. Build the image and launch the
application executable directly from within a new scheduler allocation:

```bash
python3 defcon.py stage1 -i mpi_job.qsub -o mpi_job_defcon.qsub -s base.sif --mpi on
qsub mpi_job_defcon.qsub
singularity build --fakeroot mpi_job.sif mpi_job_defcon.def
./mpi_job_defcon.run-container.sh mpi_job.sif 4 ./solver input.dat
```

The launcher calls host `mpirun -n 4 singularity exec mpi_job.sif ./solver input.dat`.
Set `DEFCON_MPI_LAUNCHER=srun` on clusters that use Slurm's `srun`, or
`DEFCON_CONTAINER_RUNTIME=apptainer` for Apptainer. If GPUs were also detected,
the same launcher adds `--nv` or `--rocm`. Use the application command in the
launcher; do not pass a job script that already calls `mpirun`.

The host launcher and the MPI installation inside the image must be compatible
at your site, and the MPI installation used for capture must be available while
building the image. Multi-node execution requires the site's
normal scheduler allocation, networking, and container availability on every
node. The local tests validate generated commands and definitions; they do not
run an MPI cluster job.
