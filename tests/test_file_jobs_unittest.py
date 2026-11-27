import time
import pytest
from pydantic import ValidationError
from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_file_jobs import FileJobRequest, FileJobStore


def await_job(jobs, key):
    for _ in range(200):
        value = jobs.status(key)
        if value['state'] not in {'queued', 'running'}:
            return value
        time.sleep(.005)
    pytest.fail('Job did not terminate')


def test_direct_hash_and_type(tmp_path):
    source = tmp_path / 'hello.txt'
    source.write_bytes(b'hello')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    request = FileJobRequest(kind='hash', selectionIds=[ref], options={'algorithm': 'sha256'})
    job = jobs.submit(request)
    status = await_job(jobs, job['id'])
    assert status['state'] == 'ready'
    report = jobs.result(job['id'])
    assert report['files'][0]['digest'] == '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    assert list(tmp_path.iterdir()) == [source]
    jobs.close()


def test_strict_job_options():
    with pytest.raises(ValidationError):
        FileJobRequest(kind='hash', selectionIds=['invalid'], options={'path': '/etc/passwd'})
    with pytest.raises(ValidationError):
        FileJobRequest(kind='hash', selectionIds=['00000000-0000-0000-0000-000000000000'], options={'algorithm': 'md5'})


def test_rename_preview_apply_original(tmp_path):
    source = tmp_path / 'hello.txt'
    source.write_bytes(b'hello')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], access='read-write', credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    preview = jobs.submit(FileJobRequest(kind='rename-preview', selectionIds=[ref], options={'prefix': 'item'}))
    assert await_job(jobs, preview['id'])['state'] == 'ready'
    preview_id = jobs.result(preview['id'])['previewId']
    apply = jobs.submit(FileJobRequest(kind='rename-apply', selectionIds=[ref], options={'previewId': preview_id}))
    assert await_job(jobs, apply['id'])['state'] == 'ready'
    assert (tmp_path / 'item001.txt').read_bytes() == b'hello'
    assert not source.exists()
    jobs.close()


@pytest.mark.parametrize('kind,options', [('file-type', {}), ('storage', {'topN': 1}), ('duplicates', {})])
def test_scan_reports(tmp_path, kind, options):
    (tmp_path / 'a.txt').write_bytes(b'hello')
    (tmp_path / 'b.txt').write_bytes(b'hello')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(tmp_path)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    job = jobs.submit(FileJobRequest(kind=kind, selectionIds=[ref], options=options))
    status = await_job(jobs, job['id'])
    assert status['state'] == 'ready'
    report = jobs.result(job['id'])
    if kind == 'file-type':
        assert report['total_files'] == 2
        assert report['files'][0]['mime_type'] == 'text/plain'
    elif kind == 'storage':
        assert report['total_size_bytes'] == 10
        assert len(report['largest_files']) == 1
        row = report['largest_files'][0]
        assert row['created_at'] is None or row['created_at'].endswith('Z')
        assert row['modified_at'].endswith('Z')
    else:
        assert sorted(report['groups'][0]['files']) == ['a.txt', 'b.txt']
        assert status['kind'] == 'duplicates'
        assert status['total'] == 2
        assert status['phase'] == 'Complete'
        assert status['insights']['duplicateGroups'] == 1
        assert status['insights']['extraCopies'] == 1
        assert status['insights']['potentialRecoveryBytes'] == 5
    assert b'complete' in jobs.export(job['id'])
    with pytest.raises(ValueError):
        jobs.result(job['id'], limit=201)
    with pytest.raises(FileExistsError):
        jobs.cancel(job['id'])
    jobs.close()


def test_split_join_round_trip_and_archive_extract(tmp_path):
    source = tmp_path / 'input.bin'
    source.write_bytes(b'abcd' * 1000)
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    ref = selections.register_native([str(source)], credential='secret')['id']
    archive = tmp_path / 'split.zip'
    grant = selections.register_output(str(archive), 'file', 'split', credential='secret')['id']
    split = jobs.submit(FileJobRequest(kind='split', selectionIds=[ref], options={'chunkSize': 1024}, outputGrantId=grant))
    assert await_job(jobs, split['id'])['state'] == 'ready'
    archive_ref = selections.register_native([str(archive)], credential='secret')['id']
    joined = tmp_path / 'joined.bin'
    grant = selections.register_output(str(joined), 'file', 'join', credential='secret')['id']
    join = jobs.submit(FileJobRequest(kind='join', selectionIds=[archive_ref], outputGrantId=grant))
    assert await_job(jobs, join['id'])['state'] == 'ready'
    assert joined.read_bytes() == source.read_bytes()
    extract_path = tmp_path / 'extracted'
    grant = selections.register_output(str(extract_path), 'directory', 'archive-extract', credential='secret')['id']
    extract = jobs.submit(FileJobRequest(kind='archive-extract', selectionIds=[archive_ref], outputGrantId=grant))
    assert await_job(jobs, extract['id'])['state'] == 'ready'
    assert (extract_path / 'manifest.json').exists()
    jobs.close()


