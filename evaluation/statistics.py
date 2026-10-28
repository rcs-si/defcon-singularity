"""Inference with explicit sampling units and prespecified equivalence margins."""
import math
import statistics
from collections import defaultdict
from statistics import NormalDist


def finite(values, minimum=1):
    values = [float(x) for x in values]
    if len(values) < minimum or not all(math.isfinite(x) for x in values):
        raise ValueError('Insufficient or nonfinite observations')
    return values


def tost(differences, lower, upper, alpha=0.05):
    from scipy.stats import t
    xs = finite(differences, 2)
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper or not 0 < alpha < .5:
        raise ValueError('Invalid equivalence bounds or alpha')
    mean = statistics.mean(xs)
    se = statistics.stdev(xs) / math.sqrt(len(xs))
    if se == 0:
        return {'equivalent': None, 'reason': 'zero sample variance; t inference undefined',
                'mean': mean, 'n': len(xs)}
    lo_p = float(t.sf((mean-lower)/se, len(xs)-1))
    hi_p = float(t.cdf((mean-upper)/se, len(xs)-1))
    radius = float(t.ppf(1-alpha, len(xs)-1)) * se
    return {'equivalent': max(lo_p, hi_p) < alpha, 'p_value': max(lo_p, hi_p),
            'p_lower': lo_p, 'p_upper': hi_p, 'mean': mean, 'n': len(xs),
            'ci': [mean-radius, mean+radius], 'ci_level': 1-2*alpha,
            'bounds': [lower, upper]}


def performance(pairs, ratio_bounds=None, alpha=.05):
    """One independent block per pair; average repeats within blocks beforehand."""
    from scipy.stats import t
    if not 0 < alpha < .5:
        raise ValueError('Invalid alpha')
    logs = []
    for native, container in pairs:
        a, b = finite([native, container], 2)
        if min(a, b) <= 0:
            raise ValueError('Runtimes must be positive')
        logs.append(math.log(b/a))
    finite(logs, 2)
    mean = statistics.mean(logs)
    se = statistics.stdev(logs) / math.sqrt(len(logs))
    radius = float(t.ppf(1-alpha/2, len(logs)-1)) * se
    result = {'blocks': len(logs), 'geometric_mean_ratio': math.exp(mean),
              'ci': [math.exp(mean-radius), math.exp(mean+radius)], 'ci_level': 1-alpha}
    if ratio_bounds is not None:
        if len(ratio_bounds) != 2 or min(ratio_bounds) <= 0:
            raise ValueError('Supply two positive ratio bounds')
        result['equivalence'] = tost(logs, *map(math.log, ratio_bounds), alpha)
    return result


def reliability(rows, alpha=.05):
    """Rows are independent validation draws, not repeated executions of a draw."""
    if not 0 < alpha < 1:
        raise ValueError('Invalid alpha')
    if any(r['dataset'] != 'validation' for r in rows):
        raise ValueError('Reliability requires independent validation sampling')
    if len({r['sample_id'] for r in rows}) != len(rows):
        raise ValueError('Repeated samples: aggregate technical replicates first')
    if any(type(r.get('supported')) is not bool for r in rows):
        raise ValueError('Every draw needs an explicit supported-environment decision')
    eligible = [r for r in rows if r.get('supported') is True]
    if any(type(r.get('success')) is not bool for r in eligible):
        raise ValueError('Eligible draws need boolean success; unresolved outcomes cannot be dropped')
    n = len(eligible)
    if not n:
        return {'n': 0, 'excluded': len(rows), 'estimate': None, 'ci': None}
    p = sum(r['success'] for r in eligible)/n
    z = NormalDist().inv_cdf(1-alpha/2)
    denominator = 1+z*z/n
    center = (p+z*z/(2*n))/denominator
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
    return {'n': n, 'excluded': len(rows)-n, 'estimate': p,
            'ci': [max(0., center-radius), min(1., center+radius)], 'ci_level': 1-alpha,
            'method': 'Wilson; assumes independent draws and fixed supported-environment rule'}


def break_even(trace_cost, build_cost, container_time, setup_cost, baseline_time):
    vals = finite([trace_cost, build_cost, container_time, setup_cost, baseline_time], 5)
    if min(vals) < 0:
        raise ValueError('Costs must be nonnegative and use the same units')
    intercept = trace_cost + build_cost - setup_cost
    saving = baseline_time - container_time
    if saving > 0:
        return {'minimum_reuses': max(0, math.ceil(intercept/saving)), 'lasting': True}
    if saving == 0:
        return {'minimum_reuses': 0 if intercept <= 0 else None, 'lasting': intercept <= 0}
    return {'minimum_reuses': 0 if intercept <= 0 else None, 'lasting': False,
            'maximum_reuses': math.floor(-intercept/-saving) if intercept <= 0 else None}


def paired_records(records, mode='container'):
    groups = defaultdict(dict)
    for row in records:
        key = (row['sample_id'], row['block'], row['node'])
        if row['mode'] in groups[key]:
            raise ValueError('Duplicate mode within block')
        groups[key][row['mode']] = row
    pairs, excluded = [], 0
    for group in groups.values():
        a, b = group.get('native'), group.get(mode)
        if not a or not b or a['status'] != 'completed' or b['status'] != 'completed':
            excluded += 1
        else:
            pairs.append([a['wall_seconds'], b['wall_seconds']])
    return pairs, excluded
