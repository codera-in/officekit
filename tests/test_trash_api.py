"""Restore from Trash routes: strict DTOs, native authorization, development-only."""

import os
import shutil

import pytest
from fastapi.testclient import TestClient

import app as api
from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_release_profile import load_release_profile
from officekit.engines.engine_trash_ledger import TrashLedger
from officekit.engines.engine_trash_restore import APPROVAL_MESSAGE, NATIVE_MESSAGE, TrashRestorer

NATIVE = {'X-OfficeKit-Native-Grant': 'native-test'}
BETA_MESSAGE = 'This operation is not available in the OfficeKit private beta.'
MISSING_ID = '00000000-0000-4000-8000-000000000000'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    trash = home / '.Trash'
    documents = home / 'Documents'
    trash.mkdir(parents=True)
    documents.mkdir(parents=True)
    ledger = TrashLedger(str(home / 'Library' / 'Application Support' / 'OfficeKit' / 'trash-ledger.json'))
    selections = FileSelectionStore(native_token='native-test')
    restorer = TrashRestorer(ledger, str(trash), selections, native_token='native-test')
    monkeypatch.setattr(api, 'trash_restorer', restorer)
    monkeypatch.setattr(api, 'file_selection_store', selections)
    return {'home': home, 'trash': trash, 'documents': documents, 'ledger': ledger, 'selections': selections,
            'restorer': restorer, 'client': TestClient(api.app)}


def stash(setup, name, data=b'hello'):
    source = setup['documents'] / name
    source.write_bytes(data)
    shutil.move(str(source), str(setup['trash'] / ('uuid-' + name)))
    moved = os.stat(setup['trash'] / ('uuid-' + name))
    folder = os.stat(setup['documents'])
    return setup['ledger'].add(trash_name='uuid-' + name, trash_identity=(moved.st_dev, moved.st_ino),
                               original_parent_path=str(setup['documents']),
                               original_parent_identity=(folder.st_dev, folder.st_ino),
                               original_name=name, size=len(data))['record_id']


def grant(setup, ids, destination=None):
    body = {'recordIds': ids}
    if destination is not None:
        body['destinationGrantId'] = destination
    response = setup['client'].post('/api/trash-restore-grants', headers=NATIVE, json=body)
    assert response.status_code == 201
    return response.json()['id']


def test_listing_returns_the_page_without_a_native_header(setup):
    record = stash(setup, 'listed.txt')
    response = setup['client'].get('/api/trash-records')
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1 and body['hasMore'] is False
    assert body['records'] == [{'id': record, 'name': 'listed.txt', 'original_folder_display': str(setup['documents']),
                                'moved_at': body['records'][0]['moved_at'], 'size_bytes': 5, 'state': 'restorable'}]


def test_listing_rejects_bad_paging(setup):
    client = setup['client']
    assert client.get('/api/trash-records?limit=201').status_code == 422
    assert client.get('/api/trash-records?limit=0').status_code == 422
    assert client.get('/api/trash-records?offset=-1').status_code == 422


def test_grant_needs_native_authorization_and_valid_input(setup):
    record = stash(setup, 'grant.txt')
    client = setup['client']
    assert client.post('/api/trash-restore-grants', json={'recordIds': [record]}).status_code == 403
    response = client.post('/api/trash-restore-grants', headers=NATIVE, json={'recordIds': [record]})
    assert response.status_code == 201
    assert set(response.json()) == {'id', 'expiresIn'}
    assert client.post('/api/trash-restore-grants', headers=NATIVE, json={'recordIds': []}).status_code == 422
    assert client.post('/api/trash-restore-grants', headers=NATIVE, json={'recordIds': ['bad']}).status_code == 422
    assert client.post('/api/trash-restore-grants', headers=NATIVE, json={'recordIds': [record], 'tenant': 'x'}).status_code == 422
    assert client.post('/api/trash-restore-grants', headers=NATIVE, json={'recordIds': [MISSING_ID]}).status_code == 404


def test_grant_refuses_more_than_one_hundred_items(setup):
    response = setup['client'].post('/api/trash-restore-grants', headers=NATIVE, json={'recordIds': [MISSING_ID] * 101})
    assert response.status_code == 422


def test_restorations_restore_with_a_bound_single_use_grant(setup):
    record = stash(setup, 'restored.txt', data=b'abc')
    grant_id = grant(setup, [record])
    client = setup['client']
    body = {'recordIds': [record], 'restoreGrantId': grant_id}
    assert client.post('/api/trash-restorations', json=body).status_code == 403
    response = client.post('/api/trash-restorations', headers=NATIVE, json=body)
    assert response.status_code == 201
    assert response.json() == {'items': [{'id': record, 'state': 'restored', 'reason': None,
                                          'restored_to': str(setup['documents'] / 'restored.txt')}], 'restored_bytes': 3}
    assert (setup['documents'] / 'restored.txt').read_bytes() == b'abc'
    again = client.post('/api/trash-restorations', headers=NATIVE, json=body)
    assert again.status_code == 403
    assert again.json()['detail'] == APPROVAL_MESSAGE