def test_archive_traversal_and_stale_preview_fail_safely(tmp_path):
    import zipfile
    source = tmp_path / 'bad.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('../escape', b'bad')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    ref = selections.register_native([str(source)], credential='secret')['id']
    destination = tmp_path / 'output'
    grant = selections.register_output(str(destination), 'directory', 'archive-extract', credential='secret')['id']
    job = jobs.submit(FileJobRequest(kind='archive-extract', selectionIds=[ref], outputGrantId=grant))
    assert await_job(jobs, job['id'])['state'] == 'failed'
    assert not destination.exists()
    assert not (tmp_path.parent / 'escape').exists()
    ref = selections.register_native([str(source)], access='read-write', credential='secret')['id']
    with pytest.raises(FileExistsError):
        jobs.submit(FileJobRequest(kind='rename-apply', selectionIds=[ref], options={'previewId': '00000000-0000-0000-0000-000000000000'}))
    jobs.close()


def test_compare_and_similarity(tmp_path):
    from PIL import Image
    left = tmp_path / 'left'
    right = tmp_path / 'right'
    left.mkdir()
    right.mkdir()
    (left / 'same').write_bytes(b'a')
    (right / 'same').write_bytes(b'a')
    (left / 'different').write_bytes(b'a')
    (right / 'different').write_bytes(b'b')
    (left / 'only').write_bytes(b'a')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    refs = [selections.register_native([str(path)], credential='secret')['id'] for path in [left, right]]
    job = jobs.submit(FileJobRequest(kind='compare-folders', selectionIds=refs))
    assert await_job(jobs, job['id'])['state'] == 'ready'
    assert {row['name']: row['status'] for row in jobs.result(job['id'])['files']} == {'same': 'equal', 'different': 'different', 'only': 'only-left'}
    pictures = tmp_path / 'pictures'
    pictures.mkdir()
    for name in ['a.png', 'b.png']:
        Image.new('RGB', (32, 32), 'blue').save(pictures / name)
    ref = selections.register_native([str(pictures)], credential='secret')['id']
    job = jobs.submit(FileJobRequest(kind='similar-images', selectionIds=[ref]))
    assert await_job(jobs, job['id'])['state'] == 'ready'
    assert jobs.result(job['id'])['groups'][0]['files'] == ['a.png', 'b.png']
    jobs.close()


def test_archive_create_and_destination_collision(tmp_path):
    import zipfile
    source = tmp_path / 'original.txt'
    source.write_bytes(b'original')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    ref = selections.register_native([str(source)], credential='secret')['id']
    target = tmp_path / 'output.zip'
    grant = selections.register_output(str(target), 'file', 'archive-create', credential='secret')['id']
    job = jobs.submit(FileJobRequest(kind='archive-create', selectionIds=[ref], outputGrantId=grant))
    assert await_job(jobs, job['id'])['state'] == 'ready'
    with zipfile.ZipFile(target) as archive:
        assert archive.read('original.txt') == b'original'
    grant = selections.register_output(str(tmp_path / 'collision.zip'), 'file', 'archive-create', credential='secret')['id']
    (tmp_path / 'collision.zip').write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        jobs.submit(FileJobRequest(kind='archive-create', selectionIds=[ref], outputGrantId=grant))
    assert (tmp_path / 'collision.zip').read_bytes() == b'keep'
    jobs.close()


def test_archive_create_keeps_unicode_member_names_and_content(tmp_path):
    # F06 Unicode: a non-ASCII name and content round-trip; names compare NFC because macOS may store NFD.
    import unicodedata
    import zipfile
    source = tmp_path / 'café-日本.txt'
    source.write_text('résumé 日本語', encoding='utf-8')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    ref = selections.register_native([str(source)], credential='secret')['id']
    target = tmp_path / 'unicode.zip'
    grant = selections.register_output(str(target), 'file', 'archive-create', credential='secret')['id']
    job = jobs.submit(FileJobRequest(kind='archive-create', selectionIds=[ref], outputGrantId=grant))
    assert await_job(jobs, job['id'])['state'] == 'ready'
    with zipfile.ZipFile(target) as archive:
        names = [unicodedata.normalize('NFC', name) for name in archive.namelist()]
        assert names == [unicodedata.normalize('NFC', 'café-日本.txt')]
        assert archive.read(archive.namelist()[0]).decode('utf-8') == 'résumé 日本語'
    assert source.read_text(encoding='utf-8') == 'résumé 日本語'
    jobs.close()


