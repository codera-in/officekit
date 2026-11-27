"""S06 review round 1: regression and guard tests for the Restore from Trash fixes.

Each test names the review comment it closes. Synthetic trees only, under tmp_path.
"""

import json
import os
import shutil
import stat
import threading
import time
import pytest
from fastapi.testclient import TestClient

import app as api
from officekit.engines import engine_trash_ledger as ledger_module
from officekit.engines import engine_trash_restore as restore_module
from officekit.engines.engine_file_selections import FileSelectionStore, identity
from officekit.engines.engine_storage_cleaner import UNRECORDED_TRASH_MESSAGE, StorageCleaner
from officekit.engines.engine_trash_ledger import TTL_SECONDS, TrashLedger
from officekit.engines.engine_trash_restore import TrashRestoreGrantRequest, TrashRestoreRequest, TrashRestorer
from tests.test_duplicate_trash_unittest import duplicate_fixture, request  # noqa: F401  (fixture re-export)
from tests.test_file_jobs_unittest import await_job

NATIVE = 'native-test'
MISSING_ID = '00000000-0000-4000-8000-000000000000'


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def ledger_add(ledger, name='a.txt'):
    return ledger.add(trash_name=f'uuid-{name}', trash_identity=(1, 2), original_parent_path='/Users/x/Documents',
                      original_parent_identity=(1, 3), original_name=name, size=3)


# ARCH-2: a listing is a GET. It filters expired records in memory and never rewrites the file.
def test_listing_never_rewrites_the_ledger_when_records_expire(tmp_path):
    clock = Clock()
    path = tmp_path / 'OfficeKit' / 'trash-ledger.json'
    ledger = TrashLedger(str(path), clock=clock)
    ledger_add(ledger, 'old.txt')
    before = path.read_bytes()
    clock.now += TTL_SECONDS + 1
    assert ledger.page(0, 10)['total'] == 0
    assert ledger.get('missing') is None
    assert path.read_bytes() == before


# QA-2 / CR-1: after a write the stored file holds at most MAX_RECORDS, oldest dropped first.
def test_the_stored_file_never_exceeds_the_cap_after_a_write(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_module, 'MAX_RECORDS', 3)
    clock = Clock()
    path = tmp_path / 'trash-ledger.json'
    ledger = TrashLedger(str(path), clock=clock)
    for index in range(4):
        clock.now += 1
        ledger_add(ledger, f'f{index}.txt')
    stored = json.loads(path.read_text())['records']
    assert [record['original_name'] for record in stored] == ['f1.txt', 'f2.txt', 'f3.txt']


# DEVOPS-1 / CR-2: an existing ledger folder with another mode is tightened to owner-only.
@pytest.mark.skipif(os.name != 'posix', reason='POSIX modes')
def test_an_existing_folder_with_another_mode_is_tightened_to_owner_only(tmp_path):
    folder = tmp_path / 'OfficeKit'
    folder.mkdir()
    os.chmod(folder, 0o755)
    ledger = TrashLedger(str(folder / 'trash-ledger.json'), clock=Clock())
    ledger_add(ledger)
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(folder / 'trash-ledger.json').st_mode) == 0o600


# ARCH-1: the three success bodies are typed in the OpenAPI document.
def test_trash_success_bodies_are_typed_in_the_openapi_schema():
    schema = api.app.openapi()

    def body(path, method, code):
        return schema['paths'][path][method]['responses'][code]['content']['application/json']['schema']

    assert body('/api/trash-records', 'get', '200') == {'$ref': '#/components/schemas/TrashRecordPage'}
    assert body('/api/trash-restore-grants', 'post', '201') == {'$ref': '#/components/schemas/TrashRestoreGrant'}
    assert body('/api/trash-restorations', 'post', '201') == {'$ref': '#/components/schemas/TrashRestoration'}


def test_typed_bodies_keep_the_wire_field_names():
    schema = api.app.openapi()['components']['schemas']
    assert set(schema['TrashRecordPage']['properties']) == {'records', 'total', 'hasMore'}
    assert set(schema['TrashRestoreGrant']['properties']) == {'id', 'expiresIn'}
    assert set(schema['TrashRestoration']['properties']) == {'items', 'restored_bytes'}


