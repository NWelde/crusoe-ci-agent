from unittest.mock import Mock

import pytest

from ci_agent.github.fork_experiment import prepare_fork_experiment


def test_common_preparation_is_shared_before_variant_branches(monkeypatch):
    monkeypatch.setattr('ci_agent.github.fork_experiment._content_text', lambda _: 'on: push\njobs: {}\n')
    client = Mock()
    client.authenticated_user.return_value = {'login': 'team'}
    client.repository.return_value = {'full_name': 'team/fork', 'parent': {'full_name': 'owner/repo'}}
    client.default_branch.return_value = ('master', 'upstream-sha')
    client.get_contents.return_value = {'sha': 'blob'}
    client.put_file.side_effect = [
        {'commit': {'sha': 'repaired-sha'}},
        {'commit': {'sha': 'baseline-sha'}},
        {'commit': {'sha': 'candidate-sha'}},
    ]
    client.workflow.return_value = {'id': 1}
    prepared = prepare_fork_experiment(
        client, 'owner/repo', '.github/workflows/ci.yml', 'on: push\njobs: {}\n',
        run_key='test', existing_fork='team/fork', common_source_files={'Gemfile': 'gemspec\n'},
    )
    branches = client.create_branch.call_args_list
    assert branches[0].args[-1] == 'upstream-sha'
    assert [call.args[-1] for call in branches[1:]] == ['repaired-sha', 'repaired-sha']
    assert prepared.base_sha == 'repaired-sha'
    assert client.put_file.call_args_list[0].args[2:4] == ('Gemfile', 'gemspec\n')


@pytest.mark.parametrize('path', ['../Gemfile', '/Gemfile', '.git/config', '.github/workflows/ci.yml', 'C:/Gemfile'])
def test_common_preparation_rejects_unsafe_files_before_mutation(path):
    client = Mock()
    with pytest.raises(ValueError, match='Common source'):
        prepare_fork_experiment(
            client, 'owner/repo', '.github/workflows/ci.yml', 'on: push\n',
            run_key='test', common_source_files={path: 'text'},
        )
    client.authenticated_user.assert_not_called()
