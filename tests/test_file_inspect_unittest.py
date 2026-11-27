"""Engine tests for the pending file tools (track A): synthetic temporary trees only."""

import hashlib
import os
import time

import pytest

from officekit.engines import engine_file_inspect as inspect_module
from officekit.engines.engine_file_selections import FileSelectionStore, MAX_SKIPPED_ROWS
from officekit.engines.engine_file_jobs import FileJobStore

TOKEN = 'secret'
IS_ROOT = hasattr(os, 'geteuid') and os.geteuid() == 0


def await_job(jobs, key):
    for _ in range(400):
        value = jobs.status(key)
        if value['state'] not in {'queued', 'running'}:
            return value
        time.sleep(.005)
    pytest.fail('Job did not terminate')


@pytest.fixture
def stores():
    selections = FileSelectionStore(native_token=TOKEN)
    jobs = FileJobStore(selections, release_profile='development')
    yield selections, jobs
    jobs.close()
    selections.close()


def run(stores, path, kind, options=None, roots=None):
    selections, jobs = stores
    paths = roots if roots is not None else [str(path)]
    ref = selections.register_native(paths, credential=TOKEN)['id']
    key = jobs.submit({'kind': kind, 'selectionIds': [ref], 'options': options or {}})['id']
    status = await_job(jobs, key)
    return status, (jobs.result(key) if status['state'] == 'ready' else None)


def skip_if_root(reason='permission bits do not apply to root'):
    if IS_ROOT:
        pytest.skip(reason)


# --- shared walker stats (engine_file_selections) ----------------------------

def test_walk_without_stats_keeps_default_behaviour(tmp_path):
    (tmp_path / 'plain.txt').write_text('x')
    (tmp_path / 'link').symlink_to(tmp_path / 'plain.txt')
    selections = FileSelectionStore(native_token=TOKEN)
    ref = selections.register_native([str(tmp_path)], credential=TOKEN)['id']
    names = sorted(item.name for item in selections.iter_files(ref))
    assert names == ['plain.txt']


def test_walk_records_links_and_special_entries_when_stats_given(tmp_path):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('FIFO unsupported')
    (tmp_path / 'plain.txt').write_text('x')
    (tmp_path / 'link').symlink_to(tmp_path / 'plain.txt')
    os.mkfifo(tmp_path / 'pipe')
    selections = FileSelectionStore(native_token=TOKEN)
    ref = selections.register_native([str(tmp_path)], credential=TOKEN)['id']
    stats = {}
    names = sorted(item.name for item in selections.iter_files(ref, stats=stats))
    assert names == ['plain.txt']
    assert stats['skipped_links'] == 1
    assert stats['special'] == 1
    assert sorted(stats['rows']) == [('link', 'link'), ('pipe', 'special')]
    assert stats.get('rows_dropped', 0) == 0


def test_walk_caps_skipped_rows_and_counts_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr('officekit.engines.engine_file_selections.MAX_SKIPPED_ROWS', 2)
    (tmp_path / 'target').write_text('x')
    for index in range(5):
        (tmp_path / f'link{index}').symlink_to(tmp_path / 'target')
    selections = FileSelectionStore(native_token=TOKEN)
    ref = selections.register_native([str(tmp_path)], credential=TOKEN)['id']
    stats = {}
    list(selections.iter_files(ref, stats=stats))
    assert stats['skipped_links'] == 5
    assert len(stats['rows']) == 2
    assert stats['rows_dropped'] == 3


def test_walk_records_denied_subfolder_and_keeps_root_readable(tmp_path):
    skip_if_root()
    (tmp_path / 'open.txt').write_text('x')
    locked = tmp_path / 'locked'
    locked.mkdir()
    (locked / 'hidden.txt').write_text('x')
    locked.chmod(0)
    try:
        selections = FileSelectionStore(native_token=TOKEN)
        ref = selections.register_native([str(tmp_path)], credential=TOKEN)['id']
        stats = {}
        names = sorted(item.name for item in selections.iter_files(ref, stats=stats))
        assert names == ['open.txt']
        assert stats['denied_folders'] == 1
        assert stats['rows'] == [('locked', 'denied')]
    finally:
        locked.chmod(0o755)


def test_skipped_row_cap_constant_is_the_contract_value():
    assert MAX_SKIPPED_ROWS == 10_000


def test_file_job_store_requires_an_explicit_release_profile():
    # ARCH-3: a caller that forgets the profile must fail loudly, not expose development kinds.
    selections = FileSelectionStore(native_token=TOKEN)
    try:
        with pytest.raises(TypeError):
            FileJobStore(selections)
    finally:
        selections.close()


