"""Optional exploratory hierarchical fits; inspect convergence before inference."""

def fit(rows, formula, kind='logistic'):
    import pandas as pd
    data = pd.DataFrame(rows)
    if kind == 'logistic':
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
        if set(data['success']) != {0, 1} or data['workload'].nunique() < 2:
            raise ValueError('Need both binary outcomes and multiple workloads')
        model = BinomialBayesMixedGLM.from_formula(formula, {'workload': '0 + C(workload)'}, data)
        result = model.fit_vb()
        return {'method': 'variational Bayes logistic random workload intercept',
                'summary': str(result.summary()), 'optimizer': str(result.optim_retvals),
                'warning': 'Approximate posterior with default priors; check prior sensitivity and held-out calibration.'}
    if kind == 'performance':
        import statsmodels.formula.api as smf
        if data['node'].nunique() < 2:
            raise ValueError('Mixed model needs multiple nodes')
        result = smf.mixedlm(formula, data, groups=data['node'], re_formula='1',
                             vc_formula={'workload': '0 + C(workload)'}).fit()
        return {'method': 'linear mixed model; node groups, workload within node variance component',
                'summary': str(result.summary()), 'converged': bool(result.converged)}
    raise ValueError('Unknown model')
