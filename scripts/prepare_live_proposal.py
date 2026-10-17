"""Prepare a pinned, independently reviewed live workflow experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from ci_agent.experiments.live_setup import prepare_e2e


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default='madeintandem/jsonb_accessor')
    parser.add_argument('--output', type=Path, default=Path('artifacts/final-e2e'))
    parser.add_argument('--template', type=Path, default=Path('config/contract-request.example.json'))
    args = parser.parse_args()
    prepare_e2e(repository=args.repository, output=args.output, template=args.template)


if __name__ == '__main__':
    main()
