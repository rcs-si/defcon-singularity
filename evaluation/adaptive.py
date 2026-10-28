"""Budgeted discovery; never a deployment reliability estimator."""
import math
import random
from .design import candidates


def select(spec, history, budget, seed=0, strategy='gp'):
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError('Budget must be positive and finite')
    rows = candidates(spec)
    if any(h.get('dataset') == 'validation' for h in history):
        raise ValueError('Held-out validation outcomes must not inform adaptive selection')
    remaining = [r for r in rows if not any(h['configuration'] == r for h in history)]
    if not remaining:
        return {'configuration': None, 'reason': 'candidate space exhausted'}
    costs = spec.get('costs', [])
    def cost(row):
        matches = [c['seconds'] for c in costs if all(row[k] == v for k, v in c['when'].items())]
        value = matches[-1] if matches else spec.get('default_cost_seconds', 1.)
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Candidate costs must be positive and finite')
        return value
    remaining = [r for r in remaining if cost(r) <= budget]
    if not remaining:
        return {'configuration': None, 'reason': 'budget exhausted'}
    if strategy == 'random' or not history:
        row = random.Random(seed).choice(remaining)
        return {'configuration': row, 'dataset': 'adaptive', 'cost': cost(row), 'acquisition': 'random exploration'}
    if strategy == 'novelty':
        # Maximin distance from previously explored settings, normalized by cost.
        def score(row):
            distances = [sum(row[k] != h['configuration'][k] for k in row)/len(row) for h in history]
            return min(distances)/cost(row)
        row = max(remaining, key=score)
        return {'configuration': row, 'dataset': 'adaptive', 'score': score(row),
                'cost': cost(row), 'acquisition': 'maximin configuration novelty per cost'}
    if strategy != 'gp':
        raise ValueError('Unknown strategy')
    labeled = [h for h in history if type(h.get('success')) is bool]
    if len({h['success'] for h in labeled}) < 2:
        return select(spec, history, budget, seed, 'novelty')
    from sklearn.gaussian_process import GaussianProcessClassifier
    from sklearn.gaussian_process.kernels import RBF
    def encode(row):
        return [float(row[k] == v) for k, levels in spec['factors'].items() for v in levels]
    model = GaussianProcessClassifier(kernel=RBF(), random_state=seed)
    model.fit([encode(h['configuration']) for h in labeled], [int(not h['success']) for h in labeled])
    probs = model.predict_proba([encode(r) for r in remaining])[:, 1]
    scores = [(-p*math.log(max(p, 1e-15))-(1-p)*math.log(max(1-p, 1e-15)))/cost(r)
              for r, p in zip(remaining, probs)]
    i = max(range(len(remaining)), key=scores.__getitem__)
    return {'configuration': remaining[i], 'dataset': 'adaptive', 'cost': cost(remaining[i]),
            'predicted_failure': float(probs[i]), 'score': float(scores[i]),
            'acquisition': 'predictive entropy per cost; heuristic, not expected information gain'}


def stopping(samples, min_runs=5, patience=3):
    """Optional discovery heuristic; never substitutes for held-out validation."""
    from .dependencies import saturation
    if min_runs < 2 or patience < 1:
        raise ValueError('Invalid stopping settings')
    report = saturation(samples)
    report['stop_suggested'] = len(samples) >= max(min_runs, patience) and all(
        row['new'] == 0 for row in report['curve'][-patience:])
    return report


def select_dependencies(spec, history, required_catalog, budget, seed=0, prior=(1., 1.), bandwidth=.5):
    """Catalog-limited required-incidence acquisition with an explicit local prior.

    Predict each not-yet-observed catalog item's activation using kernel-weighted
    Beta-Bernoulli counts. Unknown dependency identities cannot be predicted.
    With no positive observations for an unseen item, exploration is prior driven;
    this is a baseline heuristic, not a calibrated discovery guarantee.
    """
    from .dependencies import normalize
    if not math.isfinite(budget) or budget <= 0 or not math.isfinite(bandwidth) or bandwidth <= 0:
        raise ValueError('Positive finite budget and bandwidth required')
    if len(prior) != 2 or any(not math.isfinite(v) or v <= 0 for v in prior):
        raise ValueError('Beta prior parameters must be positive and finite')
    catalog = {normalize(path) for path in required_catalog}
    if not catalog:
        raise ValueError('An independently declared required-dependency catalog is required')
    rows = candidates(spec)
    for h in history:
        if h.get('dataset') != 'discovery':
            raise ValueError('Dependency acquisition accepts discovery records only, never validation')
        if h['configuration'] not in rows:
            raise ValueError('History configuration outside discovery design')
        if not isinstance(h.get('required_dependencies'), list):
            raise ValueError('Each discovery record needs a required_dependencies incidence list')
    observed = [{normalize(p) for p in h['required_dependencies']} & catalog for h in history]
    unseen = catalog - set().union(*observed)
    if not unseen:
        return {'configuration': None, 'reason': 'required catalog covered; not proof of completeness'}
    remaining = [r for r in rows if not any(h['configuration'] == r for h in history)]
    rng = random.Random(seed)
    rng.shuffle(remaining)  # Seeded tie-breaking, independent of held-out outcomes.
    ranking = []
    for row in remaining:
        cost = spec.get('default_cost_seconds', 1.)
        for rule in spec.get('costs', []):
            if all(row[k] == v for k, v in rule['when'].items()):
                cost = rule['seconds']
        if not math.isfinite(cost) or cost <= 0:
            raise ValueError('Expected cost must be positive and finite')
        if cost > budget:
            continue
        weights = [math.exp(-sum(row[k] != h['configuration'][k] for k in row)/bandwidth)
                   for h in history]
        expected = sum((prior[0] + sum(w for w, deps in zip(weights, observed) if dep in deps)) /
                       (sum(prior) + sum(weights)) for dep in unseen)
        ranking.append({'configuration': row, 'expected_new_required': expected,
                        'expected_cost_seconds': cost, 'score': expected/cost})
    if not ranking:
        return {'configuration': None, 'reason': 'candidate space or expected-cost budget exhausted'}
    best = max(ranking, key=lambda r: r['score'])
    return dict(best, dataset='discovery', acquisition='local Beta incidence expected unseen required count per cost',
                catalog_size=len(catalog), unseen_catalog_size=len(unseen), prior=list(prior), bandwidth=bandwidth,
                warning='Catalog-limited, prior-driven for never-seen dependencies; no calibrated guarantee.')
