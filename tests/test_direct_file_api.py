import os
import zipfile
from fastapi.testclient import TestClient
import app as api
from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_file_jobs import FileJobStore
import pytest
from unittest.mock import Mock


@pytest.fixture
def direct_client(tmp_path, monkeypatch):
    selections = FileSelectionStore(native_token='native-test')
    jobs = FileJobStore(selections, release_profile='development')
    monkeypatch.setattr(api, 'file_selection_store', selections)
    monkeypatch.setattr(api, 'file_job_store', jobs)
    with TestClient(api.app) as client:
        yield client, selections, jobs
    jobs.close()
    selections.close()


def test_direct_routes_validate_bodies_and_paging(direct_client, tmp_path):
    client, selections, jobs = direct_client
    headers = {'X-OfficeKit-Native-Grant': 'native-test'}
    source = tmp_path / 'original'
    source.write_bytes(b'hello')
    for body in ({'paths': []}, {'paths': [str(source)], 'unknown': True}, {'paths': [str(source)], 'access': 'all'}):
        assert client.post('/api/file-selections', headers=headers, json=body).status_code == 422
    created = client.post('/api/file-selections', headers=headers, json={'paths': [str(source)]})
    assert created.headers['location'] == '/api/file-selections/' + created.json()['id']
    ref = created.json()['id']
    for query in ('limit=201', 'limit=0', 'offset=-1'):
        assert client.get(f'/api/file-selections/{ref}?{query}').status_code == 422
    assert client.post('/api/file-jobs', json={'kind': 'hash', 'selectionIds': [ref], 'options': {'path': str(source)}}).status_code == 422
    assert client.post('/api/file-jobs', json={'kind': 'hash', 'selectionIds': ['bad']}).status_code == 422
    for path in ('/api/file-jobs/missing', '/api/file-jobs/missing/results'):
        assert client.get(path).status_code == 404
    assert client.post('/api/file-jobs/missing/cancellations', json={}).status_code == 404
    assert client.delete('/api/file-selections/missing').status_code == 404


def test_file_intake_content_and_subsets_use_manifest_ids_only(direct_client, tmp_path):
    client, selections, _jobs = direct_client
    original_open_file = selections.open_file
    first = tmp_path / 'first.pdf'
    second = tmp_path / 'second.pdf'
    first.write_bytes(b'%PDF-1.7 first fixture')
    second.write_bytes(b'%PDF-1.7 second fixture')
    selection = selections.register_native([str(first), str(second)], credential='native-test')
    manifest = client.get(f"/api/file-selections/{selection['id']}?limit=30").json()
    assert [item['name'] for item in manifest['files']] == ['1/first.pdf', '2/second.pdf']

    subset = client.post(
        f"/api/file-selections/{selection['id']}/subsets",
        json={'fileIds': [manifest['files'][1]['id']]},
    )
    assert subset.status_code == 201
    assert subset.json()['displayNames'] == ['second.pdf']
    assert 'path' not in subset.text

    content = client.get(
        f"/api/file-selections/{selection['id']}/files/{manifest['files'][0]['id']}/content"
    )
    assert content.status_code == 200
    assert content.content == first.read_bytes()
    assert content.headers['content-type'] == 'application/octet-stream'
    assert content.headers['cache-control'] == 'no-store'
    assert content.headers['x-content-type-options'] == 'nosniff'
    assert 'filename="first.pdf"' in content.headers['content-disposition']
    assert str(tmp_path) not in content.headers['content-disposition']
    assert client.post(f"/api/file-selections/{selection['id']}/subsets", json={'fileIds': [manifest['files'][0]['id'], manifest['files'][0]['id']]}).status_code == 422
    assert client.post(f"/api/file-selections/{selection['id']}/subsets", json={'fileIds': [manifest['files'][0]['id']], 'paths': [str(first)]}).status_code == 422
    assert client.get(f"/api/file-selections/{selection['id']}/files/00000000-0000-0000-0000-000000000000/content").status_code == 404


