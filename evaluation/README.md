# Robust evaluation of defcon

This opt-in research toolkit implements the three studies in the supplied plan:
dependency discovery, robustness/equivalence, and performance/cost. Run commands
from the repository root with Python 3.10+. Nothing is submitted to a scheduler
and no containers are built unless an explicit manifest command requests it.
The existing `defcon.py stage1/stage2` interface is unchanged.

This is an experimental harness, not evidence that defcon is portable. Actual
GPU, MPI, container-build, and cross-cluster results require supported allocations.
The local example runs the same native command twice to test the harness; it
must **not** be reported as a container experiment.

## Files and methods

| File | Method and purpose |
| --- | --- |
| `design.py` | Greedy constrained mixed-level covering arrays; extra high-risk interaction groups; independent weighted validation draws; randomized execution order within blocks. |
| `runner.py` | Run explicit native/traced/container argv commands, retain outputs, validate paired numerical results, record provenance, separate setup/build costs, run metamorphic pairs. |
| `dependencies.py` | Independent evidence inventory, exact file-set precision/recall, incidence accumulation/Chao2, single/multiple-trace definition generation using production APIs. |
| `equivalence.py` | Shape-aware absolute/relative numerical comparison and scaling, invariance, permutation, split-sum metamorphic relations. |
| `statistics.py` | Paired TOST, log runtime ratios and t confidence intervals, Wilson reliability intervals, break-even reuse, matched-record extraction. |
| `adaptive.py` | Cost-limited random baseline, maximin exploration, optional GP entropy-per-cost selection, dependency saturation stopping heuristic. |
| `models.py` | Optional hierarchical logistic model with workload random intercept; linear mixed performance model with node and nested workload effects. |
| `diagnostics.py` | Evidence-backed failure labels; ordered output-file localization; container-only dependency masking experiments. |
| `__main__.py` | CLI for all methods; `python3 -m evaluation --help`. |
| `workloads/` | Known branch/file dependency, NumPy/SciPy solve, PyTorch CPU/CUDA matmul/inference, and a C MPI reduction. |
| `examples/` | Local smoke test, cluster manifest template, factor design, metamorphic smoke test. |
| `tests/` | Mathematical edge cases, constrained coverage, holdout protection, aggregation compatibility, actual subprocess failures/timeouts and oracles. |
| `LITERATURE.md` | Source audit, methodological grounding, and limitations of the cited literature. |

Core design/execution/dependency methods use the standard library plus defcon's
existing requirements. Install optional analysis packages in a separate environment:

```bash
python3 -m venv /tmp/defcon-eval
. /tmp/defcon-eval/bin/activate
python -m pip install -r requirements.txt -r evaluation/requirements.txt
python -m unittest discover -s evaluation/tests -v
python -m unittest discover -s test -p 'test_*.py' -v
```

Local verification used Python 3.10, NumPy 1.26.4, SciPy 1.13.1, pandas 2.3.3,
statsmodels 0.14.6 and scikit-learn 1.7.2. A SciPy 1.15.3 wheel failed to load
on this Mac; the isolated test environment used `numpy==1.26.4 scipy==1.13.1`.
Record your installed versions; the optional requirements specify supported
ranges rather than a platform-independent binary lockfile.

PyTorch, NumPy/SciPy workloads, MPI, `readelf`, `strace`, GNU `time`, and Apptainer
are supplied by the experiment's environment. The toolkit does not install or
change an HPC environment. Optional model imports are lazy.

## Quick local check

Use fresh output directories; execution refuses to overwrite a previous run.
JSON report destinations should have an existing parent directory.

```bash
python3 -m evaluation design evaluation/examples/factors.json -o /tmp/coverage.json
python3 -m evaluation run evaluation/examples/local.json /tmp/coverage.json -o /tmp/defcon-coverage
python3 -m evaluation design evaluation/examples/factors.json --kind validation --count 20 --seed 321 -o /tmp/validation.json
python3 -m evaluation run evaluation/examples/local.json /tmp/validation.json -o /tmp/defcon-validation
python3 -m evaluation analyze reliability /tmp/defcon-validation/outcomes.json -o /tmp/reliability.json
python3 -m evaluation metamorphic evaluation/examples/metamorphic.json -o /tmp/defcon-metamorphic
```

## Study 1: dependency completeness and multi-trace capture

1. Freeze the application, inputs, base image and site configuration. Trace one
   reference configuration through the normal defcon workflow. Retain trace and
   environment artifacts outside transient scheduler storage.
