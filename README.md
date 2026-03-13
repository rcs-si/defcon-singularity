# defcon — Definition Container generator

Analyses a job's runtime file dependencies via `strace` and produces a
Singularity `.def` file that reproduces the environment inside a container.

Stages count **down to DEFCON 1** (container ready), like the real threat-level scale.

## Quickstart

You need to provide an input job script — defcon needs it to know which modules
to load, what command to run, and what scheduler directives to use (cores, time
limits, etc.). A minimal example:

```
#!/bin/bash -l
#$ -pe omp 4
#$ -l h_rt=1:00:00

module load python3/3.13.8
python3 myscript.py
```

Then run the pipeline:

```bash
# Stage 1: instrument your job script
python3 defcon.py stage1 -i my_job.qsub -o my_job_defcon.qsub

# Submit the instrumented job — it auto-calls stage2 when done
qsub my_job_defcon.qsub

# DEFCON 1: container.def is ready
singularity build --fakeroot container.sif my_job_defcon.def
singularity run container.sif
```

## How it works

Stage 1 (DEFCON 3 to 2):  defcon stage1 -i input.qsub -o output.qsub

- Parses your qsub/sbatch script and extracts scheduler directives + commands
- Generates output.run.sh  — the original commands, unchanged
- Generates output.qsub   — an instrumented wrapper that:
  1. Captures env -0 before any module loads
  2. Runs output.run.sh under strace
  3. Automatically calls defcon stage2 to emit the .def

```
Stage 2 (DEFCON 2→1):  defcon stage2 -t trace.out -e env.out --command-file job.run.sh -o container.def
```
- Parses the strace output to find all module install roots (`/share/pkg.*`)
  and project paths (`/projectnb`, `/project`, `/usr/local`)
- Writes a `Singularity` definition with `%files`, `%environment`, `%runscript`

## Options

### stage1
```
-i / --input     Input job script (.qsub or .sh)
-o / --output    Output instrumented script (default: <input>_defcon.qsub)
--def-out        Where stage2 writes the .def (default: <o>.def)
--scheduler      sge | slurm  (auto-detected from directives)
```

### stage2
```
-t / --trace     strace output file
-e / --env       env -0 dump file
--command-file   Script file to extract run commands from (recommended)
-c / --command   Command to embed in %runscript (legacy fallback)
-o / --output    Output Singularity definition file
```

## Files
| File | Purpose |
|------|---------|
| `defcon.py` | Unified CLI — stage1 and stage2 |
| `strace_parser.py` | Parse strace output; extract module paths |
| `test.py` | Sample workload (`pandas` DataFrame) |
