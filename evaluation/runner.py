"""Sequential randomized blocks in an existing allocation; no scheduler submission."""
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from .design import blocked_order
from .equivalence import compare, metamorphic

REPO = Path(__file__).resolve().parents[1]
ENV_KEYS = ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
            'CUDA_VISIBLE_DEVICES', 'ROCR_VISIBLE_DEVICES', 'LOADEDMODULES',
            'SLURM_JOB_ID', 'JOB_ID')


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def probe(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'unavailable': str(exc)}


def artifact_metadata(paths):
    result = []
    for raw in paths:
        path = Path(raw)
        try:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(chunk)
            result.append({'path': str(path), 'bytes': path.stat().st_size,
                           'sha256': digest.hexdigest()})
        except OSError as exc:
            result.append({'path': str(path), 'unavailable': str(exc)})
    return result


def provenance(manifest):
    return {'time_utc': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
            'node': platform.node(), 'machine': platform.machine(), 'python': sys.version,
            'cpu_count': os.cpu_count(), 'environment': {k: os.environ[k] for k in ENV_KEYS if k in os.environ},
            'git': probe(['git', '-C', str(REPO), 'rev-parse', 'HEAD']),
            'gpu': probe(['nvidia-smi', '--query-gpu=name,uuid,driver_version,memory.total', '--format=csv']),
            'manifest_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}


def expand(argv, context):
    if not isinstance(argv, list) or not argv or any(not isinstance(v, str) for v in argv):
        raise ValueError('Commands must be nonempty argv arrays, not shell strings')
    # Literal named placeholders only: braces in embedded scripts remain intact.
    return [replace(v, context) for v in argv]


def replace(value, context):
    for k, v in context.items():
        value = value.replace('{' + k + '}', str(v))
    return value


def execute(argv, directory, env, timeout, cwd, measure=False, gpu_monitor=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    if timeout <= 0:
        raise ValueError('Timeout must be positive')
    started = time.perf_counter()
    status, code, error = 'completed', None, None
    command = argv
    # GNU time records per-command descendants' resource use without cumulative
    # RUSAGE_CHILDREN high-water marks leaking across experimental runs.
    time_file = directory / 'resources.txt'
    if measure and sys.platform.startswith('linux') and Path('/usr/bin/time').exists():
        command = ['/usr/bin/time', '-v', '-o', str(time_file), '--'] + argv
    monitor = None
    if gpu_monitor:
        try:
            monitor = subprocess.Popen(['nvidia-smi', '--query-gpu=timestamp,uuid,utilization.gpu,memory.used',
                                        '--format=csv', '-lms', '200', '-f', str(directory / 'gpu.csv')],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    try:
        with (directory / 'stdout.txt').open('wb') as out, (directory / 'stderr.txt').open('wb') as err:
            try:
                proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
                try:
                    code = proc.wait(timeout=timeout)
                    if code != 0:
                        status = 'failed'
                except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                    if isinstance(exc, KeyboardInterrupt):
                        raise
                    status = 'timeout'
            except OSError as exc:
                status, error = 'infrastructure_failure', str(exc)
    finally:
        elapsed = time.perf_counter()-started
        if monitor:
            monitor.terminate()
            try:
                monitor.wait(timeout=3)
            except subprocess.TimeoutExpired:
                monitor.kill()
                monitor.wait()
    return {'argv': argv, 'cwd': str(cwd), 'status': status, 'returncode': code, 'error': error,
            'wall_seconds': elapsed, 'directory': str(directory),
            'resources_file': str(time_file) if time_file.exists() else None,
            'gpu_samples': str(directory / 'gpu.csv') if (directory / 'gpu.csv').exists() else None}


def output_value(record, field):
    value = json.loads((Path(record['directory']) / 'stdout.txt').read_text())
    for part in field.split('.') if field else []:
        value = value[part]
    return value


def run(manifest, design, output):
    output = Path(output).resolve()
    modes = manifest['modes']
    if 'native' not in modes or 'container' not in modes:
        raise ValueError('Declare both native and container modes')
    if any(not name.replace('_', '').isalnum() for name in modes):
        raise ValueError('Mode names must be alphanumeric or underscores')
    if design['dataset'] not in ('coverage', 'validation', 'adaptive'):
        raise ValueError('Unknown dataset')
    oracle = manifest.get('oracle')
    if oracle:
        compare([0], [0], oracle['atol'], oracle['rtol'])
    blocks = manifest.get('blocks', 1)
    blocked_order(list(modes), blocks, manifest.get('seed', 0))
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'manifest.json', manifest)
    write_json(output / 'design.json', design)
    write_json(output / 'provenance.json', provenance(manifest))
    records, outcomes = [], []
    base_context = {'repo': REPO, 'output': output, 'python': sys.executable}
    # Optional analysis/build phases are timed separately, never included in runtime ratios.
    for i, phase in enumerate(manifest.get('setup', [])):
        context = dict(base_context, run_dir=output / f'setup-{i}')
        rec = execute(expand(phase['argv'], context), context['run_dir'], os.environ.copy(),
                      phase.get('timeout', 3600), manifest.get('cwd', str(REPO)), measure=True)
        rec['phase'] = phase['name']
        write_json(output / f'setup-{i}.json', rec)
        if rec['status'] != 'completed':
            raise RuntimeError(f"Setup failed; see {rec['directory']}")
    for sample_id, config in enumerate(design['configurations']):
        if set(config) & {'repo', 'output', 'python', 'run_dir'}:
            raise ValueError('Factor uses reserved placeholder name')
        context = dict(base_context, **config)
        env = os.environ.copy()
        env.update({k: replace(str(v), context) for k, v in manifest.get('env', {}).items()})
        supported = True
        if manifest.get('preflight'):
            check_dir = output / f'sample-{sample_id}-preflight'
            rec = execute(expand(manifest['preflight'], dict(context, run_dir=check_dir)), check_dir,
                          env, manifest.get('timeout', 300), manifest.get('cwd', str(REPO)))
            if rec['status'] != 'completed':
                # Only explicit exit 77 means unsupported; errors remain eligible failures.
                supported = rec['returncode'] != 77
                outcomes.append({'sample_id': sample_id, 'dataset': design['dataset'], 'configuration': config,
                                 'supported': supported, 'success': False,
                                 'category': 'infrastructure_failure' if supported else 'unsupported_environment'})
                write_json(check_dir / 'record.json', rec)
                continue
        sample_records = {}
        for block, mode in blocked_order(list(modes), blocks, manifest.get('seed', 0)+sample_id):
            directory = output / f'sample-{sample_id}-block-{block}-{mode}'
            ctx = dict(context, run_dir=directory)
            mode_spec = modes[mode]
            mode_env = dict(env, **{k: replace(str(v), ctx) for k, v in mode_spec.get('env', {}).items()})
            rec = execute(expand(mode_spec['argv'], ctx), directory, mode_env,
                          mode_spec.get('timeout', manifest.get('timeout', 300)),
                          replace(manifest.get('cwd', str(REPO)), ctx), measure=manifest.get('measure_resources', False),
                          gpu_monitor=manifest.get('gpu_monitor', False))
            rec.update(sample_id=sample_id, block=block, mode=mode, configuration=config,
                       node=platform.node(), dataset=design['dataset'], workload=manifest['workload'])
            rec['artifacts'] = artifact_metadata(
                [replace(p, ctx) for p in mode_spec.get('artifacts', [])])
            sample_records[block, mode] = rec
            records.append(rec)
            write_json(directory / 'record.json', rec)
            # Persist partial progress even if later commands are interrupted.
            with (output / 'records.jsonl').open('a') as stream:
                stream.write(json.dumps(rec, allow_nan=False)+'\n')
        validations = []
        for block in range(blocks):
            a, b = sample_records[block, 'native'], sample_records[block, 'container']
            if a['status'] != 'completed':
                validations.append({'equivalent': False, 'category': 'native_reference_failure'})
            elif b['status'] != 'completed':
                validations.append({'equivalent': False, 'category': b['status'] if b['status'] in ('timeout', 'infrastructure_failure') else 'unclassified_execution_failure'})
            elif not oracle:
                validations.append({'equivalent': None, 'category': 'unvalidated'})
            else:
                try:
                    result = compare(output_value(a, oracle.get('field', '')),
                                     output_value(b, oracle.get('field', '')), oracle['atol'], oracle['rtol'])
                    result['category'] = 'success' if result['equivalent'] else 'numerical_mismatch'
                    validations.append(result)
                except (ValueError, KeyError, TypeError) as exc:
                    validations.append({'equivalent': False, 'category': 'invalid_output', 'reason': str(exc)})
        # Each draw's outcome is all-repeat equivalence, explicitly not a single-run probability.
        success = (all(v['equivalent'] for v in validations)
                   if all(v['equivalent'] is not None for v in validations) else None)
        outcomes.append({'sample_id': sample_id, 'dataset': design['dataset'], 'configuration': config,
                         'supported': supported, 'success': success, 'validations': validations})
        write_json(output / 'outcomes.json', outcomes)
    write_json(output / 'records.json', records)
    write_json(output / 'outcomes.json', outcomes)
    return {'records': len(records), 'samples': len(outcomes), 'output': str(output)}


def run_metamorphic(spec, output):
    """Execute base/transformed input commands in each environment independently."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for mode in ('native', 'container'):
        values = []
        for label in ('base', 'transformed'):
            directory = output / f'{mode}-{label}'
            context = {'repo': REPO, 'python': sys.executable, 'run_dir': directory}
            rec = execute(expand(spec[mode][label], context), directory, os.environ.copy(),
                          spec.get('timeout', 300), spec.get('cwd', str(REPO)))
            write_json(directory / 'record.json', rec)
            if rec['status'] != 'completed':
                raise RuntimeError(f'Metamorphic execution failed: {directory}')
            values.append(output_value(rec, spec.get('field', '')))
        results[mode] = metamorphic(*values, **spec['relation'])
    write_json(output / 'metamorphic.json', results)
    return results