def test_file_intake_content_errors_are_mapped_before_streaming(direct_client, tmp_path, monkeypatch):
    from contextlib import contextmanager

    client, selections, _jobs = direct_client
    original_open_file = selections.open_file
    source = tmp_path / 'selected.pdf'
    source.write_bytes(b'12345')
    selection = selections.register_native([str(source)], credential='native-test')
    item = client.get(f"/api/file-selections/{selection['id']}?limit=30").json()['files'][0]
    url = f"/api/file-selections/{selection['id']}/files/{item['id']}/content"

    monkeypatch.setattr(api, 'MAX_API_UPLOAD_BYTES', 4)
    assert client.get(url).status_code == 413
    monkeypatch.setattr(api, 'MAX_API_UPLOAD_BYTES', 64 * 1024 * 1024)

    @contextmanager
    def unreadable(_item):
        raise PermissionError('denied')
        yield

    monkeypatch.setattr(selections, 'open_file', unreadable)
    assert client.get(url).status_code == 403
    monkeypatch.setattr(selections, 'open_file', original_open_file)

    original_find = selections.find_file

    def replace_after_lookup(selection_id, file_id):
        selected = original_find(selection_id, file_id)
        source.write_bytes(b'other')
        return selected

    monkeypatch.setattr(selections, 'find_file', replace_after_lookup)
    assert client.get(url).status_code == 422
    assert client.get('/api/file-selections/00000000-0000-0000-0000-000000000000/files/00000000-0000-0000-0000-000000000000/content').status_code == 404


def test_file_intake_content_openapi_declares_binary_success(direct_client):
    _client, _selections, _jobs = direct_client
    api.app.openapi_schema = None
    operation = api.app.openapi()['paths']['/api/file-selections/{selection_id}/files/{file_id}/content']['get']
    assert operation['responses']['200']['content']['application/octet-stream']['schema'] == {'type': 'string', 'format': 'binary'}


def test_archive_capability_route_and_native_zip_listing(direct_client, tmp_path):
    client, selections, _jobs = direct_client
    formats = client.get('/api/archive-formats')
    assert formats.status_code == 200
    capabilities = {item['id']: item for item in formats.json()['formats']}
    assert len(capabilities) == 42
    assert capabilities['zip']['extract'] == 'supported'
    assert capabilities['sitx']['extract'] == 'unsupported'

    archive = tmp_path / 'sample.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('folder/hello.txt', 'archive fixture')
    selection_id = selections.register_native([str(archive)], credential='native-test')['id']
    response = client.get(f'/api/file-selections/{selection_id}/archive-entries')

    assert response.status_code == 200
    listing = response.json()
    assert listing['format'] == 'zip'
    assert listing['total'] == 1
    assert listing['entries'][0]['name'] == 'folder/hello.txt'
    assert listing['entries'][0]['extractable'] is True


def test_finder_location_requires_native_authority_and_scan_item(direct_client, tmp_path, monkeypatch):
    client, selections, jobs = direct_client
    from tests.test_file_jobs_unittest import await_job
    for name in ['a', 'b']:
        (tmp_path / name).write_text('same')
    selection = selections.register_native([str(tmp_path)], credential='native-test')['id']
    key = jobs.submit({'kind':'duplicates', 'selectionIds':[selection]})['id']
    assert await_job(jobs, key)['state'] == 'ready'
    entry = jobs.result(key)['groups'][0]['entries'][0]
    url = f'/api/file-jobs/{key}/reveals'
    body = {'itemId':entry['id']}
    assert client.post(url, json=body).status_code == 403
    headers = {'X-OfficeKit-Native-Grant':'native-test'}
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200
    assert response.json() == {'path':str(tmp_path / entry['name'])}
    assert client.post(url, headers=headers, json={**body, 'path':'/private/other'}).status_code == 422
    assert client.post(url, headers=headers, json={'itemId':'../other'}).status_code == 422
    (tmp_path / entry['name']).write_text('changed')
    assert client.post(url, headers=headers, json=body).status_code == 409


def test_duplicate_cleanup_http_binds_scan_write_grant_and_retained_file(direct_client, tmp_path, monkeypatch):
    client, selections, jobs = direct_client
    source = tmp_path / 'selected'
    source.mkdir()
    for name in ['original.txt', 'original copy.txt']:
        (source / name).write_text('same fixture')
    trash = tmp_path / 'fixture-trash'
    trash.mkdir()
    jobs.trash = lambda path, expected: os.rename(path, trash / os.path.basename(path))
    pending = []
    monkeypatch.setattr(jobs.executor, 'submit', lambda *args: pending.append(args))
    selection = selections.register_native([str(source)], 'read-write', 'native-test')['id']
    scan = client.post('/api/file-jobs', json={'kind': 'duplicates', 'selectionIds': [selection]}).json()['id']
    function, job, grant = pending.pop()
    function(job, grant)
    entries = client.get(f'/api/file-jobs/{scan}/results').json()['groups'][0]['entries']
    body = {'kind': 'duplicate-trash', 'selectionIds': [selection], 'options': {'sourceJobId': scan, 'fileIds': [entry['id'] for entry in entries]}}
    assert client.post('/api/file-jobs', json=body).status_code == 422
    body['options']['fileIds'] = [entries[1]['id']]
    selections.get(selection).access = 'read'
    assert client.post('/api/file-jobs', json=body).status_code == 403
    selections.get(selection).access = 'read-write'
    response = client.post('/api/file-jobs', json=body)
    assert response.status_code == 202
    function, job, grant = pending.pop()
    function(job, grant)
    result = client.get(f"/api/file-jobs/{response.json()['id']}/results?format=json")
    assert result.status_code == 200
    assert result.json()['moved_count'] == 1
    assert result.json()['items'][0]['state'] == 'trashed'
    assert (source / 'original.txt').read_text() == 'same fixture'
    assert (trash / 'original copy.txt').read_text() == 'same fixture'