def test_restorations_refuse_a_forged_grant_and_bad_bodies(setup):
    record = stash(setup, 'forged.txt')
    client = setup['client']
    response = client.post('/api/trash-restorations', headers=NATIVE, json={'recordIds': [record], 'restoreGrantId': 'forged'})
    assert response.status_code == 403 and response.json()['detail'] == APPROVAL_MESSAGE
    assert client.post('/api/trash-restorations', headers=NATIVE, json={'recordIds': [record]}).status_code == 422
    assert client.post('/api/trash-restorations', headers=NATIVE, json={'recordIds': [record, record], 'restoreGrantId': 'x'}).status_code == 422


def test_restorations_report_the_native_denial_message(setup):
    record = stash(setup, 'denied.txt')
    response = setup['client'].post('/api/trash-restorations', headers={'X-OfficeKit-Native-Grant': 'wrong'},
                                    json={'recordIds': [record], 'restoreGrantId': 'x'})
    assert response.status_code == 403
    assert response.json()['detail'] == NATIVE_MESSAGE


def test_restore_to_a_chosen_folder_through_the_routes(setup, tmp_path):
    record = stash(setup, 'picked.txt', data=b'xy')
    picked = tmp_path / 'picked'
    picked.mkdir()
    output = setup['selections'].register_output(str(picked / 'picked.txt'), 'directory', 'trash-restore', credential='native-test')
    grant_id = grant(setup, [record], destination=output['id'])
    response = setup['client'].post('/api/trash-restorations', headers=NATIVE, json={'recordIds': [record], 'restoreGrantId': grant_id})
    assert response.json()['items'][0]['state'] == 'restored'
    assert (picked / 'picked.txt').read_bytes() == b'xy'


def test_restore_to_a_folder_with_a_missing_output_grant_is_not_found(setup):
    record = stash(setup, 'nofolder.txt')
    response = setup['client'].post('/api/trash-restore-grants', headers=NATIVE,
                                    json={'recordIds': [record], 'destinationGrantId': 'missing'})
    assert response.status_code == 404


def test_forgetting_needs_native_authorization_and_keeps_the_file(setup):
    record = stash(setup, 'forget-me.txt')
    client = setup['client']
    assert client.delete(f'/api/trash-records/{record}').status_code == 403
    assert client.delete(f'/api/trash-records/{record}', headers=NATIVE).status_code == 204
    assert (setup['trash'] / 'uuid-forget-me.txt').exists()
    assert client.delete(f'/api/trash-records/{record}', headers=NATIVE).status_code == 404


@pytest.mark.parametrize('method,path,body', [
    ('get', '/api/trash-records', None),
    ('post', '/api/trash-restore-grants', {'recordIds': [MISSING_ID]}),
    ('post', '/api/trash-restorations', {'recordIds': [MISSING_ID], 'restoreGrantId': 'x'}),
    ('delete', f'/api/trash-records/{MISSING_ID}', None),
])
def test_every_trash_route_is_development_only(setup, monkeypatch, method, path, body):
    monkeypatch.setattr(api, 'RELEASE_PROFILE', load_release_profile({'OFFICEKIT_RELEASE_PROFILE': 'private-beta'}))
    kwargs = {'headers': NATIVE}
    if body is not None:
        kwargs['json'] = body
    response = getattr(setup['client'], method)(path, **kwargs)
    assert response.status_code == 403
    assert response.json()['detail'] == BETA_MESSAGE


def test_trash_routes_are_listed_in_the_beta_profile_so_the_guard_answers_403():
    profile = load_release_profile({'OFFICEKIT_RELEASE_PROFILE': 'private-beta'})
    assert profile.allows('GET', '/api/trash-records')
    assert profile.allows('POST', '/api/trash-restore-grants')
    assert profile.allows('POST', '/api/trash-restorations')
    assert profile.allows('DELETE', f'/api/trash-records/{MISSING_ID}')


def test_listing_maps_engine_failures_to_fixed_errors(setup, monkeypatch):
    def unavailable(offset, limit):
        raise RuntimeError('queue full')

    monkeypatch.setattr(setup['restorer'], 'page', unavailable)
    assert setup['client'].get('/api/trash-records').status_code == 503


def test_grant_maps_denials_and_bad_requests(setup, monkeypatch):
    record = stash(setup, 'mapped.txt')
    errors = {PermissionError: 403, ValueError: 422, RuntimeError: 503, OSError: 422}
    for error_type, status in errors.items():
        def failing(body, credential, error_type=error_type):
            raise error_type('refused')

        monkeypatch.setattr(setup['restorer'], 'mint', failing)
        response = setup['client'].post('/api/trash-restore-grants', headers=NATIVE, json={'recordIds': [record]})
        assert response.status_code == status
        if status == 403:
            assert response.json()['detail'] == 'refused'


def test_restoration_and_forget_map_engine_failures(setup, monkeypatch):
    record = stash(setup, 'mapped-two.txt')

    def value_error(body, credential):
        raise ValueError('bad')

    def runtime_error(record_id, credential):
        raise RuntimeError('busy')

    monkeypatch.setattr(setup['restorer'], 'restore', value_error)
    response = setup['client'].post('/api/trash-restorations', headers=NATIVE, json={'recordIds': [record], 'restoreGrantId': 'x'})
    assert response.status_code == 422
    monkeypatch.setattr(setup['restorer'], 'forget', runtime_error)
    assert setup['client'].delete(f'/api/trash-records/{record}', headers=NATIVE).status_code == 503
