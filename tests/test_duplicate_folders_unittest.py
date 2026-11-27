import os
import uuid
import pytest
from officekit.engines.engine_file_jobs import FileJobStore
from officekit.engines.engine_file_selections import FileSelectionStore
from tests.test_file_jobs_unittest import await_job


def scan(jobs, selection, **options):
    key = jobs.submit({'kind': 'duplicates', 'selectionIds': [selection], 'options': options})['id']
    assert await_job(jobs, key)['state'] == 'ready'
    return key, jobs.jobs[key].result


def test_recursive_default_and_exact_folder_structure(tmp_path):
    for name in ['Project', 'Project backup', 'different-name', 'extra-file', 'extra-directory']:
        folder = tmp_path / name
        (folder / 'empty').mkdir(parents=True)
        (folder / 'document.txt').write_text('same bytes')
    (tmp_path / 'different-name' / 'document.txt').rename(tmp_path / 'different-name' / 'renamed.txt')
    (tmp_path / 'extra-file' / 'additional.txt').write_text('extra')
    (tmp_path / 'extra-directory' / 'another-empty').mkdir()
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(tmp_path)], 'read-write', 'fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    try:
        _, files = scan(jobs, selection)
        assert files['files_scanned'] == 6
        assert files['include_subfolders'] is True
        assert all(os.path.isabs(entry['full_path']) for group in files['groups'] for entry in group['entries'])
        key, report = scan(jobs, selection, matchKind='folders')
        status = jobs.status(key)
        matched = [set(group['files']) for group in report['groups']]
        assert {'Project', 'Project backup'} in matched
        assert not any('different-name' in names or 'extra-file' in names or 'extra-directory' in names for names in matched)
        assert any('Project/empty' in names and 'Project backup/empty' in names for names in matched)
        assert report['match_kind'] == 'folders' and report['complete'] is True
        assert report['trash_supported'] is False
        assert status['total'] == report['files_scanned']
        assert status['insights']['inspectionOnly'] is True
        assert status['insights']['matchedFolderBytes'] == 10
        group = next(group for group in report['groups'] if 'Project' in group['files'])
        assert group['size_bytes'] == 10
        assert all(entry['file_count'] == 1 for entry in group['entries'])
        entry = next(entry for entry in group['entries'] if entry['name'] == 'Project')
        assert jobs.reveal_path(key, entry['id']) == str(tmp_path / 'Project')
        with pytest.raises(FileExistsError):
            jobs.submit({'kind':'duplicate-trash', 'selectionIds':[selection],
                         'options':{'sourceJobId':key, 'fileIds':[entry['id']]}})
    finally:
        jobs.close()


def test_folder_match_rejects_different_bytes_and_skipped_links(tmp_path):
    for name, content in [('one', '111'), ('two', '222'), ('linked', '111')]:
        folder = tmp_path / name
        folder.mkdir()
        (folder / 'file.txt').write_text(content)
    (tmp_path / 'linked' / 'link').symlink_to(tmp_path / 'two')
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(tmp_path)], credential='fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    try:
        _, report = scan(jobs, selection, matchKind='folders')
        assert report['groups'] == []
        assert report['complete'] is False and report['skipped_links'] == 1
    finally:
        jobs.close()


def test_reveal_is_scan_bound_and_rejects_changed_or_revoked_files(tmp_path):
    for name in ['a', 'b']:
        (tmp_path / name).write_text('same')
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(tmp_path)], credential='fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    try:
        key, report = scan(jobs, selection)
        entry = report['groups'][0]['entries'][0]
        assert jobs.reveal_path(key, entry['id']) == str(tmp_path / entry['name'])
        with pytest.raises(FileNotFoundError):
            jobs.reveal_path(key, str(uuid.uuid4()))
        (tmp_path / entry['name']).write_text('changed')
        with pytest.raises(FileExistsError):
            jobs.reveal_path(key, entry['id'])
        selections.revoke(selection)
        with pytest.raises(FileNotFoundError):
            jobs.reveal_path(key, entry['id'])
    finally:
        jobs.close()


