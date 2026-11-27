"""Durable direct-folder invoice libraries and their authority boundary."""

import hashlib
import json
import os
import errno
from types import SimpleNamespace
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.invoices.storage import InvoiceLibraries, InvoiceStorageError, invoice_bindings_path
from officekit.invoices import storage


@pytest.fixture
def library(tmp_path):
    parent = tmp_path / 'selected'
    parent.mkdir()
    selections = FileSelectionStore(native_token='native')
    selected = selections.register_native([str(parent)], 'read-write', 'native')
    settings = tmp_path / 'private' / 'invoice-bindings.json'
    manager = InvoiceLibraries(selections, settings)
    state = manager.attach(selected['id'])
    return manager, manager.get(state['id']), parent, settings, selections


def test_invoice_bindings_follow_the_configured_app_data_directory(monkeypatch, tmp_path):
    default = tmp_path / 'Application Support' / 'OfficeKit'
    isolated = tmp_path / 'isolated-test-data'
    isolated.mkdir()
    alias = tmp_path / 'temporary-path-alias'
    alias.symlink_to(isolated, target_is_directory=True)
    monkeypatch.setenv('OFFICEKIT_DATA_DIR', str(alias))
    assert invoice_bindings_path(default) == str(isolated / 'invoice-folder-bindings.json')

    monkeypatch.delenv('OFFICEKIT_DATA_DIR')
    assert invoice_bindings_path(default) == str(default / 'invoice-folder-bindings.json')


def test_attach_transaction_reopen_and_private_binding(library):
    manager, repo, parent, settings, selections = library
    first = repo.read()
    assert first['revision'] == 0
    assert all(first[key] == {} for key in ('businesses', 'documents', 'payments', 'schedules'))
    result = repo.transaction(0, lambda state: state['businesses'].setdefault('b', {'name': 'Studio'}))
    assert result == {'name': 'Studio', 'library_revision': 1}
    assert repo.read()['businesses'] == {'b': {'name': 'Studio'}}
    copy = repo.read()
    copy['businesses'].clear()
    assert repo.read()['businesses']
    assert os.stat(settings).st_mode & 0o777 == 0o600
    bindings = manager.list_bindings()
    assert bindings[0]['id'] == first['library_id']
    assert str(parent) not in json.dumps(bindings)
    fresh = InvoiceLibraries(selections, settings)
    with pytest.raises(InvoiceStorageError) as error:
        fresh.get(first['library_id'])
    assert error.value.status == 404
    state = fresh.reconnect(first['library_id'], 'native')
    assert state['revision'] == 1
    assert fresh.get(first['library_id']).read() == repo.read()
    assert fresh.attach(selections.register_native([str(parent)], 'read-write', 'native')['id'])['id'] == state['id']


def test_conflicting_revisions_external_changes_and_reload(library):
    _, repo, parent, _, _ = library
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(2, lambda state: state.clear())
    assert error.value.code == 'REVISION_CONFLICT'
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    data = storage._state_from_database(path.read_bytes())
    data['revision'] = 8
    path.write_bytes(storage._state_database(data))
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.status == 409
    assert repo.reload()['revision'] == 8
    assert repo.transaction(8, lambda state: 'saved') == 'saved'
    assert repo.read()['revision'] == 9