2. Collect additional discovery traces across different branches, inputs and
   runtime settings. Keep validation configurations/outcomes out of selection.
3. Compare a single trace, a fixed-budget random multi-trace baseline, and an
   adaptive multi-trace strategy at equal trace counts **and** measured compute
   budgets. Use the same reference environment snapshot for all definitions;
   combining incompatible software installations is not resolved automatically.
4. Build each definition, inventory the resulting image, and validate all images
   using the same independently drawn held-out configurations.

```bash
python3 -m evaluation aggregate reference.trace --env env.out --base /absolute/base.sif -o /tmp/single.def
python3 -m evaluation aggregate reference.trace branch.trace --env env.out --base /absolute/base.sif -o /tmp/multi.def
# Inside a suitable build allocation, separately measure the build:
apptainer build --fakeroot /tmp/multi.sif /tmp/multi.def
```

`aggregate` calls `resolve_dependencies` separately for each trace, unions the
plans, prunes redundant nested roots, and calls `render_definition`. This retains
GPU driver exclusions, MPI, Conda, site configuration and explicit overrides.
`--include`, `--exclude`, `--gpu`, `--mpi`, `--mpi-root`, `--command-file` match
the resolver's concepts. One trace is the production single-trace baseline.
It writes `.plan.json` and `.inventory.json` next to the definition. The latter
expands selected paths on the capture host; it is **not** an image-content audit:
base-image files, dereferenced symlinks, build effects, and injected host files
must be assessed separately. Directory-root counts cannot be compared to file
counts. No GPU/MPI launcher is emitted here: use the normal stage2 launcher or
explicit runtime commands as described below.

Build the operational reference from independent evidence:

```bash
python3 -m evaluation inventory --trace reference.trace --trace branch.trace \
  --elf /absolute/application --linker ld-debug.log --manifest required.json \
  -o /tmp/reference.json
```

A manifest is a JSON list, for example:

```json
[{"path":"/absolute/plugin.so","kind":"controlled_branch","required":true}]
```

Each path retains source, evidence kind and requirement status. Trace accesses
are marked observed, never required by default. The independent parser accepts
complete successful absolute-path file calls, excludes failed probes and write
creation, and does not apply defcon's site-prefix filter. It is intentionally
conservative: relative paths, unfinished/resumed records and unusual strace
escaping may be omitted. Supply independently resolved manifests for those
cases. This is not a general strace provenance parser. `readelf -d` records
`DT_NEEDED` sonames as **unresolved**, without pretending they identify actual
files or executing an untrusted binary with `ldd`. Use loader diagnostics from
an explicitly run workload (`LD_DEBUG=libs,files` on glibc), package metadata and
controlled branches to resolve them. Loader `trying file` probes are not imported
as successful loads. Static overapproximation and dynamic undercoverage remain.

`completeness` takes two JSON arrays of absolute file paths, D then G. Explicitly
select observed or independently validated required evidence from the inventory.
It reports `|D∩G|/|G|`, `|D∩G|/|D|`, missing and extra paths; an empty denominator
is `null`. Normalize lexically, retain absolute prefixes, and use matching units
and dependency scope. Separate application-captured, base-image, runtime-injected
GPU/MPI and intentionally bound input dependencies in your analysis.

```bash
python3 -m evaluation completeness captured-paths.json required-paths.json -o /tmp/completeness.json
python3 -m evaluation saturation samples.json --min-runs 5 --patience 3 -o /tmp/saturation.json
```

`samples.json` is an ordered array of per-execution path arrays. The report gives
cumulative unique paths and newly discovered paths at each step. It computes the
finite-sample bias-corrected incidence Chao2 form:

`S_obs + ((m-1)/m) * Q1*(Q1-1)/(2*(Q2+1))`.

Q1 and Q2 count paths appearing in exactly one and two executions. With fewer
than two executions, Chao2 is unavailable. The estimator is an exploratory
analogy, **not** a validated bound on software dependency completeness. Correlated,
nonrandom, adaptive executions violate ecological sampling assumptions. A run
of zero new dependencies suggests a stopping point only; held-out validation
remains necessary. The report contains plot-ready accumulation coordinates.

For controlled necessity checks, use `ablate` with a baseline image and explicit
mask targets. It mounts an empty file/directory read-only over a path inside the
container and never removes host libraries:

