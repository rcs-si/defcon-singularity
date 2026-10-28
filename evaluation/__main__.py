"""Run with python -m evaluation COMMAND from the repository root."""
import argparse
import dataclasses
import json
from pathlib import Path
from .runner import write_json


def read(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('design', help='Covering array or IID validation sample')
    p.add_argument('spec'); p.add_argument('--kind', choices=['coverage', 'validation'], default='coverage')
    p.add_argument('--count', type=int, default=30); p.add_argument('--seed', type=int, default=0)
    p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('run', help='Execute a manifest in the current allocation')
    p.add_argument('manifest'); p.add_argument('design'); p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('metamorphic', help='Execute and check transformed-input pairs')
    p.add_argument('spec'); p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('inventory', help='Independent evidence from traces, ELF, linker and metadata')
    for name in ('trace', 'manifest', 'elf', 'linker'):
        p.add_argument('--'+name, action='append', default=[])
    p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('aggregate', help='Generate a definition using one or multiple traces')
    p.add_argument('traces', nargs='+'); p.add_argument('--env', required=True); p.add_argument('--base', required=True)
    p.add_argument('--gpu', choices=['auto', 'nvidia', 'amd', 'none'], default='auto')
    p.add_argument('--mpi', choices=['auto', 'on', 'none'], default='auto')
    p.add_argument('--mpi-root'); p.add_argument('--command-file', type=Path)
    p.add_argument('--include', action='append', default=[]); p.add_argument('--exclude', action='append', default=[])
    p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('completeness', help='Compare explicit file-level lists, not directory roots')
    p.add_argument('captured'); p.add_argument('reference'); p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('saturation', help='Incidence accumulation and heuristic stopping')
    p.add_argument('samples'); p.add_argument('--min-runs', type=int, default=5)
    p.add_argument('--patience', type=int, default=3); p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('analyze', help='Analyze an explicitly selected statistical dataset')
    p.add_argument('kind', choices=['reliability', 'performance', 'tost', 'break-even'])
    p.add_argument('data'); p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('adaptive', help='Select next discovery configuration')
    p.add_argument('spec'); p.add_argument('history'); p.add_argument('--budget', required=True, type=float)
    p.add_argument('--seed', type=int, default=0); p.add_argument('--strategy', choices=['gp', 'random', 'novelty'], default='gp')
    p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('model', help='Optional exploratory hierarchical model')
    p.add_argument('data'); p.add_argument('--formula', required=True)
    p.add_argument('--kind', choices=['logistic', 'performance'], default='logistic')
    p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('ablate', help='Mask selected dependencies inside a container only')
    p.add_argument('spec'); p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('localize', help='Find the first divergent ordered output artifact')
    p.add_argument('pairs'); p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('classify', help='Attach evidence-backed failure diagnoses')
    p.add_argument('outcomes'); p.add_argument('annotations'); p.add_argument('-o', '--output', required=True)
    args = parser.parse_args()
    try:
        result = dispatch(args)
        if result is not None:
            write_json(args.output, result)
    except (ValueError, KeyError, OSError, ImportError, RuntimeError) as exc:
        parser.exit(2, f'evaluation: {exc}\n')


def dispatch(a):
    if a.command == 'design':
        from .design import covering_array, validation_sample
        return covering_array(read(a.spec)) if a.kind == 'coverage' else validation_sample(read(a.spec), a.count, a.seed)
    if a.command == 'run':
        from .runner import run
        print(json.dumps(run(read(a.manifest), read(a.design), a.output)))
    elif a.command == 'metamorphic':
        from .runner import run_metamorphic
        print(json.dumps(run_metamorphic(read(a.spec), a.output)))
    elif a.command == 'inventory':
        from .dependencies import inventory
        return inventory(a.trace, a.manifest, a.elf, a.linker)
    elif a.command == 'aggregate':
        from .dependencies import aggregate, selected_inventory
        from definition_generator import render_definition
        from environments import load_env_vars
        plan = aggregate(a.traces, gpu=a.gpu, mpi=a.mpi, mpi_root=a.mpi_root, command_file=a.command_file,
                         include_paths=a.include, exclude_paths=a.exclude)
        Path(a.output).write_text(render_definition(plan, load_env_vars(Path(a.env)), a.base))
        write_json(a.output+'.plan.json', dataclasses.asdict(plan))
        write_json(a.output+'.inventory.json', selected_inventory(plan))
    elif a.command == 'completeness':
        from .dependencies import completeness
        return completeness(read(a.captured), read(a.reference))
    elif a.command == 'saturation':
        from .adaptive import stopping
        return stopping(read(a.samples), a.min_runs, a.patience)
    elif a.command == 'analyze':
        from .statistics import reliability, performance, tost, break_even
        data = read(a.data)
        return {'reliability': lambda: reliability(data),
                'performance': lambda: performance(**data), 'tost': lambda: tost(**data),
                'break-even': lambda: break_even(**data)}[a.kind]()
    elif a.command == 'adaptive':
        from .adaptive import select
        return select(read(a.spec), read(a.history), a.budget, a.seed, a.strategy)
    elif a.command == 'model':
        from .models import fit
        return fit(read(a.data), a.formula, a.kind)
    elif a.command == 'ablate':
        from .diagnostics import ablate
        ablate(read(a.spec), a.output)
    elif a.command == 'localize':
        from .diagnostics import localize
        return localize(read(a.pairs))
    elif a.command == 'classify':
        from .diagnostics import classify
        return classify(read(a.outcomes), read(a.annotations))


if __name__ == '__main__':
    main()