def test_assets_are_hash_verified_immutable_and_bounded(library, monkeypatch):
    _, repo, parent, _, _ = library
    data = b'png-normalized-by-pdf-layer'
    digest = repo.put_asset(data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert repo.read_asset(digest) == data
    assert repo.put_asset(data) == digest
    with pytest.raises(InvoiceStorageError):
        repo.read_asset('../outside')
    asset = parent / 'officekit-invoices' / 'assets' / 'logos' / f'{digest}.png'
    asset.write_bytes(b'tampered')
    with pytest.raises(InvoiceStorageError):
        repo.read_asset(digest)
    from officekit.invoices import storage
    monkeypatch.setattr(storage, 'MAX_ASSET_BYTES', 2)
    with pytest.raises(InvoiceStorageError):
        repo.put_asset(b'123')


def test_readonly_or_multiple_or_expired_selection_cannot_attach(tmp_path):
    selections = FileSelectionStore(native_token='native')
    manager = InvoiceLibraries(selections, tmp_path / 'private' / 'bindings.json')
    folder = tmp_path / 'folder'
    folder.mkdir()
    selected = selections.register_native([str(folder)], 'read', 'native')
    with pytest.raises(InvoiceStorageError):
        manager.attach(selected['id'])
    with pytest.raises(InvoiceStorageError):
        manager.attach('missing')
    file = tmp_path / 'file'
    file.write_text('original')
    selected = selections.register_native([str(file)], 'read-write', 'native')
    with pytest.raises(InvoiceStorageError):
        manager.attach(selected['id'])
    selected = selections.register_native([str(folder), str(file)], 'read-write', 'native')
    with pytest.raises(InvoiceStorageError):
        manager.attach(selected['id'])


def test_native_reconnect_requires_authority_and_original_folder(library):
    manager, repo, parent, settings, selections = library
    with pytest.raises(PermissionError):
        manager.reconnect(repo.library_id, 'wrong')
    with pytest.raises(InvoiceStorageError):
        manager.reconnect('missing', 'native')
    parent.rename(parent.with_name('moved'))
    parent.mkdir()
    fresh = InvoiceLibraries(selections, settings)
    with pytest.raises(InvoiceStorageError) as error:
        fresh.reconnect(repo.library_id, 'native')
    assert error.value.code == 'FOLDER_CHANGED'


def test_transaction_failure_preserves_library_and_prior_verified_backup(library):
    _, repo, parent, _, _ = library
    repo.transaction(0, lambda state: state['clients'].setdefault('c', {'name': 'Acme'}))
    def fail(state):
        state['clients'].clear()
        raise ValueError('domain failure')
    with pytest.raises(ValueError, match='domain failure'):
        repo.transaction(1, fail)
    assert repo.read()['clients'] == {'c': {'name': 'Acme'}}
    repo.transaction(1, lambda state: None)
    backup = storage._state_from_database((parent / 'officekit-invoices' / 'config' / 'officekit.previous.sqlite3').read_bytes())
    assert backup['revision'] == 1


def test_unrelated_files_and_other_libraries_are_untouched(library, tmp_path):
    manager, repo, parent, _, selections = library
    unrelated = parent / 'invoice.pdf'
    unrelated.write_bytes(b'original')
    other = tmp_path / 'other'
    other.mkdir()
    attached = manager.attach(selections.register_native([str(other)], 'read-write', 'native')['id'])
    assert attached['id'] != repo.library_id
    repo.transaction(0, lambda state: state['items'].setdefault('x', {'description': 'Only here'}))
    assert manager.get(attached['id']).read()['items'] == {}
    assert unrelated.read_bytes() == b'original'


@pytest.mark.parametrize('mutation', [
    lambda s: s.pop('items'), lambda s: s.update(schema_version=2),
    lambda s: s.update(schema_version=True),
    lambda s: s.update(library_id='invalid'), lambda s: s.update(library_id=123),
    lambda s: s.update(library_id='00000000000000000000000000000000'),
    lambda s: s.update(items=[]), lambda s: s.update(items={'x': 1}),
    lambda s: s.update(items={1: {}}),
])
def test_invalid_envelopes_never_publish(library, mutation):
    _, repo, _, _, _ = library
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, mutation)
    assert error.value.code == 'INVALID_LIBRARY'
    assert repo.read()['revision'] == 0


def test_non_object_json_and_unknown_schema_are_rejected(library):
    _, repo, parent, _, _ = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    for data in (b'[]', b'{', b'\xff'):
        path.write_bytes(data)
        with pytest.raises(InvoiceStorageError) as error:
            repo.reload()
        assert error.value.code == 'INVALID_DATABASE'
    state = dict(schema_version=1, library_id=repo.library_id, revision=0, **{key: {} for key in storage.COLLECTION_LIMITS})
    for revision in (True, -1):
        state['revision'] = revision
        with pytest.raises(InvoiceStorageError):
            storage._state_database(state)