def test_archive_create_into_the_selected_folder_fails_closed_and_keeps_sources(tmp_path):
    # PM-3 / QA-10 (F06 "output in source scope"): the selection is the folder, and the ZIP is written
    # inside it. The job must refuse, publish no ZIP, leave no temporary file, and leave the sources unchanged.
    source_folder = tmp_path / 'src'
    source_folder.mkdir()
    (source_folder / 'a.txt').write_text('alpha')
    (source_folder / 'b.txt').write_text('beta')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    ref = selections.register_native([str(source_folder)], access='read-write', credential='secret')['id']
    target = source_folder / 'out.zip'
    grant = selections.register_output(str(target), 'file', 'archive-create', credential='secret')['id']
    job = jobs.submit(FileJobRequest(kind='archive-create', selectionIds=[ref], outputGrantId=grant))
    status = await_job(jobs, job['id'])
    assert status['state'] == 'failed'
    assert status['error'] == 'The output file is inside the selected folder. Choose another place to save it.'
    assert not target.exists()
    assert not any(path.name.startswith('.officekit-output-') for path in source_folder.iterdir())
    assert (source_folder / 'a.txt').read_text() == 'alpha'
    assert (source_folder / 'b.txt').read_text() == 'beta'
    assert sorted(path.name for path in source_folder.iterdir()) == ['a.txt', 'b.txt']
    jobs.close()


def test_archive_create_cancelled_before_writing_publishes_nothing_and_keeps_source(tmp_path, monkeypatch):
    # PM-3 (F06 "cancellation"): a cancelled archive-create leaves no output and no temporary file,
    # and the source file is unchanged.
    source = tmp_path / 'source.txt'
    source.write_bytes(b'keep me')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    tasks = []
    monkeypatch.setattr(jobs.executor, 'submit', lambda *args: tasks.append(args))
    ref = selections.register_native([str(source)], credential='secret')['id']
    target = tmp_path / 'cancelled.zip'
    grant = selections.register_output(str(target), 'file', 'archive-create', credential='secret')['id']
    job = jobs.submit(FileJobRequest(kind='archive-create', selectionIds=[ref], outputGrantId=grant))
    assert jobs.cancel(job['id'])['cancellationRequested']
    function, queued, queued_grant = tasks.pop()
    function(queued, queued_grant)
    assert jobs.status(job['id'])['state'] == 'cancelled'
    assert not target.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ['source.txt']
    assert source.read_bytes() == b'keep me'
    jobs.close()


@pytest.mark.parametrize('member', ['absolute', 'symlink'])
def test_archive_extract_refuses_absolute_and_symlink_members(tmp_path, member):
    # PM-3 (F07 "absolute paths/symlinks"): such members fail the job before anything is written.
    import stat
    import zipfile
    archive_path = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('ok.txt', b'fine')
        if member == 'absolute':
            archive.writestr('/absolute.txt', b'bad')
        else:
            link = zipfile.ZipInfo('link')
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, '/etc/passwd')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    ref = selections.register_native([str(archive_path)], credential='secret')['id']
    destination = tmp_path / 'output'
    grant = selections.register_output(str(destination), 'directory', 'archive-extract', credential='secret')['id']
    job = jobs.submit(FileJobRequest(kind='archive-extract', selectionIds=[ref], outputGrantId=grant))
    status = await_job(jobs, job['id'])
    assert status['state'] == 'failed'
    assert status['error'] == 'Unsafe archive member'
    assert not destination.exists()
    assert not (tmp_path / 'absolute.txt').exists()
    assert not (tmp_path / 'output' / 'link').exists()
    jobs.close()


def test_deterministic_cancellation_queue_expiry_and_limits(tmp_path, monkeypatch):
    from officekit.engines import engine_file_jobs as module
    source = tmp_path / 'source'
    source.write_bytes(b'a')
    now = [0.0]
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, clock=lambda: now[0], release_profile='development')
    tasks = []
    monkeypatch.setattr(jobs.executor, 'submit', lambda *args: tasks.append(args))
    job_ref = jobs.submit({'kind': 'hash', 'selectionIds': [ref]})
    with pytest.raises(FileExistsError):
        jobs.result(job_ref['id'])
    with pytest.raises(FileExistsError):
        jobs.export(job_ref['id'])
    assert jobs.cancel(job_ref['id'])['cancellationRequested']
    function, job, grant = tasks.pop()
    function(job, grant)
    assert jobs.status(job_ref['id'])['state'] == 'cancelled'
    now[0] = 1801
    with pytest.raises(FileNotFoundError):
        jobs.status(job_ref['id'])
    monkeypatch.setattr(module, 'MAX_PENDING', 0)
    with pytest.raises(RuntimeError):
        jobs.submit({'kind': 'hash', 'selectionIds': [ref]})
    jobs.close()


