"""Explicit numerical oracles; nonfinite values never count as equivalent."""
import math


def flatten(value):
    if isinstance(value, list):
        return [x for item in value for x in flatten(item)]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Expected numeric scalar or nested list')
    return [float(value)]


def shape(value):
    return [shape(x) for x in value] if isinstance(value, list) else None


def compare(reference, actual, atol=0.0, rtol=0.0):
    if not all(math.isfinite(x) and x >= 0 for x in (atol, rtol)):
        raise ValueError('Tolerances must be finite and nonnegative')
    a, b = flatten(reference), flatten(actual)
    if shape(reference) != shape(actual) or not a:
        return {'equivalent': False, 'reason': 'shape mismatch or empty output'}
    if not all(math.isfinite(v) for v in a + b):
        return {'equivalent': False, 'reason': 'nonfinite output'}
    errors = [abs(x-y) for x, y in zip(a, b)]
    return {'equivalent': all(e <= atol + rtol * abs(x) for e, x in zip(errors, a)),
            'max_absolute_error': max(errors),
            'relative_l2_error': math.sqrt(sum(e*e for e in errors)) /
                                 max(math.sqrt(sum(x*x for x in a)), 1e-300)}


def metamorphic(base, transformed, relation, atol=0.0, rtol=0.0, scale=1.0, permutation=None):
    """The caller must execute and justify the corresponding input transformation."""
    if relation == 'scale':
        def mul(x):
            return [mul(v) for v in x] if isinstance(x, list) else x * scale
        expected = mul(base)
    elif relation == 'invariant':
        expected = base
    elif relation == 'permutation':
        if not isinstance(base, list) or sorted(permutation or []) != list(range(len(base))):
            raise ValueError('Permutation must contain each output index exactly once')
        expected = [base[i] for i in permutation]
    elif relation == 'split_sum':
        if not isinstance(transformed, list) or len(transformed) != 2:
            raise ValueError('split_sum requires two scalar integration results')
        transformed = sum(transformed)
        expected = base
    else:
        raise ValueError('Unknown metamorphic relation')
    return compare(expected, transformed, atol, rtol)