def test_capacity_and_serialization_checks_apply_after_mutation(library, monkeypatch):
    _, repo, _, _, _ = library
    monkeypatch.setitem(storage.COLLECTION_LIMITS, 'items', 1)
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, lambda s: s['items'].update(a={}, b={}))
    assert error.value.status == 413
    monkeypatch.setattr(storage, 'MAX_LIBRARY_BYTES', len(storage._encode(repo.read(), 10000)) + 10)
    with pytest.raises(InvoiceStorageError):
        repo.transaction(0, lambda s: s['items'].update(a={'data': 'x' * 100}))
    assert repo.read()['revision'] == 0
    for value in (float('nan'), b'bytes', '\ud800'):
        with pytest.raises(InvoiceStorageError) as error:
            storage._encode(value, 100)
        assert error.value.code == 'INVALID_LIBRARY'


def test_changed_library_identity_cannot_be_adopted_or_committed(library):
    _, repo, parent, _, _ = library
    import uuid
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, lambda s: s.update(library_id=str(uuid.uuid4())))
    assert error.value.code == 'LIBRARY_CHANGED'
    state = repo.read()
    state['library_id'] = str(uuid.uuid4())
    (parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3').write_bytes(storage._state_database(state))
    with pytest.raises(InvoiceStorageError) as error:
        repo.reload()
    assert error.value.code == 'LIBRARY_CHANGED'


def test_io_and_disk_full_failures_do_not_replace_original(library, monkeypatch):
    _, repo, parent, _, _ = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    before = path.read_bytes()
    replace = os.replace
    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, 'private data must not escape')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, lambda s: s['items'].update(a={}))
    assert error.value.code == 'DISK_FULL'
    assert str(error.value) == 'The invoice folder has no space for this save.'
    assert path.read_bytes() == before
    assert not list(path.parent.glob('.invoice-*'))
    monkeypatch.setattr(os, 'replace', replace)
    path.unlink()
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.status == 503


def test_link_hardlink_and_replaced_root_are_rejected(library, tmp_path):
    _, repo, parent, _, _ = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    original = path.read_bytes()
    link = tmp_path / 'hardlink'
    os.link(path, link)
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.code == 'UNSAFE_FILE'
    link.unlink()
    path.unlink()
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises(InvoiceStorageError):
        repo.read()
    path.unlink()
    path.write_bytes(original)
    root = path.parent.parent
    root.rename(root.with_name('displaced'))
    root.mkdir()
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.code == 'FOLDER_CHANGED'


def test_folder_replacement_during_transaction_is_reported(library):
    _, repo, parent, _, _ = library
    def rename(s):
        (parent / 'officekit-invoices').rename(parent / 'renamed')
        (parent / 'officekit-invoices').mkdir()
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, rename)
    assert error.value.code == 'FOLDER_CHANGED'
    assert storage._state_from_database((parent / 'renamed' / 'config' / 'officekit.sqlite3').read_bytes())['revision'] == 0


def test_external_change_after_callback_is_not_overwritten(library):
    _, repo, parent, _, _ = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    def external_change(s):
        latest = repo.read()
        latest['revision'] = 12
        path.write_bytes(storage._state_database(latest))
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, external_change)
    assert error.value.code == 'REVISION_CONFLICT'
    assert storage._state_from_database(path.read_bytes())['revision'] == 12


def test_reconnect_refuses_missing_library_and_changed_identity(library):
    _, repo, parent, settings, selections = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    state = storage._state_from_database(path.read_bytes())
    state['library_id'] = '00000000-0000-0000-0000-000000000000'
    path.write_bytes(storage._state_database(state))
    fresh = InvoiceLibraries(selections, settings)
    with pytest.raises(InvoiceStorageError) as error:
        fresh.reconnect(repo.library_id, 'native')
    assert error.value.code == 'LIBRARY_CHANGED'
    path.unlink()
    with pytest.raises(InvoiceStorageError) as error:
        fresh.reconnect(repo.library_id, 'native')
    assert error.value.code == 'FOLDER_UNAVAILABLE'