def test_rename_rollback_stale_and_unsafe_names(tmp_path, monkeypatch):
    from officekit.engines import engine_file_jobs as module
    source = tmp_path / 'source.txt'
    source.write_bytes(b'keep')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], access='read-write', credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    preview = jobs.submit({'kind': 'rename-preview', 'selectionIds': [ref], 'options': {'prefix': 'target'}})
    assert await_job(jobs, preview['id'])['state'] == 'ready'
    preview_id = jobs.result(preview['id'])['previewId']
    original_rename = module.exclusive_rename
    def fail_publication(src, dst, parent_fd):
        if dst == 'target001.txt':
            raise OSError('injected publication failure')
        return original_rename(src, dst, parent_fd)
    monkeypatch.setattr(module, 'exclusive_rename', fail_publication)
    apply = jobs.submit({'kind': 'rename-apply', 'selectionIds': [ref], 'options': {'previewId': preview_id}})
    assert await_job(jobs, apply['id'])['state'] == 'failed'
    assert jobs.result(apply['id'])['rollback'] == 'complete'
    assert source.read_bytes() == b'keep'
    with pytest.raises(FileExistsError):
        jobs.submit({'kind': 'rename-apply', 'selectionIds': [ref], 'options': {'previewId': preview_id}})
    for name in ['', '..', 'bad/name', 'bad:name', 'a' * 241]:
        with pytest.raises(ValueError):
            jobs._safe_name(name)
    jobs.close()


@pytest.mark.parametrize('payload', [
    {'kind': 'storage', 'selectionIds': ['BAD']},
    {'kind': 'storage', 'selectionIds': ['00000000-0000-0000-0000-000000000000'] * 2},
    {'kind': 'compare-folders', 'selectionIds': ['00000000-0000-0000-0000-000000000000']},
    {'kind': 'split', 'selectionIds': ['00000000-0000-0000-0000-000000000000']},
    {'kind': 'hash', 'selectionIds': ['00000000-0000-0000-0000-000000000000'], 'outputGrantId': 'not-allowed'},
])
def test_discriminated_scope_and_grant_contract(payload):
    with pytest.raises(ValidationError):
        FileJobRequest.model_validate(payload)


@pytest.mark.parametrize('manifest', [
    {'bad': []},
    {'name': 'input', 'chunks': [{'bad': 'part'}]},
    {'name': 'input', 'chunks': [{'name': 'part', 'size': 99, 'sha256': 'wrong'}]},
])
def test_join_rejects_corrupt_manifest_and_preserves_destination(tmp_path, manifest):
    import json
    import zipfile
    source = tmp_path / 'bad.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr('part', b'content')
    selections = FileSelectionStore(native_token='secret')
    jobs = FileJobStore(selections, release_profile='development')
    ref = selections.register_native([str(source)], credential='secret')['id']
    destination = tmp_path / 'output'
    grant = selections.register_output(str(destination), 'file', 'join', credential='secret')['id']
    job = jobs.submit({'kind': 'join', 'selectionIds': [ref], 'outputGrantId': grant})
    assert await_job(jobs, job['id'])['state'] == 'failed'
    assert not destination.exists()
    assert not list(tmp_path.glob('.officekit-output-*'))
    jobs.close()


def test_report_and_output_bounds(tmp_path, monkeypatch):
    from officekit.engines import engine_file_jobs as module
    source = tmp_path / 'source'
    source.write_bytes(b'large')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    monkeypatch.setattr(module, 'MAX_REPORT_BYTES', 1)
    job = jobs.submit({'kind': 'hash', 'selectionIds': [ref]})
    assert await_job(jobs, job['id'])['state'] == 'failed'
    monkeypatch.setattr(module, 'MAX_REPORT_BYTES', 32 * 1024 ** 2)
    monkeypatch.setattr(module, 'MAX_OUTPUT_BYTES', 1)
    destination = tmp_path / 'output'
    grant = selections.register_output(str(destination), 'file', 'archive-create', credential='secret')['id']
    job = jobs.submit({'kind': 'archive-create', 'selectionIds': [ref], 'outputGrantId': grant})
    assert await_job(jobs, job['id'])['state'] == 'failed'
    assert not destination.exists()
    jobs.close()


def test_output_never_overwrites_and_split_streams_multiple_blocks(tmp_path, monkeypatch):
    from officekit.engines import engine_file_jobs as module
    source = tmp_path / 'source'
    source.write_bytes(b'a' * 4097)
    target = tmp_path / 'target'
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    grant = selections.register_output(str(target), 'file', 'split', credential='secret')['id']
    monkeypatch.setattr(module, 'CHUNK_BYTES', 512)
    job = jobs.submit({'kind': 'split', 'selectionIds': [ref], 'options': {'chunkSize': 2048}, 'outputGrantId': grant})
    assert await_job(jobs, job['id'])['state'] == 'ready'
    assert target.read_bytes().startswith(b'PK')
    assert source.read_bytes() == b'a' * 4097
    jobs.close()


