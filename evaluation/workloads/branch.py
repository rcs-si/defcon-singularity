"""Known branch dependency: --optional reads a distinct immutable data file."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--size', type=int, default=10)
p.add_argument('--scale', type=float, default=1)
p.add_argument('--optional', choices=['yes', 'no'], default='no')
a = p.parse_args()
source = Path(__file__).with_name('optional.json' if a.optional == 'yes' else 'ordinary.json')
coefficient = json.loads(source.read_text())['coefficient']
print(json.dumps({'result': [a.scale * coefficient * i for i in range(a.size)],
                  'dependency': str(source.resolve())}))