def test_folder_scan_rejects_file_changed_after_hashing(tmp_path, monkeypatch):
    for name in ['one', 'two']:
        (tmp_path / name).mkdir()
        (tmp_path / name / 'file.txt').write_text('same')
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(tmp_path)], credential='fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    digest = jobs._digest
    def change_after_digest(item, job):
        result = digest(item, job)
        with open(item.path, 'w') as output:
            output.write('changed after hashing')
        return result
    monkeypatch.setattr(jobs, '_digest', change_after_digest)
    try:
        key = jobs.submit({'kind':'duplicates', 'selectionIds':[selection], 'options':{'matchKind':'folders'}})['id']
        assert await_job(jobs, key)['state'] == 'failed'
    finally:
        jobs.close()


def test_folder_scan_rejects_individual_files_and_limits_work(tmp_path, monkeypatch):
    from officekit.engines import engine_file_jobs as module
    file = tmp_path / 'file.txt'
    file.write_text('fixture')
    selections = FileSelectionStore(native_token='fixture')
    jobs = FileJobStore(selections, release_profile='development')
    try:
        for selected in [file, tmp_path]:
            selection = selections.register_native([str(selected)], credential='fixture')['id']
            monkeypatch.setattr(module, 'MAX_ENTRIES', 0)
            key = jobs.submit({'kind':'duplicates', 'selectionIds':[selection], 'options':{'matchKind':'folders'}})['id']
            assert await_job(jobs, key)['state'] == 'failed'
    finally:
        jobs.close()


def test_overlapping_folder_roots_do_not_count_the_same_path_twice(tmp_path):
    for name in ['one', 'two']:
        (tmp_path / name).mkdir()
        (tmp_path / name / 'file.txt').write_text('same')
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(tmp_path), str(tmp_path / 'one')], credential='fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    try:
        _, report = scan(jobs, selection, matchKind='folders')
        assert report['folders_scanned'] == 3
        assert report['files_scanned'] == 2
        assert len(report['groups']) == 1
        paths = [entry['full_path'] for entry in report['groups'][0]['entries']]
        assert sorted(paths) == sorted([str(tmp_path / 'one'), str(tmp_path / 'two')])
    finally:
        jobs.close()


def test_reveal_rejects_replaced_root_even_when_file_identity_survives(tmp_path):
    root = tmp_path / 'selected'
    root.mkdir()
    for name in ['a', 'b']:
        (root / name).write_text('same')
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(root)], credential='fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    try:
        key, report = scan(jobs, selection)
        entry = report['groups'][0]['entries'][0]
        root.rename(tmp_path / 'moved')
        root.mkdir()
        os.link(tmp_path / 'moved' / entry['name'], root / entry['name'])
        with pytest.raises(FileExistsError, match='Selected root changed'):
            jobs.reveal_path(key, entry['id'])
    finally:
        jobs.close()


def test_folder_scan_rejects_changed_directory_structure(tmp_path, monkeypatch):
    for name in ['one', 'two']:
        (tmp_path / name).mkdir()
        (tmp_path / name / 'file.txt').write_text('same')
    selections = FileSelectionStore(native_token='fixture')
    selection = selections.register_native([str(tmp_path)], credential='fixture')['id']
    jobs = FileJobStore(selections, release_profile='development')
    digest = jobs._digest
    def change_directory(item, job):
        result = digest(item, job)
        os.utime(os.path.dirname(item.path), ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        return result
    monkeypatch.setattr(jobs, '_digest', change_directory)
    try:
        key = jobs.submit({'kind':'duplicates', 'selectionIds':[selection], 'options':{'matchKind':'folders'}})['id']
        assert await_job(jobs, key)['state'] == 'failed'
    finally:
        jobs.close()