```json
{
  "image":"/absolute/application.sif", "runtime":"apptainer",
  "runtime_flags":["--cleanenv","--containall"],
  "argv":["/absolute/application"],
  "oracle":{"field":"result","atol":0.000001,"rtol":0.000001},
  "targets":[{"path":"/opt/app/plugin.so","kind":"file"}]
}
```

```bash
python3 -m evaluation ablate ablation.json -o /tmp/ablation
```

An unmasked baseline must succeed. Inspect bind/runtime errors before attributing
an outcome to a dependency. Empty-file masking is a sensitivity intervention,
not literal absence; alternatives and interactions mean one-at-a-time masking
cannot establish a minimal dependency set.

## Study 2: perturbations, equivalence and portability

Factor specifications contain `factors` (nonempty scalar level lists), optional
`forbidden` partial combinations, `strength` (default pairwise), and
`high_risk_groups` (cover every feasible combination in each named group).
The greedy set-cover implementation explicitly verifies feasible interaction
coverage by construction, but does not minimize array size. It enumerates the
candidate space and refuses more than 100,000 candidates by default; for larger
spaces use NIST ACTS and import its rows as a coverage design.

The example requests three-way coverage of all three factors, so it intentionally
reduces to the full factorial. Use high-risk subsets of a larger factor model
for savings. Settings such as GPU type or node must correspond to actual allocated
hardware; changing a JSON label does not change hardware. Use one allocation per
hardware stratum and record the sampling/allocation policy.

For reliability, `--kind validation` draws with replacement using the product of
per-level `weights`, conditioned on the forbidden constraints. Weights are arrays
aligned with factor levels; omitted weights are uniform. This declares a target
distribution; it does not discover the real deployment distribution. A seed and
spec are retained. Do not remove validation draws that happen to match discovery
settings: conditioning on disjoint rows would change the estimand. Instead keep
validation outcomes unseen until selection and stopping have finished.

The execution manifest defines:

- `workload`, `blocks`, `seed`, `timeout`, `cwd` (default repository root).
- `modes.native.argv` and `modes.container.argv`, plus optional `traced` or other
  modes. Commands are argument arrays; no implicit shell, `eval` or scheduler.
- `env` and per-mode `env` overrides. `{factor}`, `{repo}`, `{python}`, `{output}`,
  `{run_dir}` placeholders are replaced literally. Reserved names cannot be factors.
- Per-mode `artifacts`: file paths with the same placeholders; record byte sizes
  and SHA256 for traces, images or inputs after the timed command. Missing files
  are marked unavailable. Hashing is outside timing but can affect filesystem
  cache state, so keep the policy consistent or collect image hashes separately.
- `oracle`: required `atol`, `rtol`, optional dotted `field` in JSON stdout. Commands
  should print exactly one JSON value; send diagnostics to stderr or use a wrapper.
- Optional `preflight` argv: exit **77** explicitly denotes an unsupported
  configuration. Other failures remain infrastructure failures, not exclusions.
  Prespecify supported GPU/driver/MPI combinations independently of results.
- Optional `setup`: list of `{name, argv, timeout}` for dependency analysis and
  build phases; these run once and are timed separately.
- `measure_resources`: Linux GNU `/usr/bin/time -v` stores CPU, peak RSS and I/O
  metrics per command. Else these metrics are unavailable, not zero.
- `gpu_monitor`: optional NVIDIA samples every 200 ms; monitoring can perturb
  short runtimes and covers visible GPUs, not just the workload process. Disable
  consistently in primary timing experiments or use a separate profiling study.

Commands run sequentially with randomized mode order within each sample/block.
Environment overrides inherit the allocation environment. Use wrapper scripts
for `module purge/load`, working-directory preparation, or library-path changes.
Command timeout kills the local process group; scheduler-launched remote tasks
may still need allocation cleanup. The harness does not retry failed runs.

Each command gets its own stdout/stderr and record. `records.jsonl` retains
partial progress; `records.json`, `outcomes.json`, manifest, design and provenance
are written for completed studies. Provenance includes node, OS, architecture,
Python, Git revision, selected allocation/thread/module variables and available
NVIDIA identity/driver information. It does not dump all environment secrets.
Record additional hardware/runtime, input and image checksums in your study
archive; commands alone do not guarantee immutable inputs.

