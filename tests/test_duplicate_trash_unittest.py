"""Duplicate cleanup uses disposable fixtures, never the developer's Trash."""
import os
import uuid
import pytest
from pydantic import ValidationError
from officekit.engines.engine_file_jobs import FileJobRequest, FileJobStore
from officekit.engines.engine_file_selections import FileSelectionStore, identity
from tests.test_file_jobs_unittest import await_job


@pytest.fixture
def duplicate_fixture(tmp_path):
    folder = tmp_path / 'selected'
    folder.mkdir()
    for name in ['a.txt', 'b.txt', 'c.txt']:
        (folder / name).write_text('identical fixture')
    trash = tmp_path / 'disposable-trash'
    trash.mkdir()
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(folder)], 'read-write', 'fixture')['id']

    def move(path, expected):
        assert identity(os.stat(path)) == expected
        os.rename(path, trash / os.path.basename(path))

    jobs = FileJobStore(selections, trash=move, release_profile='development')
    scan = jobs.submit({'kind': 'duplicates', 'selectionIds': [selection]})['id']
    assert await_job(jobs, scan)['state'] == 'ready'
    entries = jobs.result(scan)['groups'][0]['entries']
    yield folder, trash, selections, selection, jobs, scan, entries
    jobs.executor.shutdown(wait=True)


def request(selection, scan, ids):
    return {'kind': 'duplicate-trash', 'selectionIds': [selection], 'options': {'sourceJobId': scan, 'fileIds': ids}}


def test_duplicate_cleanup_keeps_one_original_and_moves_only_selected_copies(duplicate_fixture):
    folder, trash, selections, selection, jobs, scan, entries = duplicate_fixture
    cleanup = jobs.submit(request(selection, scan, [entry['id'] for entry in entries[1:]]))['id']
    assert await_job(jobs, cleanup)['state'] == 'ready'
    assert jobs.result(cleanup)['moved_count'] == 2
    assert jobs.result(cleanup)['complete'] is True
    assert [file.name for file in folder.iterdir()] == ['a.txt']
    assert sorted(file.name for file in trash.iterdir()) == ['b.txt', 'c.txt']
    assert (folder / 'a.txt').read_text() == 'identical fixture'
    with pytest.raises(FileNotFoundError):
        selections.get(selection)


def test_duplicate_cleanup_rejects_all_files_unknown_ids_and_read_only_authority(duplicate_fixture):
    folder, trash, selections, selection, jobs, scan, entries = duplicate_fixture
    for ids in [[entry['id'] for entry in entries], [str(uuid.uuid4())]]:
        with pytest.raises(ValueError):
            jobs.submit(request(selection, scan, ids))
    selections.get(selection).access = 'read'
    with pytest.raises(PermissionError):
        jobs.submit(request(selection, scan, [entries[1]['id']]))
    assert len(list(folder.iterdir())) == 3
    assert not list(trash.iterdir())


@pytest.mark.parametrize('changed', ['a.txt', 'b.txt'])
def test_duplicate_cleanup_rejects_changed_keeper_or_copy_before_any_move(duplicate_fixture, changed):
    folder, trash, _, selection, jobs, scan, entries = duplicate_fixture
    (folder / changed).write_text('changed since scan')
    cleanup = jobs.submit(request(selection, scan, [entries[1]['id'], entries[2]['id']]))['id']
    assert await_job(jobs, cleanup)['state'] == 'failed'
    assert len(list(folder.iterdir())) == 3
    assert not list(trash.iterdir())


@pytest.mark.parametrize('failure', [PermissionError, RuntimeError])
def test_duplicate_cleanup_reports_partial_failure_without_claiming_all_copies_moved(duplicate_fixture, failure):
    folder, trash, _, selection, jobs, scan, entries = duplicate_fixture
    move = jobs.trash

    def fail_one(path, expected):
        if path.endswith('c.txt'):
            raise failure('fixture denied')
        move(path, expected)

    jobs.trash = fail_one
    cleanup = jobs.submit(request(selection, scan, [entry['id'] for entry in entries[1:]]))['id']
    assert await_job(jobs, cleanup)['state'] == 'ready'
    result = jobs.result(cleanup)
    assert result['moved_count'] == 1 and result['complete'] is False
    assert [item['state'] for item in result['items']] == ['trashed', 'failed']
    assert (folder / 'a.txt').exists() and (folder / 'c.txt').exists()
    assert (trash / 'b.txt').exists()


