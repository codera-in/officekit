"""Restore from Trash: every state, the races, no-replace and the grant rules.

Synthetic trees only. The developer's real ~/.Trash is never touched: every test
injects its own Trash directory under pytest's tmp_path.
"""

import os
import shutil
from types import SimpleNamespace

import pytest

from officekit.engines import engine_trash_restore as restore_module
from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_trash_ledger import TrashLedger
from officekit.engines.engine_trash_restore import (
    MAX_RESTORE_IDS,
    RESTORE_GRANT_TTL_SECONDS,
    TrashRestoreGrantRequest,
    TrashRestoreRequest,
    TrashRestorer,
)

NATIVE = 'native-test'
MISSING_ID = '00000000-0000-4000-8000-000000000000'


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_path):
    home = tmp_path / 'home'
    trash = home / '.Trash'
    documents = home / 'Documents'
    trash.mkdir(parents=True)
    documents.mkdir(parents=True)
    clock = Clock()
    ledger = TrashLedger(str(home / 'Library' / 'Application Support' / 'OfficeKit' / 'trash-ledger.json'), clock=clock)
    selections = FileSelectionStore(native_token=NATIVE)
    restorer = TrashRestorer(ledger, str(trash), selections, native_token=NATIVE, clock=clock)
    return {'home': home, 'trash': trash, 'documents': documents, 'ledger': ledger,
            'selections': selections, 'restorer': restorer, 'clock': clock, 'tmp': tmp_path}


def stash(world, name, data=b'hello', parent=None):
    """Create a file in a folder, then move it into the synthetic Trash as the cleaner does."""
    folder = parent or world['documents']
    source = folder / name
    source.write_bytes(data)
    parent_value = os.stat(folder)
    trash_name = 'uuid-' + name
    shutil.move(str(source), str(world['trash'] / trash_name))
    moved = os.stat(world['trash'] / trash_name)
    return world['ledger'].add(trash_name=trash_name, trash_identity=(moved.st_dev, moved.st_ino),
                               original_parent_path=str(folder), original_parent_identity=(parent_value.st_dev, parent_value.st_ino),
                               original_name=name, size=len(data))['record_id']


def page_states(world):
    return {record['id']: record['state'] for record in world['restorer'].page(0, 200)['records']}


def approve(world, ids, destination=None):
    body = TrashRestoreGrantRequest.model_validate({'recordIds': ids, 'destinationGrantId': destination})
    return world['restorer'].mint(body, NATIVE)['id']


def restore(world, ids, grant_id, credential=NATIVE):
    body = TrashRestoreRequest.model_validate({'recordIds': ids, 'restoreGrantId': grant_id})
    return world['restorer'].restore(body, credential)


def test_listing_reports_each_state_and_the_total(world):
    restorable = stash(world, 'free.txt')
    taken = stash(world, 'taken.txt')
    (world['documents'] / 'taken.txt').write_text('new')
    gone = stash(world, 'gone.txt')
    os.unlink(world['trash'] / 'uuid-gone.txt')
    other = world['home'] / 'Other'
    other.mkdir()
    changed = stash(world, 'moved.txt', parent=other)
    shutil.move(str(other), str(world['tmp'] / 'other-old'))
    os.symlink(world['documents'], other)
    page = world['restorer'].page(0, 200)
    assert page['total'] == 4 and page['hasMore'] is False
    assert page_states(world) == {restorable: 'restorable', taken: 'name-taken', gone: 'missing', changed: 'changed'}
    row = next(record for record in page['records'] if record['id'] == changed)
    assert row['name'] == 'moved.txt' and row['size_bytes'] == 5
    assert row['original_folder_display'] == str(other)


def test_listing_pages_and_reports_more(world):
    for index in range(3):
        stash(world, f'page-{index}.txt')
    assert len(world['restorer'].page(0, 2)['records']) == 2
    assert world['restorer'].page(0, 2)['hasMore'] is True
    assert world['restorer'].page(2, 2)['hasMore'] is False