def test_revocation_mutation_lock_and_queued_cancel(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.write_bytes(b'a')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    tasks = []
    monkeypatch.setattr(jobs.executor, 'submit', lambda *args: tasks.append(args))
    result = jobs.submit({'kind': 'hash', 'selectionIds': [ref]})
    job = jobs.jobs[result['id']]
    job.mutation = True
    with pytest.raises(FileExistsError):
        jobs.revoke_selection(ref)
    job.mutation = False
    jobs.revoke_selection(ref)
    assert job.cancel.is_set()
    function, job, grant = tasks.pop()
    function(job, grant)
    assert jobs.status(result['id'])['state'] == 'cancelled'
    jobs.close()


def test_similarity_errors_and_pixel_caps(tmp_path, monkeypatch):
    from PIL import Image
    from officekit.engines import engine_file_jobs as module
    source = tmp_path / 'image.png'
    Image.new('RGB', (32, 32), 'blue').save(source)
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    monkeypatch.setattr(module.SimilarImageEngine, 'MAX_PIXELS', 1)
    job = jobs.submit({'kind': 'similar-images', 'selectionIds': [ref]})
    assert await_job(jobs, job['id'])['state'] == 'ready'
    assert not jobs.result(job['id'])['complete']
    monkeypatch.setattr(module.SimilarImageEngine, 'MAX_FILES', 0)
    job = jobs.submit({'kind': 'similar-images', 'selectionIds': [ref]})
    assert await_job(jobs, job['id'])['state'] == 'failed'
    monkeypatch.setattr(module.SimilarImageEngine, 'MAX_FILES', 10)
    monkeypatch.setattr(module.SimilarImageEngine, 'MAX_PIXELS', 10000)
    Image.new('RGBA', (32, 32), (0, 0, 255, 100)).save(source)
    job = jobs.submit({'kind': 'similar-images', 'selectionIds': [ref]})
    assert await_job(jobs, job['id'])['state'] == 'ready'
    assert jobs.result(job['id'])['complete']
    jobs.close()


def test_rename_noop_collision_and_expired_preview(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_bytes(b'a')
    (tmp_path / 'target001.txt').write_bytes(b'keep')
    now = [0.0]
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], access='read-write', credential='secret')['id']
    jobs = FileJobStore(selections, clock=lambda: now[0], release_profile='development')
    collision = jobs.submit({'kind': 'rename-preview', 'selectionIds': [ref], 'options': {'prefix': 'target'}})
    assert await_job(jobs, collision['id'])['state'] == 'failed'
    preview = jobs.submit({'kind': 'rename-preview', 'selectionIds': [ref], 'options': {'pattern_type': 'affix'}})
    assert await_job(jobs, preview['id'])['state'] == 'ready'
    key = jobs.result(preview['id'])['previewId']
    apply = jobs.submit({'kind': 'rename-apply', 'selectionIds': [ref], 'options': {'previewId': key}})
    assert await_job(jobs, apply['id'])['state'] == 'ready'
    assert jobs.result(apply['id'])['renamed'] == 0
    preview = jobs.submit({'kind': 'rename-preview', 'selectionIds': [ref], 'options': {'prefix': 'new'}})
    assert await_job(jobs, preview['id'])['state'] == 'ready'
    key = jobs.result(preview['id'])['previewId']
    jobs.previews[key]['expires'] = -1
    from officekit.engines.engine_file_jobs import Job
    with pytest.raises(FileExistsError):
        jobs._rename(Job(FileJobRequest(kind='rename-apply', selectionIds=[ref], options={'previewId': key})), key)
    jobs.close()


@pytest.mark.parametrize('kind', ['split', 'join', 'archive-extract'])
def test_single_input_output_operations_reject_multiple_files(tmp_path, kind):
    (tmp_path / 'a').write_bytes(b'a')
    (tmp_path / 'b').write_bytes(b'b')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(tmp_path)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    target = tmp_path.parent / (tmp_path.name + '-out')
    grant = selections.register_output(str(target), 'directory' if kind == 'archive-extract' else 'file', kind, credential='secret')['id']
    job = jobs.submit({'kind': kind, 'selectionIds': [ref], 'outputGrantId': grant})
    assert await_job(jobs, job['id'])['state'] == 'failed'
    assert not target.exists()
    jobs.close()


