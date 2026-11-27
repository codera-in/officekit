"""Route tests for the pending file tools (track A) through the existing /api/file-jobs route."""

import hashlib
import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

import app as api
from officekit.engines.engine_file_inspect import DEVELOPMENT_ONLY_KINDS
from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_file_jobs import FileJobStore

NATIVE = {'X-OfficeKit-Native-Grant': 'native-test'}
BETA_MESSAGE = 'This operation is not available in the OfficeKit private beta.'
DEVELOPMENT_KINDS = ('file-info', 'compare-files', 'file-age', 'empty-files', 'empty-folders', 'symlinks')


@pytest.fixture
def client_for(tmp_path, monkeypatch):
    """Build a client whose file job store runs under the requested release profile."""
    created = []

    def build(profile='development'):
        selections = FileSelectionStore(native_token='native-test')
        jobs = FileJobStore(selections, release_profile=profile)
        monkeypatch.setattr(api, 'file_selection_store', selections)
        monkeypatch.setattr(api, 'file_job_store', jobs)
        created.append((jobs, selections))
        return TestClient(api.app), selections, jobs

    yield build
    for jobs, selections in created:
        jobs.close()
        selections.close()


def poll(client, key):
    for _ in range(400):
        state = client.get(f'/api/file-jobs/{key}').json()
        if state['state'] not in {'queued', 'running'}:
            return state
        time.sleep(.005)
    pytest.fail('Job did not terminate')


def select(client, paths):
    response = client.post('/api/file-selections', headers=NATIVE, json={'paths': [str(path) for path in paths]})
    assert response.status_code == 201
    return response.json()['id']


def submit(client, body):
    return client.post('/api/file-jobs', json=body)


def test_metadata_kinds_run_through_the_job_route(client_for, tmp_path):
    client, _selections, _jobs = client_for()
    (tmp_path / 'note.txt').write_text('hello')
    (tmp_path / 'empty.txt').write_bytes(b'')
    ref = select(client, [tmp_path])

    created = submit(client, {'kind': 'file-info', 'selectionIds': [ref], 'options': {'includeSubfolders': False}})
    assert created.status_code == 202
    state = poll(client, created.json()['id'])
    assert state['state'] == 'ready'
    page = client.get(f"/api/file-jobs/{created.json()['id']}/results?limit=1").json()
    assert page['total_files'] == 2
    assert len(page['files']) == 1 and page['hasMore'] is True

    empties = submit(client, {'kind': 'empty-files', 'selectionIds': [ref]}).json()['id']
    assert poll(client, empties)['state'] == 'ready'
    assert [row['name'] for row in client.get(f'/api/file-jobs/{empties}/results').json()['files']] == ['empty.txt']

    ages = submit(client, {'kind': 'file-age', 'selectionIds': [ref], 'options': {'notBefore': 0}}).json()['id']
    assert poll(client, ages)['state'] == 'ready'
    assert client.get(f'/api/file-jobs/{ages}/results').json()['matched'] == 2


def test_compare_and_empty_folder_results_over_http(client_for, tmp_path):
    client, _selections, _jobs = client_for()
    payload = os.urandom(3 * 1024 * 1024)
    left, right = tmp_path / 'left.bin', tmp_path / 'right.bin'
    left.write_bytes(payload)
    right.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
    (tmp_path / 'folder' / 'nested').mkdir(parents=True)
    before = (left.read_bytes(), right.read_bytes())

    pair = submit(client, {'kind': 'compare-files', 'selectionIds': [select(client, [left]), select(client, [right])]})
    assert pair.status_code == 202
    assert poll(client, pair.json()['id'])['state'] == 'ready'
    report = client.get(f"/api/file-jobs/{pair.json()['id']}/results").json()
    assert report['equal'] is False
    assert report['first_difference_offset'] == len(payload) - 1
    assert report['sha256_a'] == hashlib.sha256(payload).hexdigest()
    assert (left.read_bytes(), right.read_bytes()) == before

    folder_ref = select(client, [tmp_path / 'folder'])
    empty = submit(client, {'kind': 'empty-folders', 'selectionIds': [folder_ref]}).json()['id']
    assert poll(client, empty)['state'] == 'ready'
    folders = {row['name']: row for row in client.get(f'/api/file-jobs/{empty}/results').json()['folders']}
    assert set(folders) == {'folder', 'nested'}
    assert folders['folder']['nested_empty_folders'] == 1
    assert folders['nested']['depth'] == 1