@pytest.mark.parametrize('data', [[], {'x': {}}, {'x': {'parent': 'relative', 'parent_identity': [], 'root_identity': [], 'label': 'x'}}, {str(i): {} for i in range(101)}])
def test_invalid_private_bindings_fail_closed(tmp_path, data):
    settings = tmp_path / 'bindings.json'
    settings.write_text(json.dumps(data))
    manager = InvoiceLibraries(FileSelectionStore(), settings)
    with pytest.raises(InvoiceStorageError) as error:
        manager.list_bindings()
    assert error.value.code == 'INVALID_BINDINGS'


def test_oversized_file_and_file_growth_are_bounded(library, monkeypatch):
    _, repo, _, _, _ = library
    monkeypatch.setattr(storage, 'MAX_DATABASE_BYTES', 1)
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.status == 413
    fstat = os.fstat
    def grown(descriptor):
        metadata = fstat(descriptor)
        if storage.stat.S_ISREG(metadata.st_mode):
            return SimpleNamespace(st_mode=metadata.st_mode, st_nlink=1, st_size=0)
        return metadata
    monkeypatch.setattr(os, 'fstat', grown)
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.status == 413


def test_special_file_lock_and_unsupported_platform(library, monkeypatch):
    _, repo, parent, _, _ = library
    lock = parent / 'officekit-invoices' / 'config' / '.invoice.lock'
    lock.unlink()
    os.mkfifo(lock)
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, lambda state: None)
    assert error.value.code == 'UNSAFE_FILE'
    monkeypatch.setattr(os, 'supports_dir_fd', set())
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.code == 'UNSUPPORTED_FILESYSTEM'


def test_binding_limit_and_corrupt_existing_asset_are_not_replaced(library, monkeypatch):
    manager, repo, parent, _, selections = library
    data = b'logo'
    digest = repo.put_asset(data)
    (parent / 'officekit-invoices' / 'assets' / 'logos' / f'{digest}.png').write_bytes(b'corrupt')
    with pytest.raises(InvoiceStorageError) as error:
        repo.put_asset(data)
    assert error.value.code == 'ASSET_CHANGED'
    manager.bindings = {str(i): {} for i in range(100)}
    selected = selections.register_native([str(parent)], 'read-write', 'native')
    with pytest.raises(InvoiceStorageError) as error:
        manager.attach(selected['id'])
    assert error.value.code == 'BINDING_CAPACITY'


def test_cleanup_does_not_unlink_a_replaced_temporary_file(library, monkeypatch):
    _, repo, parent, _, _ = library
    def replace_temporary(source, destination, *, src_dir_fd, dst_dir_fd):
        os.rename(source, 'owned-interrupted', src_dir_fd=src_dir_fd, dst_dir_fd=src_dir_fd)
        fd = os.open(source, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=src_dir_fd)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(b'unrelated replacement')
        raise OSError(errno.ENOSPC, 'full')
    monkeypatch.setattr(os, 'replace', replace_temporary)
    with pytest.raises(InvoiceStorageError):
        repo.transaction(0, lambda state: None)
    remaining = list((parent / 'officekit-invoices' / 'config').glob('.invoice-*'))
    assert len(remaining) == 1
    assert remaining[0].read_bytes() == b'unrelated replacement'