def test_private_beta_refuses_development_kinds_before_any_selection_lookup():
    from officekit.engines.engine_file_inspect import DEVELOPMENT_ONLY_KINDS
    from officekit.engines.engine_file_jobs import ReleaseScopeError
    selections = FileSelectionStore(native_token=TOKEN)
    beta = FileJobStore(selections, release_profile='private-beta')
    missing = '11111111-1111-1111-1111-111111111111'
    try:
        for kind in sorted(DEVELOPMENT_ONLY_KINDS):
            with pytest.raises(ReleaseScopeError, match='private beta'):
                beta.submit({'kind': kind, 'selectionIds': [missing, '22222222-2222-2222-2222-222222222222'] if kind == 'compare-files' else [missing], 'options': {'notBefore': 0} if kind == 'file-age' else {}})
        assert issubclass(ReleaseScopeError, PermissionError)
    finally:
        beta.close()
        selections.close()


# --- file info (F02) ---------------------------------------------------------

def test_file_info_reports_metadata_and_hidden_and_links(stores, tmp_path):
    (tmp_path / 'report.TXT').write_bytes(b'hello')
    (tmp_path / '.secret').write_bytes(b'')
    os.link(tmp_path / 'report.TXT', tmp_path / 'report-copy.TXT')
    (tmp_path / 'dangling').symlink_to(tmp_path / 'does-not-exist')
    status, report = run(stores, tmp_path, 'file-info', {'includeSubfolders': True})
    assert status['state'] == 'ready'
    rows = {row['name']: row for row in report['files']}
    assert set(rows) == {'report.TXT', '.secret', 'report-copy.TXT'}
    assert rows['report.TXT']['size_bytes'] == 5
    assert rows['report.TXT']['extension'] == '.txt'
    assert rows['report.TXT']['hard_links'] == 2
    assert rows['.secret']['hidden'] is True
    assert rows['report.TXT']['hidden'] is False
    assert len(rows['report.TXT']['mode']) == 9
    assert report['skipped'] == [{'name': 'dangling', 'reason': 'link'}]
    assert report['skipped_links'] == 1
    assert report['total_files'] == 3
    assert report['total_bytes'] == 10
    assert report['complete'] is True
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(['report.TXT', '.secret', 'report-copy.TXT', 'dangling'])


def test_file_info_counts_skipped_rows_that_were_not_listed(stores, tmp_path, monkeypatch):
    # CR-1: the list is capped, so the result must say how many skipped items it omits.
    monkeypatch.setattr('officekit.engines.engine_file_selections.MAX_SKIPPED_ROWS', 2)
    (tmp_path / 'target').write_text('x')
    for index in range(5):
        (tmp_path / f'link{index}').symlink_to(tmp_path / 'target')
    status, report = run(stores, tmp_path, 'file-info')
    assert status['state'] == 'ready'
    assert len(report['skipped']) == 2
    assert report['skipped_truncated'] == 3
    assert report['skipped_links'] == 5


def test_file_info_defaults_to_direct_files_only(stores, tmp_path):
    (tmp_path / 'top.txt').write_text('a')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'deep.txt').write_text('b')
    _, direct = run(stores, tmp_path, 'file-info')
    assert [row['name'] for row in direct['files']] == ['top.txt']
    _, nested = run(stores, tmp_path, 'file-info', {'includeSubfolders': True})
    assert sorted(row['name'] for row in nested['files']) == ['sub/deep.txt', 'top.txt']


def test_file_info_handles_unicode_long_names_and_deep_paths(stores, tmp_path):
    nfd = 'café notes.txt'
    long_name = 'a' * 251 + '.txt'
    (tmp_path / nfd).write_text('x')
    (tmp_path / long_name).write_text('y')
    folder = tmp_path
    for _ in range(7):
        folder = folder / ('n' * 100)
        folder.mkdir()
    (folder / 'deep.txt').write_text('z')
    _, report = run(stores, tmp_path, 'file-info', {'includeSubfolders': True})
    names = {row['name'] for row in report['files']}
    assert nfd in names
    assert long_name in names
    assert any(name.endswith('/deep.txt') and len(name) > 700 for name in names)
    assert len(long_name.encode()) == 255


def test_file_info_reports_denied_folder_without_failing(stores, tmp_path):
    skip_if_root()
    (tmp_path / 'open.txt').write_text('x')
    locked = tmp_path / 'locked'
    locked.mkdir()
    (locked / 'hidden.txt').write_text('x')
    locked.chmod(0)
    try:
        _, report = run(stores, tmp_path, 'file-info', {'includeSubfolders': True})
        assert [row['name'] for row in report['files']] == ['open.txt']
        assert report['denied_folders'] == 1
        assert report['skipped'] == [{'name': 'locked', 'reason': 'denied'}]
        assert report['complete'] is False
    finally:
        locked.chmod(0o755)