def test_output_grant_guards_and_manifest_size_limits(tmp_path, monkeypatch):
    import json
    import zipfile
    from dataclasses import replace
    from officekit.engines import engine_file_jobs as module
    from officekit.engines.engine_file_jobs import Job
    with pytest.raises(ValidationError):
        FileJobRequest(kind='hash', selectionIds=['ABCDEFAB-1234-1234-1234-123456789012'])
    source = tmp_path / 'source.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('manifest.json', json.dumps({'name': 'source', 'chunks': [{'name': 'part', 'size': 4, 'sha256': 'bad'}]}))
        archive.writestr('part', b'data')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    request = FileJobRequest(kind='join', selectionIds=[ref], outputGrantId='unused')
    job = Job(request)
    with pytest.raises(ValueError):
        jobs._output(job, None)
    output_ref = selections.register_output(str(tmp_path / 'out'), 'file', 'join', credential='secret')['id']
    grant = selections.consume_output(output_ref, 'join')
    with pytest.raises(FileExistsError):
        jobs._output(job, replace(grant, parent_identity=(-1, -1)))
    with pytest.raises(ValueError):
        jobs._output(job, replace(grant, kind='directory'))
    monkeypatch.setattr(module, 'MAX_REPORT_BYTES', 1)
    with pytest.raises(ValueError, match='manifest'):
        jobs._output(job, grant)
    monkeypatch.setattr(module, 'MAX_REPORT_BYTES', 10000)
    monkeypatch.setattr(module, 'MAX_OUTPUT_BYTES', 1)
    with pytest.raises(ValueError, match='Archive'):
        jobs._output(job, grant)
    monkeypatch.setattr(jobs, '_validate_archive', lambda archive: None)
    with pytest.raises(ValueError, match='Joined'):
        jobs._output(job, grant)
    jobs.close()


def test_split_limit_and_directory_members_and_extraction_rollback(tmp_path, monkeypatch):
    import zipfile
    from officekit.engines import engine_file_jobs as module
    source = tmp_path / 'source'
    source.write_bytes(b'data')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    monkeypatch.setattr(module, 'MAX_OUTPUT_BYTES', 1)
    grant = selections.register_output(str(tmp_path / 'split'), 'file', 'split', credential='secret')['id']
    result = jobs.submit({'kind': 'split', 'selectionIds': [ref], 'outputGrantId': grant})
    assert await_job(jobs, result['id'])['state'] == 'failed'
    monkeypatch.setattr(module, 'MAX_OUTPUT_BYTES', 10000)
    archive_path = tmp_path / 'archive.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('folder/', b'')
        archive.writestr('folder/file', b'data')
    ref = selections.register_native([str(archive_path)], credential='secret')['id']
    target = tmp_path / 'extract'
    grant = selections.register_output(str(target), 'directory', 'archive-extract', credential='secret')['id']
    original_rename = module.exclusive_rename
    def failure(src, dst, parent_fd):
        if dst == 'extract':
            raise OSError('injected publish failure')
        return original_rename(src, dst, parent_fd)
    monkeypatch.setattr(module, 'exclusive_rename', failure)
    result = jobs.submit({'kind': 'archive-extract', 'selectionIds': [ref], 'outputGrantId': grant})
    assert await_job(jobs, result['id'])['state'] == 'failed'
    assert not target.exists()
    jobs.close()


@pytest.mark.parametrize('phase', ['target-collision', 'source-change', 'rollback-partial', 'rollback-published', 'rollback-target-replaced'])
def test_rename_races_and_recovery(tmp_path, monkeypatch, phase):
    from officekit.engines import engine_file_jobs as module
    sources = [tmp_path / 'a.txt', tmp_path / 'b.txt']
    for source in sources:
        source.write_bytes(b'keep')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(tmp_path)], access='read-write', credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    preview = jobs.submit({'kind': 'rename-preview', 'selectionIds': [ref], 'options': {'prefix': 'target'}})
    assert await_job(jobs, preview['id'])['state'] == 'ready'
    key = jobs.result(preview['id'])['previewId']
    original_rename = module.exclusive_rename
    calls = [0]
    def injected_rename(src, dst, parent_fd):
        calls[0] += 1
        if phase == 'source-change' and calls[0] == 1:
            result = original_rename(src, dst, parent_fd)
            descriptor = module.os.open(dst, module.os.O_WRONLY, dir_fd=parent_fd)
            module.os.write(descriptor, b'changed')
            module.os.close(descriptor)
            return result
        if phase == 'rollback-partial' and calls[0] >= 3:
            raise OSError('injected publish and rollback failure')
        if phase in {'rollback-published', 'rollback-target-replaced'} and calls[0] == 4:
            if phase == 'rollback-target-replaced':
                target = tmp_path / 'target001.txt'
                target.unlink()
                target.write_bytes(b'user-owned replacement')
            raise OSError('injected second publish failure')
        return original_rename(src, dst, parent_fd)
    if phase == 'target-collision':
        (tmp_path / 'target001.txt').write_bytes(b'keep-target')
    else:
        monkeypatch.setattr(module, 'exclusive_rename', injected_rename)
    apply = jobs.submit({'kind': 'rename-apply', 'selectionIds': [ref], 'options': {'previewId': key}})
    assert await_job(jobs, apply['id'])['state'] == 'failed'
    if phase.startswith('rollback'):
        assert jobs.result(apply['id'])['rollback'] == ('partial' if phase in {'rollback-partial', 'rollback-target-replaced'} else 'complete')
        recovery = jobs.result(apply['id'])['files']
        assert len(recovery) == 2
        assert all('oldName' in row and 'newName' in row and 'currentName' in row for row in recovery)
        assert str(tmp_path) not in str(recovery)
        if phase == 'rollback-partial':
            assert all(row['state'] == 'staged' and row['temporaryName'].startswith('.officekit-rename-') for row in recovery)
        elif phase == 'rollback-target-replaced':
            assert any(row['state'] == 'changed-or-missing' for row in recovery)
            assert any(row['state'] == 'restored' for row in recovery)
        else:
            assert all(row['state'] == 'restored' for row in recovery)
    if phase == 'rollback-target-replaced':
        assert (tmp_path / 'target001.txt').read_bytes() == b'user-owned replacement'
    jobs.close()


