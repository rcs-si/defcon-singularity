"""Standalone Python 3.6+ controlled workload, copied individually into images.

Every listed data file is necessary for its branch; source-relative absolute
paths make a missing image dependency fail even if the working directory changes.
"""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--size', type=int, required=True)
    p.add_argument('--algorithm', choices=['basic', 'special'], required=True)
    p.add_argument('--feature', choices=['off', 'on'], required=True)
    args = p.parse_args()
    names = ['common.json']
    if args.algorithm == 'special':
        names.append('special.json')
    if args.feature == 'on':
        names.append('feature.json')
    if args.algorithm == 'special' and args.feature == 'on' and args.size >= 8:
        names.append('interaction.json')
    root = Path(__file__).resolve().parent
    coefficients = [json.loads((root / name).read_text())['coefficient'] for name in names]
    print(json.dumps({'result': sum(coefficients) * args.size * (args.size + 1) // 2,
                      'required_dependencies': [str(root / name) for name in names]}))


if __name__ == '__main__':
    main()