def test_empty_folder_reveal_requires_native_authority(client_for, tmp_path):
    client, _selections, _jobs = client_for()
    (tmp_path / 'box' / 'lonely').mkdir(parents=True)
    key = submit(client, {'kind': 'empty-folders', 'selectionIds': [select(client, [tmp_path / 'box'])]}).json()['id']
    assert poll(client, key)['state'] == 'ready'
    rows = {row['name']: row for row in client.get(f'/api/file-jobs/{key}/results').json()['folders']}
    item_id = rows['lonely']['id']
    reveal = f'/api/file-jobs/{key}/reveals'
    assert client.post(reveal, json={'itemId': item_id}).status_code == 403
    response = client.post(reveal, headers=NATIVE, json={'itemId': item_id})
    assert response.status_code == 200
    assert response.json()['path'] == str(tmp_path / 'box' / 'lonely')


@pytest.mark.parametrize('kind,options,count', [
    ('file-info', {'includeSubfolders': 'yes'}, 1),
    ('file-info', {'path': '/etc'}, 1),
    ('file-age', {}, 1),
    ('file-age', {'notBefore': 9, 'notAfter': 8}, 1),
    ('file-age', {'notAfter': 253402300800}, 1),
    ('file-age', {'dateField': 'accessed', 'notBefore': 1}, 1),
    ('empty-files', {'recursive': True}, 1),
    ('empty-folders', {'includeSubfolders': False}, 1),
    ('symlinks', {'includeSubfolders': 'yes'}, 1),
    ('symlinks', {'path': '/etc'}, 1),
    ('symlinks', {}, 2),
    ('compare-files', {}, 1),
    ('empty-folders', {}, 2),
])
def test_metadata_kinds_reject_bad_bodies_with_422(client_for, tmp_path, kind, options, count):
    client, _selections, _jobs = client_for()
    (tmp_path / 'a.txt').write_text('a')
    (tmp_path / 'b.txt').write_text('b')
    refs = [select(client, [tmp_path / 'a.txt']), select(client, [tmp_path / 'b.txt'])][:count]
    assert submit(client, {'kind': kind, 'selectionIds': refs, 'options': options}).status_code == 422


@pytest.mark.parametrize('selection_ids', ['x', []])
def test_selection_shape_is_validated_before_queueing(client_for, selection_ids):
    client, _selections, _jobs = client_for()
    assert submit(client, {'kind': 'file-info', 'selectionIds': selection_ids}).status_code == 422


def test_inspect_kinds_are_forbidden_under_private_beta_only(client_for, tmp_path):
    beta, _selections, _jobs = client_for('private-beta')
    (tmp_path / 'a.txt').write_text('a')
    (tmp_path / 'b.txt').write_text('b')
    ref = select(beta, [tmp_path])
    first, second = select(beta, [tmp_path / 'a.txt']), select(beta, [tmp_path / 'b.txt'])
    options = {'file-age': {'notBefore': 0}}
    for kind in DEVELOPMENT_KINDS:
        selections = [first, second] if kind == 'compare-files' else [ref]
        response = submit(beta, {'kind': kind, 'selectionIds': selections, 'options': options.get(kind, {})})
        assert response.status_code == 403, kind
        assert response.json()['detail'] == BETA_MESSAGE
    assert submit(beta, {'kind': 'hash', 'selectionIds': [ref]}).status_code == 202


SHIPPED_BETA_PROBE = '''
import json
import uuid
from fastapi.testclient import TestClient
import app as api
from officekit.engines.engine_file_inspect import DEVELOPMENT_ONLY_KINDS
from officekit.engines.engine_license_gate import GATE_STATE
GATE_STATE.install('paid', [], 3600)
client = TestClient(api.app)
result = {'profile': api.RELEASE_PROFILE.name, 'store_profile': api.file_job_store.release_profile, 'answers': {}}
for kind in sorted(DEVELOPMENT_ONLY_KINDS):
    selections = [str(uuid.uuid4()), str(uuid.uuid4())] if kind == 'compare-files' else [str(uuid.uuid4())]
    options = {'notBefore': 0} if kind == 'file-age' else {}
    response = client.post('/api/file-jobs', json={'kind': kind, 'selectionIds': selections, 'options': options})
    result['answers'][kind] = [response.status_code, response.json().get('detail')]
print(json.dumps(result))
'''