def test_duplicate_cleanup_cannot_use_a_different_or_revoked_selection(duplicate_fixture, tmp_path):
    _, _, selections, selection, jobs, scan, entries = duplicate_fixture
    other = tmp_path / 'other'
    other.mkdir()
    ref = selections.register_native([str(other)], 'read-write', 'fixture')['id']
    with pytest.raises(FileExistsError):
        jobs.submit(request(ref, scan, [entries[1]['id']]))
    selections.revoke(selection)
    with pytest.raises(FileNotFoundError):
        jobs.submit(request(selection, scan, [entries[1]['id']]))


def test_duplicate_cleanup_rejects_replaced_symlink_and_expired_scan(duplicate_fixture, tmp_path):
    folder, trash, _, selection, jobs, scan, entries = duplicate_fixture
    outside = tmp_path / 'outside'
    outside.write_text('outside must stay unchanged')
    (folder / 'b.txt').unlink()
    (folder / 'b.txt').symlink_to(outside)
    cleanup = jobs.submit(request(selection, scan, [entries[1]['id']]))['id']
    assert await_job(jobs, cleanup)['state'] == 'failed'
    assert outside.read_text() == 'outside must stay unchanged'
    assert not list(trash.iterdir())
    jobs.jobs[scan].expires = jobs.clock() - 1
    with pytest.raises(FileNotFoundError):
        jobs.submit(request(selection, scan, [entries[1]['id']]))


def test_duplicate_cleanup_has_bounded_unique_ids_and_strict_options():
    selection, scan, file = [str(uuid.uuid4()) for _ in range(3)]
    for ids in [[], [file, file], ['../private-file'], [str(uuid.uuid4()) for _ in range(10001)]]:
        with pytest.raises(ValidationError):
            FileJobRequest.model_validate(request(selection, scan, ids))
    body = request(selection, scan, [file])
    body['options']['path'] = '/private/unselected'
    with pytest.raises(ValidationError):
        FileJobRequest.model_validate(body)


@pytest.mark.parametrize('recursive', [None, False, True])
def test_duplicate_scan_scope_dates_and_outside_links(tmp_path, recursive):
    root = tmp_path / 'Downloads'
    nested = root / 'subfolder'
    nested.mkdir(parents=True)
    for path in [root / 'a.txt', root / 'b.txt', nested / 'copy.txt']:
        path.write_text('identical')
        os.utime(path, (1700000000, 1700000000))
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'outside.txt').write_text('identical')
    (root / 'linked-folder').symlink_to(outside, target_is_directory=True)
    (root / 'linked-file').symlink_to(outside / 'outside.txt')
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(root)], 'read-write', 'fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    try:
        options = {} if recursive is None else {'includeSubfolders': recursive}
        scan = jobs.submit({'kind': 'duplicates', 'selectionIds': [selection], 'options': options})['id']
        assert await_job(jobs, scan)['state'] == 'ready'
        report = jobs.result(scan)
        expected = ['a.txt', 'b.txt'] if recursive is False else ['a.txt', 'b.txt', 'subfolder/copy.txt']
        assert report['groups'][0]['files'] == expected
        assert report['files_scanned'] == len(expected)
        assert report['include_subfolders'] is (recursive is not False)
        assert all(entry['modified_at'] == '2023-11-14T22:13:20Z' for entry in report['groups'][0]['entries'])
    finally:
        jobs.executor.shutdown(wait=True)


@pytest.mark.parametrize('invalid', ['true', 1, None, [], {}])
def test_duplicate_scan_rejects_non_boolean_scope(invalid):
    with pytest.raises(ValidationError):
        FileJobRequest.model_validate({'kind': 'duplicates', 'selectionIds': [str(uuid.uuid4())],
                                       'options': {'includeSubfolders': invalid}})