# ARCH-3: the documented 404 and 503 answers exist on the grant route.
@pytest.fixture
def api_setup(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    trash = home / '.Trash'
    documents = home / 'Documents'
    trash.mkdir(parents=True)
    documents.mkdir(parents=True)
    ledger = TrashLedger(str(home / 'Library' / 'Application Support' / 'OfficeKit' / 'trash-ledger.json'))
    selections = FileSelectionStore(native_token=NATIVE)
    restorer = TrashRestorer(ledger, str(trash), selections, native_token=NATIVE)
    monkeypatch.setattr(api, 'trash_restorer', restorer)
    monkeypatch.setattr(api, 'file_selection_store', selections)
    return {'documents': documents, 'trash': trash, 'ledger': ledger, 'client': TestClient(api.app), 'restorer': restorer}


def test_grant_answers_404_for_an_absent_record(api_setup):
    response = api_setup['client'].post('/api/trash-restore-grants', headers={'X-OfficeKit-Native-Grant': NATIVE},
                                        json={'recordIds': [MISSING_ID]})
    assert response.status_code == 404


def test_grant_answers_503_when_the_approval_queue_is_full(api_setup, monkeypatch):
    monkeypatch.setattr(restore_module, 'MAX_RESTORE_GRANTS', 1)
    held = api_setup['ledger'].add(trash_name='uuid-held.txt', trash_identity=(1, 2), original_parent_path='/Users/x/Documents',
                                   original_parent_identity=(1, 3), original_name='held.txt', size=1)['record_id']
    api_setup['restorer'].grants['held'] = restore_module._Grant(frozenset([held]), None, time.monotonic() + 600)
    response = api_setup['client'].post('/api/trash-restore-grants', headers={'X-OfficeKit-Native-Grant': NATIVE},
                                        json={'recordIds': [held]})
    assert response.status_code == 503


# QA-6: the listing offset is bounded to 0 to 10,000.
def test_listing_offset_is_bounded_to_ten_thousand(api_setup):
    client = api_setup['client']
    assert client.get('/api/trash-records?offset=10000').status_code == 200
    assert client.get('/api/trash-records?offset=10001').status_code == 422


# QA-5: a folder on another device is changed, and nothing moves.
def test_a_folder_on_another_device_is_changed_and_nothing_moves(tmp_path, monkeypatch):
    from tests.test_trash_restore_unittest import approve, page_states, restore, stash
    home = tmp_path / 'home'
    trash = home / '.Trash'
    documents = home / 'Documents'
    trash.mkdir(parents=True)
    documents.mkdir(parents=True)
    clock = Clock()
    ledger = TrashLedger(str(home / 'Library' / 'Application Support' / 'OfficeKit' / 'trash-ledger.json'), clock=clock)
    selections = FileSelectionStore(native_token=NATIVE)
    restorer = TrashRestorer(ledger, str(trash), selections, native_token=NATIVE, clock=clock)
    state = {'home': home, 'trash': trash, 'documents': documents, 'ledger': ledger, 'selections': selections,
             'restorer': restorer, 'clock': clock, 'tmp': tmp_path}
    record = stash(state, 'device.txt')
    monkeypatch.setattr(restore_module, '_same_volume', lambda trash_value, folder_value: False)
    assert page_states(state)[record] == 'changed'
    result = restore(state, [record], approve(state, [record]))
    assert result['items'] == [{'id': record, 'state': 'skipped', 'reason': 'changed'}]
    assert (trash / 'uuid-device.txt').exists()
    assert not (documents / 'device.txt').exists()


# QA-8: the descriptor walk refuses a link component on its own, without the identity check.
def test_the_descriptor_walk_refuses_a_link_component_on_its_own(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    link = tmp_path / 'link'
    os.symlink(real, link)
    with pytest.raises(OSError):
        restore_module._open_directory(str(link))


# CR-5: a full approval queue is refused before the destination grant is spent.
def test_a_full_approval_queue_does_not_spend_the_destination_grant(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    trash = home / '.Trash'
    documents = home / 'Documents'
    trash.mkdir(parents=True)
    documents.mkdir(parents=True)
    clock = Clock()
    ledger = TrashLedger(str(home / 'Library' / 'Application Support' / 'OfficeKit' / 'trash-ledger.json'), clock=clock)
    selections = FileSelectionStore(native_token=NATIVE)
    restorer = TrashRestorer(ledger, str(trash), selections, native_token=NATIVE, clock=clock)
    monkeypatch.setattr(restore_module, 'MAX_RESTORE_GRANTS', 1)
    restorer.grants['held'] = restore_module._Grant(frozenset([MISSING_ID]), None, clock() + 600)
    source = documents / 'queued.txt'
    source.write_bytes(b'q')
    shutil.move(str(source), str(trash / 'uuid-queued.txt'))
    moved = os.stat(trash / 'uuid-queued.txt')
    folder = os.stat(documents)
    record = ledger.add(trash_name='uuid-queued.txt', trash_identity=(moved.st_dev, moved.st_ino),
                        original_parent_path=str(documents), original_parent_identity=(folder.st_dev, folder.st_ino),
                        original_name='queued.txt', size=1)['record_id']
    picked = tmp_path / 'picked'
    picked.mkdir()
    output = selections.register_output(str(picked / 'queued.txt'), 'directory', 'trash-restore', credential=NATIVE)
    body = TrashRestoreGrantRequest.model_validate({'recordIds': [record], 'destinationGrantId': output['id']})
    with pytest.raises(RuntimeError):
        restorer.mint(body, NATIVE)
    restorer.grants.clear()
    grant_id = restorer.mint(body, NATIVE)['id']
    result = restorer.restore(TrashRestoreRequest.model_validate({'recordIds': [record], 'restoreGrantId': grant_id}), NATIVE)
    assert result['items'][0]['state'] == 'restored'
    assert (picked / 'queued.txt').read_bytes() == b'q'


# QA-7: the move runs while the ledger lock is held, so the record and the move share one critical section.
def test_the_move_runs_while_the_ledger_lock_is_held(tmp_path):
    home = tmp_path / 'home'
    (home / '.Trash').mkdir(parents=True)
    (home / 'Documents').mkdir()
    source = home / 'Documents' / 'locked.txt'
    source.write_bytes(b'x')
    service = StorageCleaner(home=str(home), platform='darwin')
    free_elsewhere = []
    original = service._trash_move

    def probe(*args, **kwargs):
        def attempt():
            acquired = service.ledger.lock.acquire(blocking=False)
            if acquired:
                service.ledger.lock.release()
            free_elsewhere.append(acquired)
        thread = threading.Thread(target=attempt)
        thread.start()
        thread.join()
        return original(*args, **kwargs)

    service._trash_move = probe
    assert service._trash(str(source), identity(os.stat(source)), 1) is True
    assert free_elsewhere == [False]


# QA-4: the user-facing outcome names the unrecorded state when the ledger fails.
@pytest.mark.parametrize('recorded,message', [(True, 'Moved to Trash.'), (False, UNRECORDED_TRASH_MESSAGE)])
def test_the_cleanup_outcome_names_whether_the_move_was_recorded(tmp_path, monkeypatch, recorded, message):
    home = tmp_path / 'home'
    (home / '.Trash').mkdir(parents=True)
    (home / 'Documents').mkdir()
    source = home / 'Documents' / 'outcome.txt'
    source.write_bytes(b'data')
    service = StorageCleaner(native_token=NATIVE, home=str(home), platform='darwin')
    monkeypatch.setattr(service, '_trash', lambda path, expected, size_bytes=None, open_paths=None: recorded)
    item = {'id': 'i1', 'method': 'trash', 'path': str(source), 'sizeBytes': 4}
    service.plans['plan-1'] = {'id': 'plan-1', 'expiresAt': time.time() + 600, 'selected': [(item, identity(os.stat(source)))]}
    outcome = service.execute('plan-1', NATIVE)['items'][0]
    assert outcome == {'id': 'i1', 'status': 'moved', 'sizeBytes': 4, 'message': message}


# QA-3: a duplicate outcome's restorable flag follows the record result.
@pytest.mark.parametrize('recorded', [True, False])
def test_duplicate_outcome_restorable_follows_the_record_result(duplicate_fixture, recorded):
    folder, trash, _, selection, jobs, scan, entries = duplicate_fixture
    move = jobs.trash
    name = entries[1]['name']
    path = str(folder / name)
    expected_call = (path, identity(os.stat(path)))
    calls = []

    def mover(path, expected):
        calls.append((path, expected))
        move(path, expected)
        return recorded

    jobs.trash = mover
    cleanup = jobs.submit(request(selection, scan, [entries[1]['id']]))['id']
    assert await_job(jobs, cleanup)['state'] == 'ready'
    # QA-9: the mover is called exactly once, with the copy's path and the identity the scan recorded.
    assert calls == [expected_call]
    item = jobs.result(cleanup)['items'][0]
    assert item['state'] == 'trashed'
    assert item['restorable'] is recorded