def test_restore_moves_the_item_back_and_leaves_the_list(world):
    record = stash(world, 'back.txt', data=b'12345')
    result = restore(world, [record], approve(world, [record]))
    assert result == {'items': [{'id': record, 'state': 'restored', 'reason': None,
                                 'restored_to': str(world['documents'] / 'back.txt')}], 'restored_bytes': 5}
    assert (world['documents'] / 'back.txt').read_bytes() == b'12345'
    assert not (world['trash'] / 'uuid-back.txt').exists()
    assert world['ledger'].get(record) is None


def test_restore_never_replaces_an_existing_name(world):
    record = stash(world, 'same.txt', data=b'old')
    (world['documents'] / 'same.txt').write_bytes(b'new')
    result = restore(world, [record], approve(world, [record]))
    assert result == {'items': [{'id': record, 'state': 'skipped', 'reason': 'name-taken'}], 'restored_bytes': 0}
    assert (world['documents'] / 'same.txt').read_bytes() == b'new'
    assert (world['trash'] / 'uuid-same.txt').read_bytes() == b'old'
    assert world['ledger'].get(record) is not None


def test_partial_restore_reports_each_item(world):
    ok = stash(world, 'ok.txt', data=b'abc')
    blocked = stash(world, 'blocked.txt', data=b'de')
    (world['documents'] / 'blocked.txt').write_text('x')
    result = restore(world, [ok, blocked], approve(world, [ok, blocked]))
    assert result['items'] == [{'id': ok, 'state': 'restored', 'reason': None,
                                'restored_to': str(world['documents'] / 'ok.txt')},
                               {'id': blocked, 'state': 'skipped', 'reason': 'name-taken'}]
    assert result['restored_bytes'] == 3


def test_record_forgotten_after_approval_is_skipped_as_missing(world):
    record = stash(world, 'later.txt')
    grant = approve(world, [record])
    world['ledger'].remove(record)
    assert restore(world, [record], grant)['items'] == [{'id': record, 'state': 'skipped', 'reason': 'missing'}]


def test_trash_item_replaced_after_approval_is_not_restored(world):
    record = stash(world, 'swap.txt', data=b'original')
    grant = approve(world, [record])
    os.unlink(world['trash'] / 'uuid-swap.txt')
    (world['trash'] / 'uuid-swap.txt').write_bytes(b'impostor')
    assert restore(world, [record], grant)['items'] == [{'id': record, 'state': 'skipped', 'reason': 'missing'}]
    assert not (world['documents'] / 'swap.txt').exists()


def test_emptied_trash_and_missing_trash_folder_report_missing(world):
    emptied = stash(world, 'emptied.txt')
    os.unlink(world['trash'] / 'uuid-emptied.txt')
    assert page_states(world) == {emptied: 'missing'}
    shutil.rmtree(world['trash'])
    assert page_states(world) == {emptied: 'missing'}
    assert restore(world, [emptied], approve(world, [emptied]))['items'][0]['reason'] == 'missing'


def test_original_folder_replaced_by_a_link_is_changed_and_nothing_moves(world):
    record = stash(world, 'linked.txt', data=b'safe')
    elsewhere = world['tmp'] / 'elsewhere'
    elsewhere.mkdir()
    shutil.move(str(world['documents']), str(world['tmp'] / 'documents-old'))
    os.symlink(elsewhere, world['documents'])
    assert page_states(world) == {record: 'changed'}
    assert restore(world, [record], approve(world, [record]))['items'] == [{'id': record, 'state': 'skipped', 'reason': 'changed'}]
    assert list(elsewhere.iterdir()) == []
    assert (world['trash'] / 'uuid-linked.txt').read_bytes() == b'safe'


def test_original_folder_swapped_after_approval_is_changed(world):
    record = stash(world, 'late.txt')
    grant = approve(world, [record])
    shutil.move(str(world['documents']), str(world['tmp'] / 'documents-old'))
    world['documents'].mkdir()
    assert restore(world, [record], grant)['items'] == [{'id': record, 'state': 'skipped', 'reason': 'changed'}]