def test_file_info_created_date_is_null_without_birth_time(stores, tmp_path, monkeypatch):
    (tmp_path / 'a.txt').write_text('x')
    without_birth_time(monkeypatch)
    _, report = run(stores, tmp_path, 'file-info')
    assert report['files'][0]['created_at'] is None
    assert report['platform_limits']


def test_file_info_does_not_mutate_source(stores, tmp_path):
    source = tmp_path / 'source.bin'
    source.write_bytes(os.urandom(4096))
    before = identity_of(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    run(stores, tmp_path, 'file-info')
    assert identity_of(source) == before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def identity_of(path):
    value = os.lstat(path)
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def without_birth_time(monkeypatch):
    """Simulate a platform that reports no birth time (signature index 5 is None)."""
    real = inspect_module.identity

    def unborn(value):
        return real(value)[:5] + (None,)

    monkeypatch.setattr('officekit.engines.engine_file_selections.identity', unborn)
    monkeypatch.setattr(inspect_module, 'identity', unborn)


# --- file age (F09) ----------------------------------------------------------

NS = 1_000_000_000
T0 = 1_700_000_000


def set_mtime(path, seconds_ns):
    os.utime(path, ns=(seconds_ns, seconds_ns))


def test_file_age_bounds_are_inclusive_at_the_exact_second(stores, tmp_path):
    early, edge, late = tmp_path / 'early', tmp_path / 'edge', tmp_path / 'late'
    for path in (early, edge, late):
        path.write_text('x')
    set_mtime(early, T0 * NS - 1)
    set_mtime(edge, T0 * NS)
    set_mtime(late, (T0 + 1) * NS)
    _, report = run(stores, tmp_path, 'file-age', {'notBefore': T0, 'notAfter': T0})
    assert [row['name'] for row in report['files']] == ['edge']
    assert report['matched'] == 1 and report['scanned'] == 3


def test_file_age_upper_bound_includes_the_whole_last_second(stores, tmp_path):
    inside, outside = tmp_path / 'inside', tmp_path / 'outside'
    inside.write_text('x')
    outside.write_text('x')
    set_mtime(inside, T0 * NS + 999_999_999)
    set_mtime(outside, (T0 + 1) * NS)
    _, report = run(stores, tmp_path, 'file-age', {'notAfter': T0})
    assert [row['name'] for row in report['files']] == ['inside']


def test_file_age_one_sided_ranges(stores, tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.write_text('x')
    new.write_text('x')
    set_mtime(old, (T0 - 10) * NS)
    set_mtime(new, (T0 + 10) * NS)
    _, after = run(stores, tmp_path, 'file-age', {'notBefore': T0})
    assert [row['name'] for row in after['files']] == ['new']
    _, before = run(stores, tmp_path, 'file-age', {'notAfter': T0})
    assert [row['name'] for row in before['files']] == ['old']
    assert before['not_after'] == T0 and before['not_before'] is None


def test_file_age_counts_unavailable_created_dates(stores, tmp_path, monkeypatch):
    (tmp_path / 'a.txt').write_text('x')
    without_birth_time(monkeypatch)
    _, report = run(stores, tmp_path, 'file-age', {'dateField': 'created', 'notBefore': 0})
    assert report['files'] == []
    assert report['unavailable_dates'] == 1
    assert report['date_field'] == 'created'


def test_file_age_recursion_on_and_off(stores, tmp_path):
    (tmp_path / 'top').write_text('x')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'deep').write_text('x')
    set_mtime(tmp_path / 'top', T0 * NS)
    set_mtime(tmp_path / 'sub' / 'deep', T0 * NS)
    _, flat = run(stores, tmp_path, 'file-age', {'notBefore': 0})
    assert [row['name'] for row in flat['files']] == ['top']
    _, deep = run(stores, tmp_path, 'file-age', {'notBefore': 0, 'includeSubfolders': True})
    assert sorted(row['name'] for row in deep['files']) == ['sub/deep', 'top']
    assert deep['complete'] is True


def test_file_age_denied_subfolder_marks_scan_incomplete(stores, tmp_path):
    skip_if_root()
    locked = tmp_path / 'locked'
    locked.mkdir()
    locked.chmod(0)
    try:
        _, report = run(stores, tmp_path, 'file-age', {'notBefore': 0, 'includeSubfolders': True})
        assert report['complete'] is False
    finally:
        locked.chmod(0o755)


# --- empty files (F10) -------------------------------------------------------

def test_empty_files_are_zero_byte_only(stores, tmp_path):
    (tmp_path / 'zero').write_bytes(b'')
    (tmp_path / 'space').write_text(' ')
    (tmp_path / 'newline').write_text('\n')
    (tmp_path / 'empty-link-target').write_bytes(b'')
    (tmp_path / 'alias').symlink_to(tmp_path / 'empty-link-target')
    before = identity_of(tmp_path / 'zero')
    _, report = run(stores, tmp_path, 'empty-files')
    assert [row['name'] for row in report['files']] == ['empty-link-target', 'zero']
    assert report['skipped_links'] == 1
    assert report['scanned'] == 4
    assert report['complete'] is True
    assert identity_of(tmp_path / 'zero') == before
    assert (tmp_path / 'space').read_text() == ' '


def test_empty_files_report_denied_folders(stores, tmp_path):
    skip_if_root()
    (tmp_path / 'zero').write_bytes(b'')
    locked = tmp_path / 'locked'
    locked.mkdir()
    locked.chmod(0)
    try:
        _, report = run(stores, tmp_path, 'empty-files', {'includeSubfolders': True})
        assert report['denied_folders'] == 1
        assert report['complete'] is False
        assert [row['name'] for row in report['files']] == ['zero']
    finally:
        locked.chmod(0o755)


def test_inspect_kinds_reject_bad_options_at_the_dto():
    from pydantic import ValidationError
    from officekit.engines.engine_file_jobs import FileJobRequest
    ref = '11111111-1111-1111-1111-111111111111'
    cases = (('file-info', {'includeSubfolders': 1}), ('file-info', {'extra': True}),
             ('file-age', {'notBefore': 5, 'notAfter': 4}), ('file-age', {}),
             ('file-age', {'notBefore': True}), ('file-age', {'notBefore': 1.0}),
             ('file-age', {'notAfter': 253402300800}), ('file-age', {'dateField': 'accessed', 'notBefore': 1}),
             ('empty-files', {'includeSubfolders': 'yes'}))
    for kind, options in cases:
        with pytest.raises(ValidationError):
            FileJobRequest(kind=kind, selectionIds=[ref], options=options)
    second = '22222222-2222-2222-2222-222222222222'
    with pytest.raises(ValidationError):
        FileJobRequest(kind='compare-files', selectionIds=[ref], options={})
    with pytest.raises(ValidationError):
        FileJobRequest(kind='file-info', selectionIds=[ref, second], options={})


# --- compare files (F05) -----------------------------------------------------

def run_pair(stores, first, second):
    selections, jobs = stores
    left = selections.register_native([str(first)], credential=TOKEN)['id']
    right = selections.register_native([str(second)], credential=TOKEN)['id']
    key = jobs.submit({'kind': 'compare-files', 'selectionIds': [left, right]})['id']
    status = await_job(jobs, key)
    return status, (jobs.result(key) if status['state'] == 'ready' else None)


def write_pair(folder, left, right):
    """Write two synthetic files into an existing folder; str content is UTF-8 text."""
    folder.mkdir(exist_ok=True)
    a, b = folder / 'left.dat', folder / 'right.dat'
    a.write_bytes(left.encode() if isinstance(left, str) else left)
    b.write_bytes(right.encode() if isinstance(right, str) else right)
    return a, b


def test_compare_equal_three_mib_binaries_leaves_sources_unchanged(stores, tmp_path):
    payload = os.urandom(3 * 1024 * 1024)
    a, b = write_pair(tmp_path, payload, payload)
    before = (identity_of(a), identity_of(b))
    status, report = run_pair(stores, a, b)
    assert status['state'] == 'ready'
    assert report['equal'] is True
    assert report['same_file'] is False
    assert report['mode'] == 'binary'
    assert report['first_difference_offset'] is None
    assert report['bytes_a'] is None and report['bytes_b'] is None
    assert report['sha256_a'] == report['sha256_b'] == hashlib.sha256(payload).hexdigest()
    assert report['size_a'] == report['size_b'] == len(payload)
    assert report['hunks'] == [] and report['complete'] is True
    assert (identity_of(a), identity_of(b)) == before


@pytest.mark.parametrize('position', ['first', 'middle', 'last'])
def test_one_byte_difference_is_located_exactly(stores, tmp_path, position):
    size = 3 * 1024 * 1024
    left = bytearray(os.urandom(size))
    right = bytearray(left)
    offset = {'first': 0, 'middle': size // 2, 'last': size - 1}[position]
    right[offset] = (right[offset] + 1) % 256
    a, b = write_pair(tmp_path, bytes(left), bytes(right))
    status, report = run_pair(stores, a, b)
    assert status['state'] == 'ready'
    assert report['equal'] is False
    assert report['first_difference_offset'] == offset
    assert report['bytes_a'] == bytes(left[offset:offset + 16]).hex()
    assert report['bytes_b'] == bytes(right[offset:offset + 16]).hex()
    assert report['sha256_a'] != report['sha256_b']
    assert report['mode'] == 'binary'


def test_length_only_difference_points_at_the_shorter_end(stores, tmp_path):
    base = b'abc' * 1000
    a, b = write_pair(tmp_path, base, base + b'extra')
    status, report = run_pair(stores, a, b)
    assert report['equal'] is False
    assert report['first_difference_offset'] == len(base)
    assert report['size_b'] - report['size_a'] == 5
    assert report['bytes_a'] == ''
    assert report['bytes_b'] == b'extra'.hex()


def test_utf8_bom_is_reported_as_a_difference(stores, tmp_path):
    a, b = write_pair(tmp_path, b'\xef\xbb\xbfhello\n', b'hello\n')
    status, report = run_pair(stores, a, b)
    assert report['mode'] == 'text'
    assert report['encoding_a'] == 'utf-8-bom'
    assert report['encoding_b'] == 'utf-8'
    assert report['equal'] is False
    assert report['equal_ignoring_line_endings'] is False
    assert report['first_difference_offset'] == 0


def test_line_endings_lf_vs_crlf_are_equal_ignoring_endings(stores, tmp_path):
    a, b = write_pair(tmp_path, b'one\ntwo\n', b'one\r\ntwo\r\n')
    status, report = run_pair(stores, a, b)
    assert report['mode'] == 'text'
    assert report['line_endings_a'] == 'lf'
    assert report['line_endings_b'] == 'crlf'
    assert report['equal'] is False
    assert report['equal_ignoring_line_endings'] is True
    assert report['hunks'] == []


def test_mixed_and_missing_line_endings_are_named(stores, tmp_path):
    a, b = write_pair(tmp_path, 'one\ntwo\r\nthree\r', 'no endings here')
    status, report = run_pair(stores, a, b)
    assert report['line_endings_a'] == 'mixed'
    assert report['line_endings_b'] == 'none'


def test_latin1_text_is_treated_as_binary(stores, tmp_path):
    a, b = write_pair(tmp_path, 'café\n'.encode('latin-1'), 'cafè\n'.encode('latin-1'))
    status, report = run_pair(stores, a, b)
    assert report['mode'] == 'binary'
    assert report['encoding_a'] == 'binary'
    assert report['line_endings_a'] is None
    assert report['hunks'] == []


def test_text_over_two_mib_is_too_large_for_the_view(stores, tmp_path):
    left = ('x' * 1000 + '\n') * 2100
    right = left[:-2] + 'y\n'
    a, b = write_pair(tmp_path, left, right)
    status, report = run_pair(stores, a, b)
    assert len(left.encode()) > 2 * 1024 * 1024
    assert report['mode'] == 'text-too-large'
    assert report['hunks'] == []
    assert report['equal'] is False


def test_text_hunks_show_changed_lines_with_context(stores, tmp_path):
    a, b = write_pair(tmp_path, 'a\nb\nc\nd\n', 'a\nB\nc\nd\n')
    status, report = run_pair(stores, a, b)
    assert report['mode'] == 'text'
    hunk = report['hunks'][0]
    assert (hunk['a_start'], hunk['a_lines'], hunk['b_start'], hunk['b_lines']) == (1, 4, 1, 4)
    assert [(line['op'], line['text']) for line in hunk['lines']] == [(' ', 'a'), ('-', 'b'), ('+', 'B'), (' ', 'c'), (' ', 'd')]


def test_hunks_and_lines_are_bounded_and_marked_truncated(stores, tmp_path):
    left = ''.join(f'line {index}\n' for index in range(2000))
    right = ''.join(f'LINE {index}\n' if index % 8 == 0 else f'line {index}\n' for index in range(2000))
    a, b = write_pair(tmp_path, left, right)
    status, report = run_pair(stores, a, b)
    assert len(report['hunks']) == 200
    assert report['truncated'] is True

    block_left = ''.join(f'old {index}\n' for index in range(100))
    block_right = ''.join(f'new {index}\n' for index in range(100))
    c, d = write_pair(tmp_path / 'block', block_left, block_right)
    status, report = run_pair(stores, c, d)
    assert len(report['hunks'][0]['lines']) == 40
    assert report['truncated'] is True


def test_long_lines_are_truncated_and_oversized_diffs_are_skipped(stores, tmp_path):
    a, b = write_pair(tmp_path, 'x' * 1000 + '1\n', 'x' * 1000 + '2\n')
    status, report = run_pair(stores, a, b)
    assert all(len(line['text']) <= 500 for hunk in report['hunks'] for line in hunk['lines'])
    c, d = write_pair(tmp_path / 'many', 'a\n' * 20_001, 'b\n' * 20_001)
    status, report = run_pair(stores, c, d)
    assert report['hunks'] == []
    assert report['truncated'] is True


def test_same_inode_is_reported_without_special_casing_the_bytes(stores, tmp_path):
    a, b = write_pair(tmp_path, b'same bytes', b'same bytes')
    os.link(a, tmp_path / 'alias.dat')
    status, report = run_pair(stores, a, tmp_path / 'alias.dat')
    assert report['same_file'] is True
    assert report['equal'] is True


def test_cancel_is_honoured_while_text_hunks_are_built(tmp_path):
    # CR-3: the byte loop checks twice for these small files; a cancel raised after that must
    # still stop the hunk pass instead of letting the whole diff finish.
    import io
    from types import SimpleNamespace

    class Cancelled(Exception):
        pass

    left = ''.join(f'line {index}\n' for index in range(300)).encode()
    right = ''.join(f'line {index}{"x" if index % 3 == 0 else ""}\n' for index in range(300)).encode()
    calls = []

    def check():
        calls.append(True)
        if len(calls) > 2:
            raise Cancelled()

    first = SimpleNamespace(signature=(1, 1, len(left)), data=left)
    second = SimpleNamespace(signature=(1, 2, len(right)), data=right)
    with pytest.raises(Cancelled):
        inspect_module.compare_files(first, second, check=check, open_file=lambda item: io.BytesIO(item.data))
    assert len(calls) == 3


def test_compare_peak_memory_stays_bounded(stores, tmp_path):
    # QA-3: the files must be larger than the 8 MiB bound and the 1 MiB chunk, so a whole-file read
    # (two 12 MiB buffers) fails while chunked reads (about 2 MiB) pass.
    import tracemalloc
    payload = os.urandom(12 * 1024 * 1024)
    a, b = write_pair(tmp_path, payload, payload[:-1] + bytes([payload[-1] ^ 1]))
    tracemalloc.start()
    try:
        status, report = run_pair(stores, a, b)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert status['state'] == 'ready'
    assert report['first_difference_offset'] == len(payload) - 1
    assert peak < 8 * 1024 * 1024


# --- empty folders (S05) -----------------------------------------------------

def folder_rows(report):
    return {row['name']: row for row in report['folders']}


def tree_identity(root):
    found = {}
    for current, dirs, _files in os.walk(root):
        for name in dirs:
            path = os.path.join(current, name)
            found[path] = identity_of(path)
        found[current] = identity_of(current)
    return found


def test_empty_folders_are_counted_bottom_up_with_nested_empties(stores, tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b' / 'c').mkdir(parents=True)
    (tmp_path / 'd').mkdir()
    (tmp_path / 'd' / 'file.txt').write_text('x')
    before = tree_identity(tmp_path)
    status, report = run(stores, tmp_path, 'empty-folders')
    assert status['state'] == 'ready', status
    rows = folder_rows(report)
    assert set(rows) == {'a', 'b', 'b/c'}
    assert rows['b']['state'] == 'empty'
    assert rows['b']['nested_empty_folders'] == 1
    assert rows['b']['depth'] == 1
    assert rows['b/c']['depth'] == 2
    assert rows['a']['nested_empty_folders'] == 0
    assert report['scanned_folders'] == 5
    assert report['complete'] is True
    assert tree_identity(tmp_path) == before


def test_hidden_files_only_is_reported_separately_from_empty(stores, tmp_path):
    (tmp_path / 'store').mkdir()
    (tmp_path / 'store' / '.DS_Store').write_text('x')
    (tmp_path / 'store' / 'nothing').mkdir()
    (tmp_path / 'plain').mkdir()
    _, report = run(stores, tmp_path, 'empty-folders')
    rows = folder_rows(report)
    assert rows['store']['state'] == 'hidden-files-only'
    assert rows['store']['nested_empty_folders'] == 1
    assert rows['store/nothing']['state'] == 'empty'
    assert rows['plain']['state'] == 'empty'


def test_links_inside_keep_the_folder_non_empty_and_are_not_followed(stores, tmp_path):
    target = tmp_path / 'outside'
    target.mkdir()
    (target / 'empty-inside').mkdir()
    holder = tmp_path / 'holder'
    holder.mkdir()
    (holder / 'alias').symlink_to(target)
    _, report = run(stores, tmp_path, 'empty-folders')
    rows = folder_rows(report)
    assert 'holder' not in rows
    assert 'outside' in rows and 'outside/empty-inside' in rows
    assert report['skipped_links'] == 1
    assert not any(name.startswith('holder/alias') for name in rows)


@pytest.mark.parametrize('change', ['symlink', 'replaced', 'removed'])
def test_child_changed_after_the_parent_scan_fails_closed_and_is_not_followed(stores, tmp_path, monkeypatch, change):
    # CR-2 (P-026/P-027): the parent listing records each child's identity. A child swapped for a
    # symlink (or replaced, or removed) before the child is opened must fail closed; outside entries
    # must never be counted.
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'outside-file.txt').write_text('outside')
    selected = tmp_path / 'selected'
    selected.mkdir()
    (selected / 'child').mkdir()
    real_entry_stat = inspect_module._entry_stat
    swapped = []

    def change_child_after_parent_listing(entry):
        value = real_entry_stat(entry)
        if entry.name == 'child' and not swapped:
            swapped.append(entry.path)
            os.rename(entry.path, tmp_path / 'child-aside')
            if change == 'symlink':
                os.symlink(outside, entry.path)
            elif change == 'replaced':
                os.mkdir(entry.path)
                (selected / 'child' / 'new.txt').write_text('new')
        return value

    monkeypatch.setattr(inspect_module, '_entry_stat', change_child_after_parent_listing)
    status, report = run(stores, selected, 'empty-folders')
    assert swapped, 'the change hook never fired'
    assert status['state'] == 'failed'
    assert report is None


def test_child_that_gains_an_entry_after_the_parent_scan_is_still_the_listed_folder(stores, tmp_path, monkeypatch):
    # CR-8: the open-time check compares only (device, inode) and the directory type. Writing an entry
    # into the child changes its mtime and ctime, which must not fail the job; the child is still
    # the listed folder, and it is no longer empty, so it is not reported.
    selected = tmp_path / 'selected'
    (selected / 'child').mkdir(parents=True)
    (selected / 'free').mkdir()
    real_entry_stat = inspect_module._entry_stat
    written = []

    def write_into_child_after_its_stat(entry):
        value = real_entry_stat(entry)
        if entry.name == 'child' and not written:
            written.append(entry.path)
            (selected / 'child' / 'new.txt').write_text('new')
        return value

    monkeypatch.setattr(inspect_module, '_entry_stat', write_into_child_after_its_stat)
    status, report = run(stores, selected, 'empty-folders')
    assert written, 'the change hook never fired'
    assert status['state'] == 'ready'
    assert set(folder_rows(report)) == {'free'}


def test_folder_walk_refuses_where_no_descriptor_open_is_available(stores, tmp_path, monkeypatch):
    # CR-9: without a no-follow descriptor open (Windows), the walk cannot detect junctions, so the
    # folder check fails with a fixed message instead of descending.
    (tmp_path / 'free').mkdir()
    monkeypatch.setattr(inspect_module, 'DESCRIPTOR_WALK', False)
    status, report = run(stores, tmp_path, 'empty-folders')
    assert status['state'] == 'failed'
    assert status['error'] == 'Folder checks need macOS or Linux.'
    assert report is None


def test_bundles_and_protected_subtrees_are_not_entered(stores, tmp_path):
    (tmp_path / 'App.app' / 'Contents').mkdir(parents=True)
    home = tmp_path / 'home'
    (home / '.ssh').mkdir(parents=True)
    (tmp_path / 'free').mkdir()
    _, report = run(stores, tmp_path, 'empty-folders')
    rows = folder_rows(report)
    assert set(rows) == {'free'}
    assert report['skipped_bundles'] == 1
    assert report['excluded_protected'] == 1


def test_other_volume_directories_are_skipped_not_claimed(stores, tmp_path, monkeypatch):
    (tmp_path / 'mounted' / 'inner').mkdir(parents=True)
    real = inspect_module._entry_stat

    def other_device(entry):
        value = real(entry)
        if entry.name == 'mounted':
            return type('Stat', (), {'st_dev': value.st_dev + 1, 'st_mode': value.st_mode,
                                     'st_ino': value.st_ino, 'st_size': value.st_size,
                                     'st_mtime_ns': value.st_mtime_ns, 'st_ctime_ns': value.st_ctime_ns})()
        return value

    monkeypatch.setattr(inspect_module, '_entry_stat', other_device)
    _, report = run(stores, tmp_path, 'empty-folders')
    assert report['skipped_other_volume'] == 1
    assert 'mounted' not in folder_rows(report)
    assert 'mounted/inner' not in folder_rows(report)


def test_empty_root_is_reported_and_non_empty_root_is_not(stores, tmp_path):
    empty_root = tmp_path / 'empty-root'
    empty_root.mkdir()
    _, report = run(stores, empty_root, 'empty-folders')
    rows = folder_rows(report)
    assert rows == {'empty-root': {'id': rows['empty-root']['id'], 'name': 'empty-root', 'state': 'empty',
                                   'nested_empty_folders': 0, 'depth': 0}}
    (tmp_path / 'filled').mkdir()
    (tmp_path / 'filled' / 'file.txt').write_text('x')
    _, report = run(stores, tmp_path / 'filled', 'empty-folders')
    assert report['folders'] == []


def test_overlapping_roots_count_each_folder_once(stores, tmp_path):
    parent = tmp_path / 'parent'
    child = parent / 'child'
    child.mkdir(parents=True)
    _, report = run(stores, parent, 'empty-folders', roots=[str(parent), str(child)])
    assert sorted(folder_rows(report)) == ['1/child', '1/parent']
    assert len(report['folders']) == 2


def test_denied_child_makes_ancestors_non_empty_and_incomplete(stores, tmp_path):
    skip_if_root()
    holder = tmp_path / 'holder'
    locked = holder / 'locked'
    locked.mkdir(parents=True)
    locked.chmod(0)
    try:
        _, report = run(stores, tmp_path, 'empty-folders')
        assert 'holder' not in folder_rows(report)
        assert report['denied_folders'] == 1
        assert report['complete'] is False
    finally:
        locked.chmod(0o755)


def test_empty_folders_requires_a_folder_root(stores, tmp_path):
    single = tmp_path / 'single.txt'
    single.write_text('x')
    status, _ = run(stores, single, 'empty-folders')
    assert status['state'] == 'failed'
    assert status['error'] == 'Choose a folder to check for empty folders'


def test_protected_root_is_refused(stores, tmp_path):
    protected = tmp_path / '.ssh'
    protected.mkdir()
    status, _ = run(stores, protected, 'empty-folders')
    assert status['state'] == 'failed'
    assert status['error'] == 'Protected folders cannot be checked'


# --- shared guards: cancellation, scan limit, changed root, retention --------

def test_cancellation_stops_a_scan_mid_way(tmp_path):
    from officekit.engines.engine_file_inspect import empty_folders, file_info
    from officekit.engines.engine_file_jobs import Cancelled
    for index in range(5):
        (tmp_path / f'd{index}').mkdir()
        (tmp_path / f'f{index}.txt').write_text('x')
    calls = []

    def cancel_after_two():
        calls.append(1)
        if len(calls) > 2:
            raise Cancelled()

    selections = FileSelectionStore(native_token=TOKEN)
    ref = selections.register_native([str(tmp_path)], credential=TOKEN)['id']
    with pytest.raises(Cancelled):
        empty_folders(selections.get(ref).roots, selection_id=ref, check=cancel_after_two)
    calls.clear()
    with pytest.raises(Cancelled):
        file_info(selections.iter_files(ref), {}, check=cancel_after_two,
                  dates=lambda item: {'created_at': None, 'modified_at': None})


def test_scan_entry_limit_is_enforced_for_walks_and_folders(tmp_path, monkeypatch):
    for index in range(6):
        (tmp_path / f'f{index}.txt').write_text('x')
    monkeypatch.setattr('officekit.engines.engine_file_selections.MAX_ENTRIES', 3)
    monkeypatch.setattr(inspect_module, 'MAX_ENTRIES', 3)
    selections = FileSelectionStore(native_token=TOKEN)
    ref = selections.register_native([str(tmp_path)], credential=TOKEN)['id']
    with pytest.raises(ValueError, match='Selection exceeds scan entry limit'):
        list(selections.iter_files(ref))
    with pytest.raises(ValueError, match='Selection exceeds scan entry limit'):
        inspect_module.empty_folders(selections.get(ref).roots, selection_id=ref, check=lambda: None)


def test_changed_root_is_refused_for_folder_scans(stores, tmp_path):
    folder = tmp_path / 'root'
    folder.mkdir()
    selections, jobs = stores
    ref = selections.register_native([str(folder)], credential=TOKEN)['id']
    # Move the granted folder away and put a new one at the same path: a different inode.
    folder.rename(tmp_path / 'moved')
    folder.mkdir()
    key = jobs.submit({'kind': 'empty-folders', 'selectionIds': [ref]})['id']
    status = await_job(jobs, key)
    assert status['state'] == 'failed'
    assert status['error'] == 'Selected root changed'


def test_result_over_the_retention_limit_is_rejected(stores, tmp_path, monkeypatch):
    for index in range(20):
        (tmp_path / f'long-name-{index:03d}-{"x" * 80}.txt').write_text('x')
    monkeypatch.setattr('officekit.engines.engine_file_jobs.MAX_REPORT_BYTES', 512)
    monkeypatch.setattr('officekit.engines.engine_file_jobs.MAX_RETAINED_REPORT_BYTES', 512)
    status, _ = run(stores, tmp_path, 'file-info')
    assert status['state'] == 'failed'
    assert status['error'] == 'Result exceeds report retention limit'


def test_compare_requires_two_single_files(stores, tmp_path):
    folder = tmp_path / 'folder'
    folder.mkdir()
    (folder / 'inside.txt').write_text('x')
    single = tmp_path / 'single.txt'
    single.write_text('y')
    status, _ = run_pair(stores, folder, single)
    assert status['state'] == 'failed'
    assert status['error'] == 'Choose two single files to compare'
