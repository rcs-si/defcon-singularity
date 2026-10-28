"""Independent evidence inventories and reuse of defcon's production resolver."""
import collections
import dataclasses
import json
import posixpath
import re
import subprocess
from pathlib import Path


def normalize(path):
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError('Inventory paths must be absolute')
    return '/' + posixpath.normpath(path).lstrip('/')


def inventory(traces=(), manifests=(), elfs=(), linker_logs=()):
    evidence = collections.defaultdict(list)
    warnings = []
    def add(path, source, kind, required=False):
        evidence[normalize(path)].append({'source': str(source), 'kind': kind, 'required': required})
    for trace in traces:
        for line in Path(trace).read_text(errors='replace').splitlines():
            # Conservative independent parser: complete successful file syscalls,
            # first pathname only, no writes or failed existence probes as requirements.
            m = re.search(r'\b(openat|open|execve|stat|newfstatat|access|readlink)\(.*?"((?:[^"\\]|\\.)*)".*\)\s+=\s+(\d+)', line)
            if not m:
                continue
            try:
                path = json.loads('"' + m[2] + '"')
            except ValueError:
                warnings.append('Undecodable trace pathname')
                continue
            if not path.startswith('/'):
                warnings.append('Relative trace paths omitted; supply a resolved manifest')
                continue
            if 'O_WRONLY' in line or 'O_CREAT' in line:
                continue
            add(path, trace, 'runtime_observed')
    for manifest in manifests:
        for entry in json.loads(Path(manifest).read_text()):
            add(entry['path'], manifest, entry.get('kind', 'package_metadata'), entry.get('required') is True)
    unresolved = []
    for elf in elfs:
        # readelf inspects data; unlike ldd it does not execute the inspected binary.
        output = subprocess.run(['readelf', '-d', str(elf)], capture_output=True, text=True,
                                check=True, timeout=30).stdout
        add(str(Path(elf).absolute()), elf, 'elf_object')
        unresolved.extend({'object': str(elf), 'soname': name}
                          for name in re.findall(r'\(NEEDED\).*?\[(.*?)\]', output))
    for log in linker_logs:
        for path in re.findall(r'(?:calling init:|calling fini:|file=)\s*(/[^\s;\[\]]+)',
                               Path(log).read_text(errors='replace')):
            add(path, log, 'linker_observed')
    return {'paths': dict(sorted(evidence.items())), 'unresolved_sonames': unresolved,
            'warnings': sorted(set(warnings)), 'claim': 'operational reference, not ground truth'}


def completeness(captured, reference):
    d = {normalize(p) for p in captured}
    g = {normalize(p) for p in reference}
    return {'captured': len(d), 'reference': len(g), 'intersection': len(d & g),
            'recall': len(d & g)/len(g) if g else None,
            'precision': len(d & g)/len(d) if d else None,
            'missing': sorted(g-d), 'extra': sorted(d-g)}


def saturation(samples):
    if not samples:
        raise ValueError('At least one execution inventory required')
    counts = collections.Counter()
    curve = []
    for sample in samples:
        before = len(counts)
        counts.update({normalize(p) for p in sample})
        curve.append({'executions': len(curve)+1, 'unique': len(counts), 'new': len(counts)-before})
    m = len(samples)
    q1, q2 = sum(v == 1 for v in counts.values()), sum(v == 2 for v in counts.values())
    estimate = len(counts) + (m-1)/m * q1*(q1-1)/(2*(q2+1)) if m >= 2 else None
    return {'curve': curve, 'q1': q1, 'q2': q2, 'chao2_bias_corrected': estimate,
            'warning': 'Exploratory incidence estimate; correlated/adaptive samples violate sampling assumptions. Saturation does not prove completeness.'}


def aggregate(traces, **options):
    from dependency_resolver import resolve_dependencies, DependencyPlan
    from path_utils import _path_is_under
    plans = [resolve_dependencies(Path(trace), **options) for trace in traces]
    if not plans:
        raise ValueError('At least one trace required')
    values = {}
    for field in dataclasses.fields(DependencyPlan):
        values[field.name] = (any(p.mpi_enabled for p in plans) if field.name == 'mpi_enabled'
                              else sorted(set().union(*(getattr(p, field.name) for p in plans))))
    roots = values['copy_roots']
    values['copy_roots'] = [r for r in roots if not any(r != p and _path_is_under(r, p) for p in roots)]
    for key in ('project_files', 'blocked_libs'):
        values[key] = [p for p in values[key] if not any(_path_is_under(p, r) for r in values['copy_roots'])]
    return DependencyPlan(**values)


def selected_inventory(plan):
    """Expand selected copy paths on the capture host; not proof of image contents."""
    from environments.gpu import is_host_driver
    from path_utils import _path_is_under
    paths, missing = set(), []
    for raw in plan.copy_roots + plan.project_files + plan.blocked_libs:
        root = Path(raw)
        if not root.exists():
            missing.append(raw)
            continue
        entries = root.rglob('*') if root.is_dir() else [root]
        for p in entries:
            s = str(p)
            if p.is_dir() or any(_path_is_under(s, ex) for ex in plan.exclude_paths):
                continue
            if plan.gpu_backends and is_host_driver(s):
                continue
            paths.add(normalize(s))
    return {'paths': sorted(paths), 'missing_sources': missing,
            'claim': 'capture-host selection inventory; excludes base image and runtime host injection'}