def test_swap_after_the_move_is_reported_and_the_new_item_is_left_alone(world, monkeypatch):
    record = stash(world, 'raced.txt', data=b'raced')
    grant = approve(world, [record])
    real_move = restore_module._exclusive_move

    def swap_after_move(source, source_fd, destination, destination_fd):
        real_move(source, source_fd, destination, destination_fd)
        os.unlink(os.path.join(world['documents'], destination))
        with open(os.path.join(world['documents'], destination), 'wb') as handle:
            handle.write(b'impostor')

    monkeypatch.setattr(restore_module, '_exclusive_move', swap_after_move)
    result = restore(world, [record], grant)
    monkeypatch.undo()
    assert result['items'] == [{'id': record, 'state': 'skipped', 'reason': 'changed'}]
    assert (world['documents'] / 'raced.txt').read_bytes() == b'impostor'
    assert world['ledger'].get(record) is not None


def test_protected_folder_is_never_restored_into(world):
    protected = world['home'] / '.ssh'
    protected.mkdir()
    record = stash(world, 'key.txt', parent=protected)
    assert page_states(world) == {record: 'changed'}
    assert restore(world, [record], approve(world, [record]))['items'] == [{'id': record, 'state': 'skipped', 'reason': 'protected'}]
    assert (world['trash'] / 'uuid-key.txt').exists()


def test_folders_owned_by_another_user_are_changed(world, monkeypatch):
    record = stash(world, 'owned.txt')
    real_uid = os.getuid()
    monkeypatch.setattr(restore_module.os, 'getuid', lambda: real_uid + 1)
    assert page_states(world) == {record: 'changed'}
    monkeypatch.undo()
    assert page_states(world) == {record: 'restorable'}


def test_same_volume_compares_device_numbers_only(world):
    trash_value = os.stat(world['trash'])
    assert restore_module._same_volume(trash_value, SimpleNamespace(st_dev=trash_value.st_dev))
    assert not restore_module._same_volume(trash_value, SimpleNamespace(st_dev=trash_value.st_dev + 1))


def test_grant_is_required_and_bound_to_the_exact_ids(world):
    first = stash(world, 'one.txt')
    second = stash(world, 'two.txt')
    grant = approve(world, [first])
    with pytest.raises(PermissionError):
        restore(world, [first], 'forged-grant')
    with pytest.raises(PermissionError):
        restore(world, [second], grant)
    with pytest.raises(PermissionError):
        restore(world, [first], grant, credential='wrong')
    assert restore(world, [first], grant)['restored_bytes'] == len(b'hello')


def test_grant_is_single_use(world):
    record = stash(world, 'once.txt')
    grant = approve(world, [record])
    restore(world, [record], grant)
    with pytest.raises(PermissionError):
        restore(world, [record], grant)


def test_grant_expires_after_ten_minutes(world):
    record = stash(world, 'late.txt')
    grant = approve(world, [record])
    world['clock'].now += RESTORE_GRANT_TTL_SECONDS
    with pytest.raises(PermissionError):
        restore(world, [record], grant)


def test_minting_needs_native_authorization_and_known_items(world):
    record = stash(world, 'auth.txt')
    body = TrashRestoreGrantRequest.model_validate({'recordIds': [record]})
    with pytest.raises(PermissionError):
        world['restorer'].mint(body, '')
    with pytest.raises(PermissionError):
        world['restorer'].mint(body, 'wrong')
    unknown = TrashRestoreGrantRequest.model_validate({'recordIds': [MISSING_ID]})
    with pytest.raises(FileNotFoundError):
        world['restorer'].mint(unknown, NATIVE)


def test_restore_to_a_chosen_folder_uses_the_directory_grant(world):
    record = stash(world, 'chosen.txt', data=b'xy')
    picked = world['tmp'] / 'picked'
    picked.mkdir()
    output = world['selections'].register_output(str(picked / 'chosen.txt'), 'directory', 'trash-restore', credential=NATIVE)
    result = restore(world, [record], approve(world, [record], destination=output['id']))
    assert result['items'] == [{'id': record, 'state': 'restored', 'reason': None,
                                'restored_to': str(picked / 'chosen.txt')}]
    assert (picked / 'chosen.txt').read_bytes() == b'xy'
    assert not (world['documents'] / 'chosen.txt').exists()


