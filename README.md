# defcon — DEFinition CONtainer generator

Analyses a job's runtime file dependencies via `strace` and produces a
Singularity `.def` file that reproduces the environment inside a container.

Stages count **down to DEFCON 1** (container ready), like the real threat-level scale.

## Quickstart

```bash
# Stage 1: instrument your job script
python3 defcon.py stage1 -i my_job.qsub -o my_job_defcon.qsub

# Submit the instrumented job — it auto-calls stage2 when done
qsub my_job_defcon.qsub

# DEFCON 1 ✅  container.def is ready
singularity build container.sif container.def
```

## How it works

```
Stage 1 (DEFCON 3→2):  defcon stage1 -i input.qsub -o output.qsub
```
- Parses your qsub/sbatch script and extracts scheduler directives + commands
- Generates `output.run.sh`  — the original commands, unchanged
- Generates `output.qsub`   — an instrumented wrapper that:
  1. Captures `env -0` before any module loads
  2. Runs `output.run.sh` under `strace`
  3. Automatically calls `defcon stage2` to emit the `.def`

```
Stage 2 (DEFCON 2→1):  defcon stage2 -t trace.out -e env.out -c "cmd" -o container.def
```
- Parses the strace output to find all module install roots (`/share/pkg.*`)
  and project paths (`/projectnb`, `/project`, `/usr/local`)
- Writes a `Singularity` definition with `%files`, `%environment`, `%runscript`

## Key fix vs previous version

`strace` probes many hardware-capability library variants before finding the
right one — all as `ENOENT` failures.  The old parser skipped those lines,
missing most modules.  The new parser always extracts `/share/pkg` install
roots regardless of syscall outcome, since any probe proves the module is used.

## Options

### stage1
```
-i / --input     Input job script (.qsub or .sh)
-o / --output    Output instrumented script (default: <input>_defcon.qsub)
--def-out        Where stage2 writes the .def (default: <output>.def)
--scheduler      sge | slurm  (auto-detected from directives)
```

### stage2
```
-t / --trace     strace output file
-e / --env       env -0 dump file
-c / --command   Command to embed in %runscript
-o / --output    Output Singularity definition file
```

## Files
| File | Purpose |
|------|---------|
| `defcon.py` | Unified CLI — stage1 and stage2 |
| `strace_parser.py` | Parse strace output; extract module paths |
| `test.py` | Sample workload (`pandas` DataFrame) |