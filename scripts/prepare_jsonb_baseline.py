"""Generate explicit, reproducible JSONB baseline repairs without GitHub writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_agent.github.fork_experiment import _content_text
from ci_agent.github.runs import GitHubClient


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f'Expected exactly one source pattern: {old!r}')
    return text.replace(old, new, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sha', default='cef7a810a48ce9c3b8a79015591fddfb1a963e5a')
    parser.add_argument('--output', type=Path, default=Path('artifacts/e2e-jsonb/baseline-fixes.json'))
    args = parser.parse_args()
    client = GitHubClient.from_git_credential()
    repairs = {}
    for path, cop, statement in (
        ('Rakefile', 'Style/MixinUsage', 'include ActiveRecord::Tasks'),
        ('bin/console', 'Lint/UselessAssignment', 'x = Product.new'),
    ):
        original = _content_text(client.get_contents('madeintandem', 'jsonb_accessor', path, args.source_sha))
        repairs[path] = replace_once(
            original,
            f'# rubocop:disable {cop}\n{statement}\n# rubocop:enable {cop}\n',
            f'# rubocop:disable-next {cop}\n{statement}\n',
        )
    path = 'spec/spec_helper.rb'
    original = _content_text(client.get_contents('madeintandem', 'jsonb_accessor', path, args.source_sha))
    repairs[path] = replace_once(replace_once(original, '# rubocop:disable Style/OneClassPerFile\n', ''), '# rubocop:enable Style/OneClassPerFile\n', '')
    original = _content_text(client.get_contents('madeintandem', 'jsonb_accessor', 'Gemfile', args.source_sha))
    if 'gem "json"' in original or "gem 'json'" in original:
        raise ValueError('Source already declares JSON; inspect compatibility before preparing')
    repairs['Gemfile'] = replace_once(
        original, '\ngemspec\n',
        '\ngemspec\n\n# Rails versions in the CI matrix require the JSON 2 API.\ngem "json", "< 3"\n',
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(repairs, indent=2) + '\n', encoding='utf-8')
    print(f'Prepared {len(repairs)} common source repairs from {args.source_sha}: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