def test_sqlite_history_and_complete_backup_restore_roundtrip(library, tmp_path):
    manager, repo, parent, _, selections = library
    original_id = repo.library_id
    repo.transaction(0, lambda state: state['businesses'].update(studio={'name': 'Studio', 'currency': 'USD'}))
    repo.transaction(1, lambda state: state['documents'].update(invoice={'number': 'INV-001'}))
    logo = repo.put_asset(b'normalized-logo')
    document = '00000000-0000-0000-0000-000000000042'
    relative = repo.archive_document(document, '2026-10-26', b'%PDF-1.7\ninvoice')
    assert relative == f'data/2026/10/{document}.pdf'
    assert repo.archive_document(document, '2026-10-26', b'%PDF-1.7\ninvoice') == relative
    assert [entry['revision'] for entry in repo.history()] == [0, 1, 2]
    backup = repo.backup()
    path = tmp_path / 'backup.zip'
    path.write_bytes(backup)
    destination = tmp_path / 'restored'
    destination.mkdir()
    selection = selections.register_native([str(destination)], 'read-write', 'native')['id']
    backup_selection = selections.register_native([str(path)], 'read', 'native')['id']
    restored = manager.restore(selection, backup_selection)
    assert restored['id'] == original_id
    restored_repo = manager.get(original_id)
    assert restored_repo.read() == repo.read()
    assert restored_repo.history() == repo.history()
    assert restored_repo.read_asset(logo) == b'normalized-logo'
    assert (destination / 'officekit-invoices' / relative).read_bytes() == b'%PDF-1.7\ninvoice'
    assert list((parent / 'officekit-invoices' / 'backups').glob('*.zip'))
    assert not (parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3-wal').exists()
    with pytest.raises(InvoiceStorageError) as error:
        manager.restore(selection, backup_selection)
    assert error.value.code == 'RESTORE_DESTINATION_EXISTS'


def test_archive_validation_and_existing_content_are_preserved(library, monkeypatch):
    _, repo, _, _, _ = library
    document = '00000000-0000-0000-0000-000000000001'
    for args in (('../outside', '2026-10-26', b'%PDF-ok'), (document, 'bad-date', b'%PDF-ok'),
                 (document, '2026-10-26', b'not pdf')):
        with pytest.raises(InvoiceStorageError):
            repo.archive_document(*args)
    repo.archive_document(document, '2026-10-26', b'%PDF-first')
    with pytest.raises(InvoiceStorageError) as error:
        repo.archive_document(document, '2026-10-26', b'%PDF-changed')
    assert error.value.code == 'ARCHIVE_CHANGED'


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize('entries', [
    [('../outside', b'bad')], [('/absolute', b'bad')], [('data/2026/10/x.pdf', b'bad')],
    [('config/officekit.sqlite3', b'corrupt')], [('assets/logos/' + 'a' * 64 + '.png', b'logo')],
])
def test_restore_rejects_unsafe_or_incomplete_archives(library, tmp_path, entries):
    manager, _, _, _, selections = library
    destination = tmp_path / 'restore'
    destination.mkdir()
    archive = tmp_path / 'backup.zip'
    archive.write_bytes(zip_bytes(entries))
    target_id = selections.register_native([str(destination)], 'read-write', 'native')['id']
    source_id = selections.register_native([str(archive)], 'read', 'native')['id']
    with pytest.raises(InvoiceStorageError):
        manager.restore(target_id, source_id)
    assert not (destination / 'officekit-invoices').exists()


def test_history_events_are_safe_and_preserved(library):
    _, repo, _, _, _ = library
    event = {'action': 'invoice-issued', 'business_id': '00000000-0000-0000-0000-000000000001', 'document_id': '00000000-0000-0000-0000-000000000002'}
    repo.transaction(0, lambda state: None, event)
    entry = repo.history()[-1]
    assert entry['summary'] == 'invoice issued'
    assert entry['business_id'] == event['business_id']
    assert entry['document_id'] == event['document_id']
    for invalid in ([], {'bank_details': 'secret'}, {'action': 'contains spaces'}, {'action': 1}, {'business_id': 'not uuid'}, {'document_id': 2}, {'document_id': '00000000000000000000000000000000'}):
        with pytest.raises(InvoiceStorageError) as error:
            repo.transaction(1, lambda state: None, invalid)
        assert error.value.code == 'INVALID_EVENT'
    assert repo.read()['revision'] == 1


def test_sqlite_corrupt_schema_and_inconsistent_history_are_rejected(library):
    _, repo, parent, _, _ = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    original = path.read_bytes()
    for statement in ('DROP TABLE history', 'CREATE VIEW bad AS SELECT 1', 'ALTER TABLE meta RENAME COLUMN value TO content', "INSERT INTO records VALUES ('unknown','id','{}')", "UPDATE meta SET value='{' WHERE key='library_id'"):
        connection = storage._database(original)
        connection.execute(statement)
        connection.commit()
        path.write_bytes(connection.serialize())
        connection.close()
        with pytest.raises(InvoiceStorageError):
            repo.reload()
    state = repo._state
    with pytest.raises(InvoiceStorageError) as error:
        storage._state_database(state, original)
    assert error.value.code == 'INVALID_DATABASE'


def test_backup_without_optional_files_and_archive_capacities(library, monkeypatch):
    _, repo, _, _, _ = library
    assert set(storage._unpack_backup(repo.backup())) == {'config/officekit.sqlite3'}
    document = '00000000-0000-0000-0000-000000000001'
    for args in (('00000000000000000000000000000001', '2026-10-26', b'%PDF-x'), (document, '2026-10-26', 'text')):
        with pytest.raises(InvoiceStorageError):
            repo.archive_document(*args)
    monkeypatch.setattr(storage, 'MAX_PDF_BYTES', 5)
    with pytest.raises(InvoiceStorageError):
        repo.archive_document(document, '2026-10-26', b'%PDF-too-large')
    monkeypatch.setattr(storage, 'MAX_DATABASE_BYTES', 1)
    with pytest.raises(InvoiceStorageError) as error:
        storage._state_database(repo._state)
    assert error.value.code == 'LIBRARY_CAPACITY'


def test_backup_rejects_unexpected_folder_files_and_file_counts(library, monkeypatch):
    _, repo, parent, _, _ = library
    assets = parent / 'officekit-invoices' / 'assets'
    assets.mkdir()
    unexpected = assets / 'other'
    unexpected.mkdir()
    with pytest.raises(InvoiceStorageError) as error:
        repo.backup()
    assert error.value.code == 'INVALID_BACKUP'
    unexpected.rmdir()
    unexpected.write_bytes(b'unrelated')
    with pytest.raises(InvoiceStorageError) as error:
        repo.backup()
    assert error.value.code == 'INVALID_BACKUP'
    unexpected.unlink()
    repo.put_asset(b'logo')
    monkeypatch.setattr(storage, 'MAX_BACKUP_FILES', 0)
    with pytest.raises(InvoiceStorageError) as error:
        repo.backup()
    assert error.value.code == 'BACKUP_CAPACITY'


def test_archive_path_validation_and_zip_limits(library, monkeypatch):
    _, repo, _, _, _ = library
    database = storage._state_database(repo.read())
    for raw in (b'', b'not zip', 'not bytes'):
        with pytest.raises(InvoiceStorageError):
            storage._unpack_backup(raw)
    with pytest.raises(InvoiceStorageError, match='no database'):
        storage._unpack_backup(zip_bytes([]))
    pdf_name = 'data/2026/10/00000000-0000-0000-0000-000000000001.pdf'
    with pytest.raises(InvoiceStorageError, match='archived invoice'):
        storage._unpack_backup(zip_bytes([('config/officekit.sqlite3', database), (pdf_name, b'notpdf')]))
    with pytest.warns(UserWarning):
        duplicates = zip_bytes([('config/officekit.sqlite3', database), ('config/officekit.sqlite3', database)])
    with pytest.raises(InvoiceStorageError, match='unsafe or repeated'):
        storage._unpack_backup(duplicates)
    monkeypatch.setattr(storage, 'MAX_BACKUP_FILES', 0)
    with pytest.raises(InvoiceStorageError, match='too many files'):
        storage._unpack_backup(zip_bytes([('config/officekit.sqlite3', database)]))
    monkeypatch.setattr(storage, 'MAX_BACKUP_FILES', 10000)
    monkeypatch.setattr(storage, 'MAX_DATABASE_BYTES', 1)
    with pytest.raises(InvoiceStorageError, match='file in the invoice backup'):
        storage._unpack_backup(zip_bytes([('config/officekit.sqlite3', database)]))


def test_restore_selection_type_and_identity_checks(library, tmp_path):
    manager, repo, _, _, selections = library
    backup = tmp_path / 'backup.zip'
    backup.write_bytes(repo.backup())
    folder = tmp_path / 'restore'
    folder.mkdir()
    destination = selections.register_native([str(folder)], 'read-write', 'native')['id']
    source = selections.register_native([str(backup)], 'read', 'native')['id']
    for dest, src in (('missing', source), (destination, 'missing'), (source, destination)):
        with pytest.raises(InvoiceStorageError):
            manager.restore(dest, src)
    backup.rename(backup.with_suffix('.moved'))
    backup.write_bytes(b'replacement')
    with pytest.raises(InvoiceStorageError) as error:
        manager.restore(destination, source)
    assert error.value.code == 'BACKUP_CHANGED'
    source = selections.register_native([str(backup.with_suffix('.moved'))], 'read', 'native')['id']
    folder.rename(folder.with_name('moved-folder'))
    folder.mkdir()
    with pytest.raises(InvoiceStorageError) as error:
        manager.restore(destination, source)
    assert error.value.code == 'FOLDER_CHANGED'


def test_special_files_never_block_reads(library):
    _, repo, parent, _, _ = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(InvoiceStorageError) as error:
        repo.read()
    assert error.value.code == 'UNSAFE_FILE'


def test_bad_bindings_do_not_block_app_start_or_get_overwritten(tmp_path):
    settings = tmp_path / 'bindings.json'
    settings.write_bytes(b'corrupt settings')
    manager = InvoiceLibraries(FileSelectionStore(), settings)
    for operation in (manager.list_bindings, lambda: manager.attach('missing'), lambda: manager.reconnect('missing', 'native')):
        with pytest.raises(InvoiceStorageError):
            operation()
    assert settings.read_bytes() == b'corrupt settings'


def test_restore_requires_folder_and_file_shapes(library, tmp_path):
    manager, repo, parent, _, selections = library
    backup = tmp_path / 'backup.zip'
    backup.write_bytes(repo.backup())
    file_selection = selections.register_native([str(backup)], 'read-write', 'native')['id']
    folder_selection = selections.register_native([str(parent)], 'read-write', 'native')['id']
    for dest, src in ((file_selection, file_selection), (folder_selection, folder_selection)):
        with pytest.raises(InvoiceStorageError) as error:
            manager.restore(dest, src)
        assert error.value.code == 'INVALID_FOLDER'


def test_compressed_backup_expansion_and_aggregate_limits(library, monkeypatch):
    _, repo, _, _, _ = library
    database = storage._state_database(repo.read())
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('config/officekit.sqlite3', database)
    monkeypatch.setattr(storage, 'MAX_BACKUP_BYTES', len(database) - 1)
    with pytest.raises(InvoiceStorageError, match='expands'):
        storage._unpack_backup(output.getvalue())
    with pytest.raises(InvoiceStorageError, match='supported capacity'):
        repo.backup()
    monkeypatch.setattr(storage, 'MAX_BACKUP_BYTES', 512 * 1024 * 1024)
    monkeypatch.setattr(storage, 'MAX_BACKUP_FILES', 1)
    repo.put_asset(b'logo')
    with pytest.raises(InvoiceStorageError, match='supported capacity'):
        repo.backup()


def test_directory_identity_is_rechecked_at_context_exit(library):
    _, repo, parent, _, _ = library
    with pytest.raises(InvoiceStorageError, match='during access'):
        with repo._directory():
            (parent / 'officekit-invoices').rename(parent / 'moved-library')
            (parent / 'officekit-invoices').mkdir()


def test_sqlite_integrity_failure_and_query_error_are_fixed(library, monkeypatch):
    _, repo, _, _, _ = library
    class BadIntegrity:
        closed = False
        def execute(self, sql):
            return self
        def executescript(self, sql):
            return self
        def fetchone(self):
            return ('not ok',)
        def close(self):
            self.closed = True
    failed = BadIntegrity()
    with monkeypatch.context() as patch:
        patch.setattr(storage.sqlite3, 'connect', lambda *args: failed)
        with pytest.raises(InvoiceStorageError):
            storage._database()
    assert failed.closed
    class BadQuery:
        closed = False
        def execute(self, sql):
            raise storage.sqlite3.OperationalError('private error')
        def close(self):
            self.closed = True
    query = BadQuery()
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_database', lambda *args: query)
        with pytest.raises(InvoiceStorageError) as error:
            storage._state_from_database(b'input')
        assert error.value.code == 'INVALID_DATABASE'
    assert query.closed
    source = BadIntegrity()
    target = BadIntegrity()
    source.backup = lambda destination: None
    connections = iter((source, target))
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_database', lambda *args: next(connections))
        with pytest.raises(InvoiceStorageError, match='verification'):
            repo.backup()
    assert source.closed and target.closed


def test_external_edit_during_temporary_database_fsync_is_preserved(library, monkeypatch):
    _, repo, parent, _, _ = library
    path = parent / 'officekit-invoices' / 'config' / 'officekit.sqlite3'
    original_sync = os.fsync
    calls = 0
    def sync_and_edit(descriptor):
        nonlocal calls
        original_sync(descriptor)
        calls += 1
        if calls == 3:
            latest = repo.read()
            latest['revision'] = 99
            path.write_bytes(storage._state_database(latest))
    monkeypatch.setattr(os, 'fsync', sync_and_edit)
    with pytest.raises(InvoiceStorageError) as error:
        repo.transaction(0, lambda state: None)
    assert error.value.code == 'REVISION_CONFLICT'
    assert storage._state_from_database(path.read_bytes())['revision'] == 99


def test_backup_selected_file_swap_after_stat_is_rejected(library, tmp_path, monkeypatch):
    manager, repo, _, _, selections = library
    backup = tmp_path / 'selected.zip'
    backup.write_bytes(repo.backup())
    folder = tmp_path / 'destination'
    folder.mkdir()
    source = selections.register_native([str(backup)], 'read', 'native')['id']
    destination = selections.register_native([str(folder)], 'read-write', 'native')['id']
    original_open = os.open
    swapped = False
    def swap(name, flags, *args, **kwargs):
        nonlocal swapped
        if name == backup.name and not swapped:
            swapped = True
            backup.rename(backup.with_suffix('.old'))
            backup.write_bytes(backup.with_suffix('.old').read_bytes())
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', swap)
    monkeypatch.setattr(os, 'supports_dir_fd', os.supports_dir_fd | {swap})
    with pytest.raises(InvoiceStorageError) as error:
        manager.restore(destination, source)
    assert error.value.code == 'BACKUP_CHANGED'
    assert not (folder / 'officekit-invoices').exists()


@pytest.mark.parametrize('field,value', [('parent_identity', 1), ('root_identity', []), ('parent_identity', [True, 2]), ('label', []), ('label', ''), ('label', 'x' * 161)])
def test_malformed_binding_identity_is_invoice_only_error(library, field, value):
    _, repo, _, settings, selections = library
    bindings = json.loads(settings.read_bytes())
    bindings[repo.library_id][field] = value
    settings.write_text(json.dumps(bindings))
    manager = InvoiceLibraries(selections, settings)
    with pytest.raises(InvoiceStorageError) as error:
        manager.reconnect(repo.library_id, 'native')
    assert error.value.code == 'INVALID_BINDINGS'