def test_restore_to_a_folder_needs_one_item_and_a_trash_restore_grant(world):
    first = stash(world, 'p.txt')
    second = stash(world, 'q.txt')
    picked = world['tmp'] / 'picked2'
    picked.mkdir()
    output = world['selections'].register_output(str(picked / 'p.txt'), 'directory', 'archive-create', credential=NATIVE)
    with pytest.raises(ValueError):
        approve(world, [first, second], destination=output['id'])
    with pytest.raises(PermissionError):
        approve(world, [first], destination=output['id'])
    with pytest.raises(FileNotFoundError):
        approve(world, [first], destination='no-such-output')
    assert world['ledger'].get(second) is not None


def test_restore_to_a_folder_refuses_a_name_taken_or_swapped_folder(world):
    taken = stash(world, 'dest.txt')
    picked = world['tmp'] / 'picked3'
    picked.mkdir()
    output = world['selections'].register_output(str(picked / 'dest.txt'), 'directory', 'trash-restore', credential=NATIVE)
    grant = approve(world, [taken], destination=output['id'])
    (picked / 'dest.txt').write_text('mine')
    assert restore(world, [taken], grant)['items'][0]['reason'] == 'name-taken'

    swapped = stash(world, 'moved.txt')
    picked2 = world['tmp'] / 'picked4'
    picked2.mkdir()
    output = world['selections'].register_output(str(picked2 / 'moved.txt'), 'directory', 'trash-restore', credential=NATIVE)
    grant = approve(world, [swapped], destination=output['id'])
    shutil.move(str(picked2), str(world['tmp'] / 'picked4-old'))
    picked2.mkdir()
    assert restore(world, [swapped], grant)['items'][0]['reason'] == 'changed'


def test_ledger_failure_after_a_restore_still_reports_restored(world, monkeypatch):
    record = stash(world, 'ledger-down.txt', data=b'ab')
    grant = approve(world, [record])

    def broken(record_id):
        raise OSError('ledger unavailable')

    monkeypatch.setattr(world['ledger'], 'remove', broken)
    assert restore(world, [record], grant)['items'] == [{'id': record, 'state': 'restored', 'reason': None,
                                                         'restored_to': str(world['documents'] / 'ledger-down.txt')}]
    assert (world['documents'] / 'ledger-down.txt').read_bytes() == b'ab'


def test_tampered_ledger_names_cannot_escape_the_trash(world):
    forged = world['ledger'].add(trash_name='../../etc/passwd', trash_identity=(1, 2),
                                 original_parent_path=str(world['documents']), original_parent_identity=(1, 2),
                                 original_name='x', size=1)['record_id']
    assert page_states(world) == {forged: 'missing'}
    assert restore(world, [forged], approve(world, [forged]))['items'][0]['reason'] == 'missing'


def test_forget_removes_only_the_ledger_entry_and_keeps_the_file(world):
    record = stash(world, 'forget.txt')
    world['restorer'].forget(record, NATIVE)
    assert world['ledger'].get(record) is None
    assert (world['trash'] / 'uuid-forget.txt').exists()
    with pytest.raises(FileNotFoundError):
        world['restorer'].forget(record, NATIVE)
    with pytest.raises(PermissionError):
        world['restorer'].forget(record, 'wrong')


def test_request_dtos_are_strict_and_bounded():
    assert MAX_RESTORE_IDS == 100
    with pytest.raises(ValueError):
        TrashRestoreGrantRequest.model_validate({'recordIds': []})
    with pytest.raises(ValueError):
        TrashRestoreGrantRequest.model_validate({'recordIds': [MISSING_ID] * 101})
    with pytest.raises(ValueError):
        TrashRestoreGrantRequest.model_validate({'recordIds': ['not-a-uuid']})
    with pytest.raises(ValueError):
        TrashRestoreGrantRequest.model_validate({'recordIds': [MISSING_ID], 'extra': 1})
    with pytest.raises(ValueError):
        TrashRestoreRequest.model_validate({'recordIds': [MISSING_ID]})


def tampered(world, trash_name, **fields):
    """A real Trash item with a ledger record whose folder or name fields are forged."""
    path = world['trash'] / trash_name
    path.write_bytes(b'x')
    value = os.stat(path)
    folder = os.stat(world['documents'])
    base = {'trash_name': trash_name, 'trash_identity': (value.st_dev, value.st_ino),
            'original_parent_path': str(world['documents']), 'original_parent_identity': (folder.st_dev, folder.st_ino),
            'original_name': 't.txt', 'size': 1}
    base.update(fields)
    return world['ledger'].add(**base)['record_id']


