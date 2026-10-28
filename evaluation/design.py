"""Constrained mixed-level covering arrays and independent validation sampling."""
import itertools
import math
import random


def candidates(spec):
    factors = spec['factors']
    if not factors or any(not values for values in factors.values()):
        raise ValueError('Provide nonempty factors and levels')
    for values in factors.values():
        if any(not isinstance(v, (str, int, float, bool)) for v in values):
            raise ValueError('Factor levels must be JSON scalars')
        if len(set(values)) != len(values):
            raise ValueError('Duplicate factor levels')
    if math.prod(map(len, factors.values())) > spec.get('max_candidates', 100000):
        raise ValueError('Candidate limit exceeded; reduce factors or use NIST ACTS')
    exclusions = spec.get('forbidden', [])
    for rule in exclusions:
        if not rule or any(k not in factors or v not in factors[k] for k, v in rule.items()):
            raise ValueError('Invalid forbidden combination')
    rows = [dict(zip(factors, vals)) for vals in itertools.product(*factors.values())]
    rows = [r for r in rows if not any(all(r[k] == v for k, v in rule.items()) for rule in exclusions)]
    if not rows:
        raise ValueError('Constraints exclude every configuration')
    return rows


def interactions(row, groups):
    return {tuple((k, row[k]) for k in group) for group in groups}


def covering_array(spec):
    rows = candidates(spec)
    names = list(spec['factors'])
    strength = spec.get('strength', min(2, len(names)))
    if not 1 <= strength <= len(names):
        raise ValueError('Invalid covering strength')
    groups = list(itertools.combinations(names, strength))
    for group in spec.get('high_risk_groups', []):
        if len(set(group)) != len(group) or not group or not set(group) <= set(names):
            raise ValueError('Invalid high-risk group')
        groups.append(tuple(group))
    covered = [interactions(r, groups) for r in rows]
    remaining = set().union(*covered)
    total = len(remaining)
    chosen = []
    while remaining:
        i = max(range(len(rows)), key=lambda j: len(covered[j] & remaining))
        chosen.append(rows[i])
        remaining -= covered[i]
    return {'dataset': 'coverage', 'configurations': chosen,
            'feasible_interactions': total, 'covered_interactions': total,
            'candidate_count': len(rows), 'groups': groups}


def validation_sample(spec, count, seed):
    if count < 1:
        raise ValueError('Sample count must be positive')
    rows = candidates(spec)
    # IID draws with replacement from the declared finite deployment distribution.
    weights = []
    level_weights = spec.get('weights', {})
    for name, ws in level_weights.items():
        if name not in spec['factors'] or len(ws) != len(spec['factors'][name]):
            raise ValueError('Weights must align with factor levels')
        if any(not math.isfinite(w) or w < 0 for w in ws):
            raise ValueError('Weights must be finite and nonnegative')
    for row in rows:
        weights.append(math.prod(level_weights.get(k, [1] * len(v))[v.index(row[k])]
                                 for k, v in spec['factors'].items()))
    if sum(weights) <= 0:
        raise ValueError('No positive feasible probability mass')
    return {'dataset': 'validation', 'seed': seed,
            'distribution': 'product of level weights conditioned on constraints',
            'spec': spec, 'configurations': random.Random(seed).choices(rows, weights, k=count)}


def blocked_order(modes, blocks, seed):
    if blocks < 1 or len(set(modes)) != len(modes) or not modes:
        raise ValueError('Provide positive blocks and distinct modes')
    rng = random.Random(seed)
    result = []
    for block in range(blocks):
        order = list(modes)
        rng.shuffle(order)
        result.extend((block, mode) for mode in order)
    return result
