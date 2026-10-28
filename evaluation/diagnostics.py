"""Evidence-backed failure labels, file comparison, and container-only masking."""
import hashlib
import json
import os
from pathlib import Path
from .runner import execute, expand, output_value, REPO, write_json
from .equivalence import compare

CATEGORIES = {'missing_dependency', 'runtime_incompatibility', 'numerical_mismatch',
              'resource_exhaustion', 'infrastructure_failure', 'unclassified_execution_failure'}


def classify(outcomes, annotations):
    """Human diagnoses must cite evidence; stderr guesses are not causal labels."""
    rows = {r['sample_id']: dict(r) for r in outcomes}
    for entry in annotations:
        if entry['category'] not in CATEGORIES or not entry.get('evidence'):
            raise ValueError('Diagnosis needs an allowed category and evidence')
        row = rows[entry['sample_id']]
        if row.get('success') is True:
            raise ValueError('Cannot classify a successful sample as a failure')
        row['diagnosis'] = {'category': entry['category'], 'evidence': entry['evidence']}
    return list(rows.values())


def localize(pairs):
    """Compare ordered pipeline artifacts; first divergence is not proven causation."""
    result = []
    for pair in pairs:
        a, b = Path(pair['native']), Path(pair['container'])
        if pair.get('numeric'):
            check = compare(json.loads(a.read_text()), json.loads(b.read_text()),
                            pair['atol'], pair['rtol'])
        else:
            def digest(p):
                h = hashlib.sha256()
                with p.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b''):
                        h.update(chunk)
                return h.hexdigest()
            check = {'equivalent': digest(a) == digest(b)}
        result.append(dict(pair, comparison=check))
    return {'artifacts': result, 'first_divergence': next((i for i, r in enumerate(result)
            if not r['comparison']['equivalent']), None),
            'claim': 'ordered artifact comparison; no automatic process-level causal attribution'}


def ablate(spec, output):
    """Mask named paths inside an Apptainer image; never delete host dependencies."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    oracle = spec['oracle']
    runtime = spec.get('runtime', 'apptainer')
    image = str(Path(spec['image']).resolve())
    command = spec['argv']
    base = [runtime, 'exec'] + spec.get('runtime_flags', [])
    results = []
    reference = None
    for i, target in enumerate([None] + spec['targets']):
        directory = output / f'case-{i}'
        argv = list(base)
        if target:
            path = target['path']
            if not path.startswith('/') or path == '/' or ':' in path or ',' in path:
                raise ValueError('Mask target must be an absolute file/directory path without bind separators')
            mask = output / f'mask-{i}'
            if target['kind'] == 'directory':
                mask.mkdir()
            elif target['kind'] == 'file':
                mask.touch()
            else:
                raise ValueError('Target kind must be file or directory')
            argv += ['--bind', f'{mask}:{path}:ro']
        argv += [image] + expand(command, {'repo': REPO, 'run_dir': directory})
        rec = execute(argv, directory, os.environ.copy(), spec.get('timeout', 300), spec.get('cwd', str(REPO)))
        rec['target'] = target
        if target is None:
            if rec['status'] != 'completed':
                write_json(output / 'ablation.json', [rec])
                raise RuntimeError('Unmasked baseline must succeed before ablation')
            reference = output_value(rec, oracle.get('field', ''))
            if not compare(reference, reference)['equivalent']:
                raise ValueError('Baseline output must be finite and nonempty')
        elif rec['status'] == 'completed':
            try:
                rec['comparison'] = compare(reference, output_value(rec, oracle.get('field', '')),
                                            oracle['atol'], oracle['rtol'])
            except (ValueError, KeyError, TypeError) as exc:
                rec['output_error'] = str(exc)
        rec['claim'] = 'mask sensitivity only; inspect bind failures, alternatives, and dependency interactions'
        results.append(rec)
        write_json(output / 'ablation.json', results)
    return results