def test_relative_folders_and_dot_names_in_a_tampered_ledger_are_changed(world):
    relative = tampered(world, 'uuid-rel', original_parent_path='relative/dir')
    dotdot = tampered(world, 'uuid-dot', original_name='..')
    assert page_states(world) == {relative: 'changed', dotdot: 'changed'}
    assert restore(world, [relative, dotdot], approve(world, [relative, dotdot]))['items'] == [
        {'id': relative, 'state': 'skipped', 'reason': 'changed'},
        {'id': dotdot, 'state': 'skipped', 'reason': 'changed'}]


def test_exclusive_move_never_replaces_an_existing_name(tmp_path):
    folder = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        (tmp_path / 'a.txt').write_text('a')
        (tmp_path / 'b.txt').write_text('b')
        with pytest.raises(FileExistsError):
            restore_module._exclusive_move('a.txt', folder, 'b.txt', folder)
        assert (tmp_path / 'b.txt').read_text() == 'b'
        restore_module._exclusive_move('a.txt', folder, 'c.txt', folder)
        assert (tmp_path / 'c.txt').read_text() == 'a'
    finally:
        os.close(folder)


def test_a_platform_without_exclusive_rename_is_refused_and_reported(world, monkeypatch):
    record = stash(world, 'unsupported.txt')
    grant = approve(world, [record])
    monkeypatch.setattr(restore_module, '_RENAME_NO_REPLACE', {})
    with pytest.raises(OSError):
        restore_module._exclusive_move('a', 0, 'b', 0)
    assert restore(world, [record], grant)['items'] == [{'id': record, 'state': 'skipped', 'reason': 'changed'}]


@pytest.mark.parametrize('error,reason', [
    (FileExistsError(17, 'exists'), 'name-taken'),
    (FileNotFoundError(2, 'gone'), 'missing'),
    (PermissionError(1, 'denied'), 'changed'),
])
def test_a_failing_move_is_reported_by_its_cause(world, monkeypatch, error, reason):
    record = stash(world, 'cause.txt')
    grant = approve(world, [record])

    def failing(*args):
        raise error

    monkeypatch.setattr(restore_module, '_exclusive_move', failing)
    assert restore(world, [record], grant)['items'] == [{'id': record, 'state': 'skipped', 'reason': reason}]
    assert (world['trash'] / 'uuid-cause.txt').exists()


def test_an_item_that_vanishes_right_after_the_move_is_changed_and_left_alone(world, monkeypatch):
    record = stash(world, 'vanished.txt')
    grant = approve(world, [record])
    real_move = restore_module._exclusive_move

    def move_then_remove(source, source_fd, destination, destination_fd):
        real_move(source, source_fd, destination, destination_fd)
        os.unlink(os.path.join(world['documents'], destination))

    monkeypatch.setattr(restore_module, '_exclusive_move', move_then_remove)
    assert restore(world, [record], grant)['items'] == [{'id': record, 'state': 'skipped', 'reason': 'changed'}]


def test_too_many_waiting_approvals_are_refused(world, monkeypatch):
    monkeypatch.setattr(restore_module, 'MAX_RESTORE_GRANTS', 1)
    first = stash(world, 'cap-a.txt')
    second = stash(world, 'cap-b.txt')
    approve(world, [first])
    with pytest.raises(RuntimeError):
        approve(world, [second])


def test_a_failure_while_holding_folders_releases_them_and_raises(world, monkeypatch):
    stash(world, 'held.txt')

    def broken():
        raise OSError('identity unavailable')

    monkeypatch.setattr(restore_module.os, 'getuid', broken)
    with pytest.raises(OSError):
        world['restorer'].page(0, 200)
    monkeypatch.undo()
    assert page_states(world)


def test_nothing_is_logged(world, capsys, caplog):
    record = stash(world, 'quiet-name.txt')
    restore(world, [record], approve(world, [record]))
    captured = capsys.readouterr()
    assert 'quiet-name' not in captured.out + captured.err
    assert 'quiet-name' not in caplog.text