def test_rename_platform_without_directory_descriptors(tmp_path, monkeypatch):
    import contextlib
    from officekit.engines import engine_file_jobs as module
    @contextlib.contextmanager
    def fallback(path):
        yield None
    monkeypatch.setattr(module, 'open_parent', fallback)
    source = tmp_path / 'source.txt'
    source.write_bytes(b'keep')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], access='read-write', credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    preview = jobs.submit({'kind': 'rename-preview', 'selectionIds': [ref], 'options': {'prefix': 'new'}})
    assert await_job(jobs, preview['id'])['state'] == 'ready'
    key = jobs.result(preview['id'])['previewId']
    apply = jobs.submit({'kind': 'rename-apply', 'selectionIds': [ref], 'options': {'previewId': key}})
    assert await_job(jobs, apply['id'])['state'] == 'failed'
    assert source.read_bytes() == b'keep'
    jobs.close()


def test_rename_reserves_selection_against_concurrent_jobs(tmp_path, monkeypatch):
    source = tmp_path / 'source.txt'
    source.write_bytes(b'keep')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], access='read-write', credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    preview = jobs.submit({'kind': 'rename-preview', 'selectionIds': [ref], 'options': {'prefix': 'new'}})
    assert await_job(jobs, preview['id'])['state'] == 'ready'
    key = jobs.result(preview['id'])['previewId']
    tasks = []
    monkeypatch.setattr(jobs.executor, 'submit', lambda *args: tasks.append(args))
    jobs.submit({'kind': 'rename-apply', 'selectionIds': [ref], 'options': {'previewId': key}})
    with pytest.raises(FileExistsError):
        jobs.submit({'kind': 'hash', 'selectionIds': [ref]})
    duplicate_ref = selections.register_native([str(source)], credential='secret')['id']
    with pytest.raises(FileExistsError):
        jobs.submit({'kind': 'hash', 'selectionIds': [duplicate_ref]})
    with pytest.raises(FileExistsError):
        jobs.submit({'kind': 'rename-apply', 'selectionIds': [ref], 'options': {'previewId': key}})
    function, job, grant = tasks.pop()
    function(job, grant)
    assert job.state == 'ready'
    jobs.close()


def test_mutation_and_revocation_commit_point_is_atomic(tmp_path, monkeypatch):
    import threading
    from officekit.engines.engine_file_jobs import Job
    source = tmp_path / 'source'
    source.write_bytes(b'keep')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    job = Job(FileJobRequest(kind='hash', selectionIds=[ref]), state='running')
    jobs.jobs['test'] = job
    checks = []
    original_check = jobs._check
    def checked_under_mutation_lock(current):
        attempts = []
        def competing_revoke_lock():
            acquired = jobs.lock.acquire(blocking=False)
            attempts.append(acquired)
            if acquired:
                jobs.lock.release()
        thread = threading.Thread(target=competing_revoke_lock)
        thread.start()
        thread.join()
        assert attempts == [False]
        checks.append(current)
        original_check(current)
    monkeypatch.setattr(jobs, '_check', checked_under_mutation_lock)
    jobs._begin_mutation(job)
    assert checks == [job]
    assert job.mutation
    with pytest.raises(FileExistsError):
        jobs.revoke_selection(ref)
    jobs.close()