`examples/cluster.json` is a template: replace `/REPLACE/branch.sif` and use an
image containing the application at its original absolute path. Avoid automatic
host/project/home mounts hiding missing captured dependencies. Check your site's
mount policy; restrict binds to declared inputs. Propagate experiment thread
variables explicitly through `APPTAINERENV_OMP_NUM_THREADS` or runtime `--env`
when using `--cleanenv`. Never copy a broad project root merely to make a failed
completeness experiment pass.

For CUDA/ML, use `workloads/torch_workload.py --device cuda` with runtime `--nv`,
an allocated GPU, compatible driver/toolkit/framework and, where needed,
`CUBLAS_WORKSPACE_CONFIG=:4096:8`. The workload refuses CPU fallback, synchronizes
CUDA and emits the device. Matrix scaling is linear; positive scaling also
preserves this example's bias-free ReLU inference. Negative scaling does not.
For your external `matrixMulCUBLAS`, supply a wrapper that exports actual numeric
results; a PASS banner or exit code alone is not a numerical oracle.
For MPI, compile `mpi_sum.c` with the site's `mpicc`; put host `mpirun -n N` **outside**
`apptainer exec` and use a compatible MPI implementation/transport inside the
image. Remote ranks may require per-rank tracing beyond local `strace -f`.
For SciPy, `scientific.py --solver scipy` activates a different compiled path
from `--solver numpy`; changing size alone need not expose a new dependency.

Elementwise comparison uses `abs(actual-reference) <= atol + rtol*abs(reference)`.
It checks nested shape, rejects NaN/infinity and empty results, and reports maximum
absolute and relative L2 error. Choose scientific tolerances **before** observing
results. No oracle yields `success: null`, never a correctness claim.

`metamorphic` executes base and transformed-input commands separately in native
and container environments. Supported relations are `scale`, `invariant`,
`permutation` (complete output index permutation), and `split_sum` (two scalar
partial integrals sum to the base scalar). The workload author must justify and
implement the input transformation. Passing a relation in both environments does
not itself demonstrate cross-environment equivalence; run both checks.

```bash
python3 -m evaluation analyze tost differences.json -o /tmp/tost.json
```

Input: `{"differences":[0.001,-0.002,0.003],"lower":-0.01,"upper":0.01,"alpha":0.05}`.
Use independently paired native-minus-container scalar differences. TOST rejects
both outside-margin null hypotheses; its equivalent CI is 100(1-2α)% (90% at
α=.05). It assumes independent approximately normal paired differences. Zero
sample variance produces an indeterminate result. Do not flatten correlated
vector components into independent replicates; use domain summaries, account for
multiple endpoints, and justify margins. Stochastic workload distribution tests
require a workload-specific analysis, not an automatic claim from elementwise
comparison.

Reliability uses one outcome per IID configuration draw and a Wilson interval.
Repeated blocks are aggregated as **all blocks equivalent**; this estimates
success of that fixed repeated-run protocol, not per-execution success probability.
Do not mix block counts. Coverage/adaptive rows, duplicate sample IDs and unresolved
eligible outcomes are rejected. Only a prespecified unsupported classification is
excluded. Node/time correlation can invalidate binomial intervals; stratify or
use a separately justified clustered model when draws are not independent.

Attach diagnoses without rewriting execution evidence:

```bash
python3 -m evaluation classify outcomes.json annotations.json -o /tmp/diagnosed.json
python3 -m evaluation localize artifacts.json -o /tmp/localization.json
```

Annotations: `[{"sample_id":0,"category":"missing_dependency","evidence":"loader log line and controlled mask reproduction"}]`.
Categories: missing dependency, runtime incompatibility, numerical mismatch,
resource exhaustion, infrastructure failure, or unclassified execution failure
(use snake_case names). Exit failure alone never establishes missing dependencies.
Localization accepts ordered `{native,container}` file pairs and compares SHA256,
or numeric JSON with `numeric:true,atol,rtol`. First divergence is an inspection
lead, not proven causation or an implementation of the full perturbation-localization
research system.

## Study 3: performance and practical cost

Use comparable allocations, a prespecified warmup/cache policy, random order,
and independent blocks. The runner measures end-to-end process elapsed time,
including launcher/interpreter/runtime startup. It retains failed runs; successful
runtime pairs are selected explicitly for performance analysis. Report excluded
failures alongside timing, never silently infer negligible overhead from survivors.
Do not pool different workloads/node strata into a t interval or treat repeated
measurements of one allocation as independent allocations.