def test_job_route_complete_snapshot_and_cancellation(direct_client, tmp_path, monkeypatch):
    client, selections, jobs = direct_client
    source = tmp_path / 'original'
    source.write_bytes(b'hello')
    ref = selections.register_native([str(source)], credential='native-test')['id']
    tasks = []
    monkeypatch.setattr(jobs.executor, 'submit', lambda *args: tasks.append(args))
    created = client.post('/api/file-jobs', json={'kind': 'hash', 'selectionIds': [ref]})
    assert created.status_code == 202
    key = created.json()['id']
    assert client.get(f'/api/file-jobs/{key}').json()['state'] == 'queued'
    assert client.get(f'/api/file-jobs/{key}/results').status_code == 409
    assert client.get(f'/api/file-jobs/{key}/results?format=json').status_code == 409
    function, job, grant = tasks.pop()
    function(job, grant)
    page = client.get(f'/api/file-jobs/{key}/results')
    assert page.status_code == 200
    assert page.json()['total_bytes'] == 5
    complete = client.get(f'/api/file-jobs/{key}/results?format=json')
    assert complete.status_code == 200
    assert 'file-result.json' in complete.headers['content-disposition']
    assert complete.json()['files'] == page.json()['files']
    assert client.get(f'/api/file-jobs/{key}/results?format=unsupported').status_code == 422
    assert client.get(f'/api/file-jobs/{key}/results?limit=201').status_code == 422
    assert client.post(f'/api/file-jobs/{key}/cancellations', json={}).status_code == 409
    created = client.post('/api/file-jobs', json={'kind': 'hash', 'selectionIds': [ref]})
    key = created.json()['id']
    assert client.post(f'/api/file-jobs/{key}/cancellations', json={}).status_code == 202
    function, job, grant = tasks.pop()
    function(job, grant)
    assert client.get(f'/api/file-jobs/{key}').json()['state'] == 'cancelled'


def test_native_output_grant_and_mutation_revoke_guard(direct_client, tmp_path, monkeypatch):
    client, selections, jobs = direct_client
    destination = tmp_path / 'output'
    body = {'path': str(destination), 'kind': 'file', 'job_kind': 'archive-create', 'overwrite': False}
    assert client.post('/api/file-output-grants', json=body).status_code == 403
    assert client.post('/api/file-output-grants', headers={'X-OfficeKit-Native-Grant': 'native-test'}, json={**body, 'overwrite': True}).status_code == 422
    created = client.post('/api/file-output-grants', headers={'X-OfficeKit-Native-Grant': 'native-test'}, json=body)
    assert created.status_code == 201
    assert str(tmp_path) not in created.text
    assert created.headers['location'].endswith(created.json()['id'])
    source = tmp_path / 'source'
    source.write_bytes(b'hello')
    ref = selections.register_native([str(source)], credential='native-test')['id']
    tasks = []
    monkeypatch.setattr(jobs.executor, 'submit', lambda *args: tasks.append(args))
    result = client.post('/api/file-jobs', json={'kind': 'hash', 'selectionIds': [ref]})
    key = result.json()['id']
    jobs.jobs[key].mutation = True
    assert client.delete(f'/api/file-selections/{ref}').status_code == 409
    jobs.jobs[key].mutation = False
    assert client.delete(f'/api/file-selections/{ref}').status_code == 204
    assert jobs.jobs[key].cancel.is_set()
    function, job, grant = tasks.pop()
    function(job, grant)