def test_retained_reports_global_budget_and_expired_eviction(tmp_path, monkeypatch):
    from officekit.engines import engine_file_jobs as module
    from officekit.engines.engine_file_jobs import Job
    source = tmp_path / 'source'
    source.write_bytes(b'keep')
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(source)], credential='secret')['id']
    now = [0.0]
    jobs = FileJobStore(selections, clock=lambda: now[0], release_profile='development')
    request = FileJobRequest(kind='hash', selectionIds=[ref])
    monkeypatch.setattr(module, 'MAX_RETAINED_REPORT_BYTES', 40)
    first, second, third = Job(request, state='ready', expires=10), Job(request, state='ready', expires=20), Job(request, state='running')
    jobs.jobs['first'] = first
    jobs._retain_result(first, {'value': 'a' * 20})
    jobs.jobs['second'] = second
    jobs._retain_result(second, {'value': 'b' * 20})
    with pytest.raises(FileNotFoundError):
        jobs.status('first')
    assert sum(job.result_bytes for job in jobs.jobs.values()) <= 40
    now[0] = 21
    jobs.jobs['third'] = third
    jobs._retain_result(third, {'value': 'c'})
    assert 'second' not in jobs.jobs
    assert jobs.jobs['third'].result == {'value': 'c'}
    with pytest.raises(ValueError):
        jobs._retain_result(third, {'value': 'x' * 100})
    third.state = 'ready'
    third.expires = 30
    jobs.close()


def test_failed_recovery_report_is_downloadable(tmp_path, monkeypatch):
    from officekit.engines.engine_file_jobs import Job
    selections = FileSelectionStore(native_token='secret')
    source = tmp_path / 'source'
    source.write_bytes(b'a')
    ref = selections.register_native([str(source)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    job = Job(FileJobRequest(kind='hash', selectionIds=[ref]), state='failed', expires=jobs.clock() + 100)
    jobs.jobs['recovery'] = job
    jobs._retain_result(job, {'rollback': 'partial', 'recoveryRequired': True, 'files': [{'temporaryName': '.officekit-stage'}]})
    assert b'.officekit-stage' in jobs.export('recovery')
    jobs.close()


def test_similar_images_filters_non_images_and_permission_error(tmp_path, monkeypatch):
    from PIL import Image
    pictures = tmp_path / 'mixed_folder'
    pictures.mkdir()
    (pictures / 'notes.txt').write_text('not an image')
    (pictures / 'runner.pkg').write_bytes(b'binary data')
    (pictures / 'package.json').write_text('{}')
    for name in ['photo1.png', 'photo2.png']:
        Image.new('RGB', (32, 32), 'red').save(pictures / name)
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(pictures)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')
    job = jobs.submit(FileJobRequest(kind='similar-images', selectionIds=[ref]))
    assert await_job(jobs, job['id'])['state'] == 'ready'
    result = jobs.result(job['id'])
    assert result['scanned_images'] == 2
    assert result['groups'][0]['files'] == ['photo1.png', 'photo2.png']

    # Test permission error handling
    def mock_files_permission_error(job, key=None):
        raise PermissionError('Simulated TCC denial')
    monkeypatch.setattr(jobs, '_files', mock_files_permission_error)
    job_perm = jobs.submit(FileJobRequest(kind='similar-images', selectionIds=[ref]))
    perm_status = await_job(jobs, job_perm['id'])
    assert perm_status['state'] == 'failed'
    assert 'Permission denied' in perm_status['error']
    jobs.close()


def test_all_tools_consistent_permission_and_empty_handling(tmp_path, monkeypatch):
    empty_folder = tmp_path / 'empty_folder'
    empty_folder.mkdir()
    selections = FileSelectionStore(native_token='secret')
    ref = selections.register_native([str(empty_folder)], credential='secret')['id']
    jobs = FileJobStore(selections, release_profile='development')

    # Empty folder handling for rename-preview
    rename_job = jobs.submit(FileJobRequest(kind='rename-preview', selectionIds=[ref]))
    rename_status = await_job(jobs, rename_job['id'])
    assert rename_status['state'] == 'failed'
    assert 'No files found' in rename_status['error']

    # Empty folder handling for archive-create
    grant = selections.register_output(str(tmp_path / 'out.zip'), 'file', 'archive-create', credential='secret')['id']
    zip_job = jobs.submit(FileJobRequest(kind='archive-create', selectionIds=[ref], outputGrantId=grant))
    zip_status = await_job(jobs, zip_job['id'])
    assert zip_status['state'] == 'failed'
    assert 'No files found' in zip_status['error']

    # PermissionError on root folder triggers Permission required phase
    def mock_files_permission(job, key=None):
        raise PermissionError('Simulated folder access denial')
    monkeypatch.setattr(jobs, '_files', mock_files_permission)
    hash_job = jobs.submit(FileJobRequest(kind='hash', selectionIds=[ref]))
    hash_status = await_job(jobs, hash_job['id'])
    assert hash_status['state'] == 'failed'
    assert hash_status['phase'] == 'Permission required'
    assert 'Permission denied' in hash_status['error']
    jobs.close()