def test_shipped_private_beta_wiring_refuses_every_development_kind():
    # QA-4 / PM-5: run the shipped app.py wiring (not a test-built store) under OFFICEKIT_RELEASE_PROFILE=private-beta.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, 'OFFICEKIT_RELEASE_PROFILE': 'private-beta'}
    completed = subprocess.run([sys.executable, '-c', SHIPPED_BETA_PROBE], cwd=repo, env=env, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-2000:]
    probe = json.loads(completed.stdout.strip().splitlines()[-1])
    assert probe['profile'] == 'private-beta'
    assert probe['store_profile'] == 'private-beta'
    assert set(probe['answers']) == set(DEVELOPMENT_KINDS)
    for kind in DEVELOPMENT_KINDS:
        assert probe['answers'][kind] == [403, BETA_MESSAGE], kind


def test_development_profile_runs_every_inspect_kind(client_for, tmp_path):
    dev, _selections, _jobs = client_for('development')
    (tmp_path / 'a.txt').write_text('a')
    ref = select(dev, [tmp_path])
    assert set(DEVELOPMENT_KINDS) == DEVELOPMENT_ONLY_KINDS
    for kind in ('file-info', 'file-age', 'empty-files', 'empty-folders', 'symlinks'):
        options = {'notBefore': 0} if kind == 'file-age' else {}
        response = submit(dev, {'kind': kind, 'selectionIds': [ref], 'options': options})
        assert response.status_code == 202, kind
        assert poll(dev, response.json()['id'])['state'] == 'ready', kind


def test_symlink_inspector_pages_its_links_over_http(client_for, tmp_path):
    client, _selections, _jobs = client_for()
    folder = tmp_path / 'project'
    (folder / 'src' / 'releases').mkdir(parents=True)
    (folder / 'src' / 'current').symlink_to('releases')
    (folder / 'src' / 'gone').symlink_to('missing')
    (folder / 'src' / 'outside').symlink_to(tmp_path / 'elsewhere')
    ref = select(client, [folder])
    key = submit(client, {'kind': 'symlinks', 'selectionIds': [ref], 'options': {'includeSubfolders': True}}).json()['id']
    assert poll(client, key)['state'] == 'ready'
    page = client.get(f'/api/file-jobs/{key}/results?limit=2').json()
    assert page['total_links'] == 3
    assert page['resolves_inside'] == 1 and page['broken_or_circular'] == 1 and page['outside_selection'] == 1
    assert page['hasMore'] is True and len(page['links']) == 2
    assert [row['relative_path'] for row in page['links']] == ['src/current', 'src/gone']
    assert client.get(f'/api/file-jobs/{key}/results?offset=2&limit=2').json()['links'][0]['state'] == 'out-of-scope'


def test_symlink_inspector_on_a_file_fails_with_the_fixed_message(client_for, tmp_path):
    client, _selections, _jobs = client_for()
    (tmp_path / 'single.txt').write_text('x')
    key = submit(client, {'kind': 'symlinks', 'selectionIds': [select(client, [tmp_path / 'single.txt'])]}).json()['id']
    state = poll(client, key)
    assert state['state'] == 'failed'
    assert state['error'] == 'Choose a folder to inspect links'


def test_single_file_folder_mismatch_fails_the_job_with_the_fixed_message(client_for, tmp_path):
    client, _selections, _jobs = client_for()
    folder = tmp_path / 'folder'
    folder.mkdir()
    (folder / 'x.txt').write_text('x')
    single = tmp_path / 'single.txt'
    single.write_text('y')
    key = submit(client, {'kind': 'compare-files', 'selectionIds': [select(client, [folder]), select(client, [single])]}).json()['id']
    state = poll(client, key)
    assert state['state'] == 'failed'
    assert state['error'] == 'Choose two single files to compare'
