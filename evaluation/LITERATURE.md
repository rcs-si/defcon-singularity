# Literature audit and implementation decisions

Reviewed 2026-10-26. This is a targeted audit of the supplied plan and the
methods implemented here, not a claim to have exhausted all related literature.
Sources below are original papers, author copies, institutional records or
maintainer documentation. Access limitations are explicit.

| Source | What it supports and what this implementation does |
| --- | --- |
| Moreau, Wiebels & Boettiger (2023), [Containers for computational reproducibility](https://www.nature.com/articles/s43586-023-00236-9), [author copy](https://minio.carlboettiger.info/shared-data/Containers.pdf) | Container methods and limits. Retain recipe, environment, outputs and provenance; do not infer numerical or hardware portability from packaging success. Publisher abstract/record reviewed. |
| Canon & Younge (2019), [A Case for Portability and Reproducibility of HPC Containers](https://www.osti.gov/servlets/purl/1642946) | HPC system interfaces and host-library integration constrain portability. Keep supported-environment screening and runtime incompatibility separate from reconstruction failure. Full institutional paper accessed. |
| Torrez, Randles & Priedhorsky (2019), [HPC container runtimes have minimal or no performance impact](https://laro.lanl.gov/esploro/outputs/conferenceProceeding/HPC-container-runtimes-have-minimal-or/9916369628403761), [conference paper](https://conferences.computer.org/sc19w/2019/pdfs/CANOPIE-HPC2019-7nd7J7oXBlGtzeJIHi79mM/4VQ694HccmYWPtiazfnGiz/RirsVUUc5jhKx5UKJBlyT.pdf) | Native/container comparisons across benchmarks. This does not establish low syscall-tracing overhead or universal negligible overhead. Measure tracing, build and replay separately. Institutional record/abstract and indexed paper text reviewed. |
| [ReproZip packing documentation](https://docs.reprozip.org/en/1.1/packing.html) | Tracing, package attribution, editable file inventories and multiple-run capture are established techniques. Multi-trace aggregation is not itself a novel contribution; any adaptive benefit needs a fixed-budget multi-trace baseline. Full documentation accessed. |
| [Complete Provenance for Application Experiments with Containers and Hardware Interface Metadata](https://ieeexplore.ieee.org/iel7/10029390/10029941/10029967.pdf), CANOPIE-HPC 2022 | Hardware/interface metadata belongs alongside container artifacts. IEEE indexed abstract verified; direct full-text access failed. The lightweight provenance collector does not claim to reproduce that paper's complete system. |
| Lin, Simon & Niu, [Exploratory Metamorphic Testing for Scientific Software](https://pubmed.ncbi.nlm.nih.gov/32461738/), DOI 10.1109/MCSE.2018.2880577 | Relations between related input executions provide oracles for scientific software. Online publication 2018; journal issue 22(2), 2020. The supplied plan's year should be qualified. Indexed abstract and author-paper text reviewed; direct author page was temporarily unavailable. Relations in this toolkit are workload-declared, not universally valid. |
| [File-based localization of numerical perturbations in data analysis pipelines](https://arxiv.org/abs/2006.04684) (2020) | Comparing intermediate files can guide numerical-difference localization. The ordered artifact comparator is a limited diagnostic, not a reproduction of the paper's full perturbation/process analysis. Record/indexed text reviewed; PMC access presented an interstitial. |
| Rostamipoor, Ghavamnia & Polychronakis (2023), [Confine](https://mrostamipoor.github.io/files/confine.pdf), Computers & Security 132, 103325 | Static syscall analysis addresses dynamic-training coverage limits. Confine's objective is seccomp attack-surface reduction; `readelf` inventory collection here is not Confine's static call-graph analysis. Full author copy accessed. |
| [Methods and Tools for Optimizing Resource Allocation and Performance Evaluation in Serverless Environments and HPC Systems](https://escholarship.org/uc/item/9cb3k1sm) | Indexed dissertation text discusses Sharp and reproducible performance experiments. Direct repository access required browser verification; no claim of a full-text review or a Sharp reproduction. Our inference is grounded separately in paired log-ratio and equivalence methods. |
| NIST, [Covering Array Tables](https://www.nist.gov/itl/math/nist-covering-array-tables), [Combinatorial Coverage Measurement, IR 7878](https://csrc.nist.gov/pubs/ir/7878/final) | t-way interaction coverage and measurement. The toolkit greedily covers all feasible interactions, with explicit variable-strength groups. Coverage arrays are not probability samples and no minimal-array claim is made. |
| Chao & Colwell (2017), [Thirty years of progeny from Chao's inequality](https://www.idescat.cat/sort/sort411/41.1.1.chao-colwell.pdf); [tabula Chao2 documentation](https://search.r-project.org/CRAN/refmans/tabula/html/index_chao2.html) | Incidence-based estimation from uniques/duplicates and sampling assumptions. We implement the finite-sample bias-corrected form and label the software-dependency analogy exploratory. Full review and maintainer documentation accessed. |
| Lakens (2017), [Equivalence Tests: A Practical Primer](https://journals.sagepub.com/doi/pdf/10.1177/1948550617697177); Lakens, Scheel & Isager (2018), [Equivalence Testing for Psychological Research: A Tutorial](https://journals.sagepub.com/doi/10.1177/2515245918770963) | Two one-sided tests with prespecified margins; failure to reject a difference test does not establish equivalence. At alpha .05 the equivalence interval is 90%, not 95%. Indexed method text reviewed. |
| [Apptainer GPU guide](https://apptainer.org/docs/user/main/gpu.html), [MPI guide](https://apptainer.org/docs/user/main/mpi.html) | Runtime host-driver injection and compatible host/container MPI integration. Actual runtime flags and allocation compatibility remain explicit in manifests. Documentation accessed. |
| [scikit-learn GaussianProcessClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.gaussian_process.GaussianProcessClassifier), [Gaussian process guide](https://scikit-learn.org/stable/modules/gaussian_process.html) | Optional approximate GP classification. Predictive entropy is an uncertainty-sampling heuristic, not expected information gain about model parameters. |
| [statsmodels BinomialBayesMixedGLM](https://www.statsmodels.org/stable/generated/statsmodels.genmod.bayes_mixed_glm.BinomialBayesMixedGLM.html), [MixedLM](https://www.statsmodels.org/stable/generated/statsmodels.regression.mixed_linear_model.MixedLM.html) | Optional Bayesian binomial random-intercept and linear mixed fits. Reports retain convergence/optimizer information; inference needs design-specific checks. |

## Consequences for interpreting experiments

- A successful reconstruction is not necessarily dependency-complete, numerically
  equivalent, or portable. These are separate reports.
- Observed accesses, ELF sonames, package inventories and necessary files are
  different kinds of evidence. No automatic union becomes perfect ground truth.
- Holdout sampling must remain independent of adaptive discovery. Covering-array
  and adaptive success proportions describe those designs only.
- Chao2 and saturation cannot certify completion of dynamic discovery.
- GP entropy selection is implemented as a useful initial research baseline;
  full expected information gain, validated dependency-yield models and optimal
  stopping are not asserted.
- Host library injection is part of the supported runtime contract, not inherently
  a capture bug. Broad accidental mounts can nevertheless mask missing captures.
- No result in the reviewed literature validates a particular defcon image or
  supplies the scientific tolerance for a user's workload.