```python
import json
from evaluation.statistics import paired_records, performance
records = json.load(open('/tmp/defcon-coverage/records.json'))
pairs, excluded = paired_records(records, mode='container')
# Apply only to an independently blocked, homogeneous workload/configuration stratum.
report = performance(pairs, ratio_bounds=[0.95, 1.05])
print(report, 'excluded blocks:', excluded)
```

The CLI equivalent consumes `{"pairs":[[10,10.1],[11,11.2],[9,9.05]],"ratio_bounds":[0.95,1.05]}`.
It averages `log(T_mode/T_native)` and exponentiates a t interval to obtain a
geometric mean ratio. The ordinary interval is 95%; optional TOST uses the
prespecified ratio bounds on the log scale. `mode='traced'` estimates tracing
overhead separately. `.wall_seconds` setup records measure analysis/build costs.
Archive image/trace sizes and raw syscall summaries separately; `trace=file`
records cannot estimate total syscall counts. Use a separate `strace -c` run for
that metric because profiling affects runtime.

Break-even CLI input:

```json
{"trace_cost":100,"build_cost":200,"container_time":9,"setup_cost":50,"baseline_time":10}
```

```bash
python3 -m evaluation analyze break-even costs.json -o /tmp/break-even.json
```

Solves `(C_trace+C_build-C_setup) <= N*(T_baseline-T_container)` for integer N.
It handles no crossing, equal slopes, and initially cheaper but slower containers
with a finite upper reuse limit. All costs need common units. Include comparable
packaging/setup work and justify labor-to-cost conversions; comparing to an
already prepared native environment answers a different question.

## Adaptive discovery and hierarchical analysis

```bash
python3 -m evaluation adaptive factors.json history.json --budget 100 --strategy gp -o /tmp/next.json
```

History is `[{"configuration":{"size":4,"optional":"no","threads":1},"dataset":"adaptive","success":true}]`.
The budget is the **remaining** discovery budget. Optional factor-spec `costs`
contains `{when: {factor: level}, seconds: number}` entries (last matching rule wins);
otherwise `default_cost_seconds` applies. Record actual costs after each execution,
subtract them from the budget, append the outcome, and call again. Configurations
already in history are excluded. Return `configuration:null` means exhausted
budget/candidates. Execute recommendations through an adaptive design object
`{"dataset":"adaptive","configurations":[...recommended configuration...]}` and
retain the resulting trace for `aggregate`.

`random` is the fixed-budget nonadaptive baseline. `novelty` maximizes the minimum
categorical Hamming distance from previous configurations divided by cost. `gp`
uses one-hot factor levels and an RBF Gaussian-process classifier; it maximizes
**predictive Bernoulli entropy per cost**, a practical uncertainty heuristic, not
Bayesian expected information gain. It falls back to novelty until both success
and failure are observed. Predictions are uncalibrated exploratory estimates.
The method does not infer unseen dependency identities. Keep independent held-out
validation results out of history (the API rejects labeled validation records).

Optional hierarchical models consume a list of tabular JSON rows:

```bash
python3 -m evaluation model model-rows.json --kind logistic \
  --formula 'success ~ C(gpu) * C(input_size) + C(library)' -o /tmp/logistic.json
python3 -m evaluation model timing-rows.json --kind performance \
  --formula 'log_ratio ~ C(condition)' -o /tmp/mixed.json
```

Logistic rows require binary `success` and `workload`; the model adds a workload
random intercept and uses statsmodels' variational Bayes fit/default priors.
Timing rows require `node`, `workload`, presummarized `log_ratio`, and formula
covariates; the model uses node groups and workload-within-node variance components.
This is not a fully crossed arbitrary repeated-measures model. Inspect optimizer
status, convergence, separation, sample size, prior sensitivity and calibration.
These models describe the tested design; they cannot establish reliability
outside that distribution. Adaptive data can support failure exploration, but
not an unbiased deployment failure rate.

## Compatibility and limits

The only production-file repair restores `strace_parser.py`'s missing site-config
imports and configurable module-name/path handling. The untouched baseline could
not import the pipeline; the existing 35-test suite verifies the repair. No
production requirements, CLI flags, or rendering interfaces are changed.

The suite supplies reusable methods and workloads, not a universal application
oracle, automatic scheduler/hardware provisioning, exhaustive static analysis,
or a proof of completeness. Full cluster validation remains an experiment to run
with the real site images, modules, GPU hardware, MPI transport and permissions.