@pytest.mark.parametrize('target,method,url,body', [
    ('file_selection_store.register_native', 'post', '/api/file-selections', {'paths': ['/approved/native/path']}),
    ('file_selection_store.register_output', 'post', '/api/file-output-grants', {'path': '/approved/native/output', 'kind': 'file', 'job_kind': 'archive-create'}),
    ('file_selection_store.metadata', 'get', '/api/file-selections/id', None),
    ('file_job_store.revoke_selection', 'delete', '/api/file-selections/id', None),
    ('file_job_store.submit', 'post', '/api/file-jobs', {'kind': 'hash', 'selectionIds': ['00000000-0000-0000-0000-000000000000']}),
    ('file_job_store.status', 'get', '/api/file-jobs/id', None),
    ('file_job_store.cancel', 'post', '/api/file-jobs/id/cancellations', {}),
    ('file_job_store.result', 'get', '/api/file-jobs/id/results', None),
    ('file_job_store.export', 'get', '/api/file-jobs/id/results?format=json', None),
])
@pytest.mark.parametrize('failure,status', [(PermissionError,403), (FileExistsError,409), (FileNotFoundError,404), (RuntimeError,409), (OSError,422), (ValueError,422)])
def test_direct_routes_map_engine_failures_without_paths(direct_client, monkeypatch, target, method, url, body, failure, status):
    client, selections, jobs = direct_client
    owner_name, attribute = target.split('.')
    owner = getattr(api, owner_name)
    stub = Mock(side_effect=failure('/private/sensitive/path'))
    monkeypatch.setattr(owner, attribute, stub)
    response = getattr(client, method)(url, **({'json': body} if body is not None else {}))
    expected = 503 if failure is RuntimeError else status
    assert response.status_code == expected
    assert '/private/sensitive/path' not in response.text
    stub.assert_called_once()


def test_cancellation_requires_strict_empty_object(direct_client, monkeypatch):
    client, selections, jobs = direct_client
    stub = Mock(return_value={'id': 'job', 'cancellationRequested': True})
    monkeypatch.setattr(jobs, 'cancel', stub)
    for body in ({'path': '/arbitrary'}, [], 'cancel', None):
        response = client.post('/api/file-jobs/job/cancellations', json=body)
        assert response.status_code == 422
    stub.assert_not_called()
    assert client.post('/api/file-jobs/job/cancellations', json={}).status_code == 202


def test_webview_bearer_cannot_issue_native_grants(direct_client, tmp_path, monkeypatch):
    client, selections, jobs = direct_client
    monkeypatch.setattr(api, 'API_AUTH_TOKEN', 'webview-token')
    source = tmp_path / 'source'
    source.write_bytes(b'hello')
    body = {'paths': [str(source)]}
    assert client.post('/api/file-selections', headers={'X-OfficeKit-Native-Grant': 'native-test'}, json=body).status_code == 401
    assert client.post('/api/file-selections', headers={'Authorization': 'Bearer webview-token'}, json=body).status_code == 403
    assert client.post('/api/file-selections', headers={'Authorization': 'Bearer webview-token', 'X-OfficeKit-Native-Grant': 'webview-token'}, json=body).status_code == 403
    created = client.post('/api/file-selections', headers={'Authorization': 'Bearer webview-token', 'X-OfficeKit-Native-Grant': 'native-test'}, json=body)
    assert created.status_code == 201
    key = created.json()['id']
    assert client.get(f'/api/file-selections/{key}').status_code == 401
    assert client.get(f'/api/file-selections/{key}', headers={'Authorization': 'Bearer webview-token'}).status_code == 200

def test_native_registration_is_required_and_scans_original(tmp_path, monkeypatch):
    path = tmp_path / 'original.txt'
    path.write_text('hello', encoding='utf-8')
    selections = FileSelectionStore(native_token='native-test')
    jobs = FileJobStore(selections, release_profile='development')
    monkeypatch.setattr(api, 'file_selection_store', selections, raising=False)
    monkeypatch.setattr(api, 'file_job_store', jobs, raising=False)
    with TestClient(api.app) as client:
        denied = client.post('/api/file-selections', json={'paths': [str(path)]})
        assert denied.status_code == 403
        created = client.post('/api/file-selections', headers={'X-OfficeKit-Native-Grant': 'native-test'}, json={'paths': [str(path)]})
        assert created.status_code == 201
        key = created.json()['id']
        assert str(tmp_path) not in created.text
        manifest = client.get(f'/api/file-selections/{key}').json()
        assert manifest['files'][0]['name'] == 'original.txt'
        assert list(tmp_path.iterdir()) == [path]
        assert client.delete(f'/api/file-selections/{key}').status_code == 204
        assert client.get(f'/api/file-selections/{key}').status_code == 404
    jobs.close()
