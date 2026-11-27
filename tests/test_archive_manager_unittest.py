import tempfile
import warnings
import zipfile
from pathlib import Path

import pytest

from officekit.engines import engine_archive_manager


def test_capability_registry_covers_requested_formats_and_states(monkeypatch):
    monkeypatch.setattr(engine_archive_manager, 'engine_path', lambda: '/bundled/7zz')

    formats = engine_archive_manager.capabilities()
    by_id = {item['id']: item for item in formats}

    assert len(formats) == 42
    assert by_id['zip']['extract'] == 'supported'
    assert by_id['tar-gz']['read'] == 'partial'
    assert by_id['tar-gz']['extract'] == 'partial'
    assert by_id['sitx']['read'] == 'unsupported'
    assert by_id['sitx']['extract'] == 'unsupported'
    assert by_id['zip']['create'] == 'supported'
    assert sum(item['read'] == 'supported' for item in formats) == 28
    assert sum(item['read'] == 'partial' for item in formats) == 7
    assert sum(item['read'] == 'unsupported' for item in formats) == 7


@pytest.mark.parametrize(('name', 'expected'), [
    ('backup.tar.gz', 'tar-gz'),
    ('disk.TAR.BZ2', 'tar-bz2'),
    ('package.zipx', 'zipx'),
    ('unknown.bin', 'unknown'),
])
def test_extension_hint_matches_longest_case_insensitive_extension(name, expected):
    assert engine_archive_manager.extension_hint(name) == expected


def test_bundled_engine_lists_and_extracts_zip_entries_without_changing_source():
    engine = engine_archive_manager.engine_path()
    if not engine:
        pytest.skip('The pinned archive engine has not been installed for this platform.')

    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        archive = root / 'fixture.zip'
        output = root / 'output'
        output.mkdir()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as handle:
            handle.writestr('folder/readme.txt', 'archive manager smoke fixture')

        entries = engine_archive_manager.list_archive(str(archive))
        engine_archive_manager.extract_archive(str(archive), str(output), lambda: None)

        assert [(entry['name'], entry['kind']) for entry in entries] == [('folder/readme.txt', 'file')]
        assert (output / 'folder' / 'readme.txt').read_text() == 'archive manager smoke fixture'
        assert zipfile.is_zipfile(archive)


def test_listing_rejects_unsafe_archive_paths():
    engine = engine_archive_manager.engine_path()
    if not engine:
        pytest.skip('The pinned archive engine has not been installed for this platform.')

    with tempfile.TemporaryDirectory() as temporary_directory:
        archive = Path(temporary_directory) / 'unsafe.zip'
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.writestr('../outside.txt', 'must not escape')

        with pytest.raises(ValueError, match='unsafe entry path'):
            engine_archive_manager.list_archive(str(archive))


def test_listing_reports_nested_member_paths_in_full(tmp_path):
    # PM-3 (F12 "nested paths"): nested folders list with their full member paths.
    if not engine_archive_manager.engine_path():
        pytest.skip('The pinned archive engine has not been installed for this platform.')
    archive = tmp_path / 'nested.zip'
    with zipfile.ZipFile(archive, 'w') as handle:
        handle.writestr('docs/2026/notes.txt', 'deep')
        handle.writestr('docs/readme.txt', 'top')
    names = sorted(entry['name'] for entry in engine_archive_manager.list_archive(str(archive)))
    assert 'docs/2026/notes.txt' in names
    assert 'docs/readme.txt' in names


def test_listing_refuses_duplicate_member_paths_instead_of_hiding_one(tmp_path):
    # PM-3 (F12 "duplicate paths"): a repeated member name fails the listing with the unsafe-path
    # message, so the browser never shows one copy as if it were the only one.
    if not engine_archive_manager.engine_path():
        pytest.skip('The pinned archive engine has not been installed for this platform.')
    archive = tmp_path / 'duplicate.zip'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.writestr('docs/readme.txt', 'first')
            handle.writestr('docs/readme.txt', 'second')
    with pytest.raises(ValueError, match='unsafe entry path'):
        engine_archive_manager.list_archive(str(archive))


def fake_engine(tmp_path, monkeypatch, script):
    """A stand-in 7zz that runs the given shell body, so listing and extraction failures are deterministic."""
    engine = tmp_path / 'fake7zz'
    engine.write_text('#!/bin/sh\n' + script + '\n')
    engine.chmod(0o755)
    monkeypatch.setattr(engine_archive_manager, 'engine_path', lambda: str(engine))
    return engine


def test_encrypted_entries_are_listed_as_encrypted_not_extracted_silently(tmp_path, monkeypatch):
    # F12: an encrypted member is reported as encrypted in the listing with its own metadata.
    archive = tmp_path / 'secret.zip'
    archive.write_bytes(b'x')
    fake_engine(tmp_path, monkeypatch, "printf '%s\\n' '----------' 'Path = secret.txt' 'Size = 3' "
                "'Packed Size = 5' 'Encrypted = +' 'Modified = 2025-01-01 00:00:00' ''")
    entries = engine_archive_manager.list_archive(str(archive))
    assert entries == [{'name': 'secret.txt', 'size_bytes': 3, 'compressed_bytes': 5, 'kind': 'file',
                        'encrypted': True, 'modified_at': '2025-01-01 00:00:00'}]


def test_unsupported_or_encrypted_archive_fails_with_the_fixed_message(tmp_path, monkeypatch):
    # F12 / F07: an engine refusal (encrypted, unsupported or damaged) becomes one fixed message, never a path.
    archive = tmp_path / 'locked.7z'
    archive.write_bytes(b'x')
    destination = tmp_path / 'out'
    destination.mkdir()
    fake_engine(tmp_path, monkeypatch, 'exit 2')
    with pytest.raises(ValueError, match='damaged, encrypted or unsupported') as listed:
        engine_archive_manager.list_archive(str(archive))
    assert str(archive) not in str(listed.value)
    with pytest.raises(ValueError, match='damaged, encrypted or unsupported') as extracted:
        engine_archive_manager.extract_archive(str(archive), str(destination), lambda: None)
    assert str(destination) not in str(extracted.value)


def test_declared_expansion_over_the_limit_is_refused_before_extraction(tmp_path, monkeypatch):
    # F07 decompression bomb: the declared expanded size is checked at listing, before any extraction starts.
    archive = tmp_path / 'bomb.zip'
    archive.write_bytes(b'x')
    fake_engine(tmp_path, monkeypatch, "printf '%s\\n' '----------' 'Path = big.bin' 'Size = 200' 'Packed Size = 1' ''")
    monkeypatch.setattr(engine_archive_manager, 'MAX_UNPACKED_BYTES', 100)
    with pytest.raises(ValueError, match='expanded-size limit'):
        engine_archive_manager.list_archive(str(archive))


def test_disk_full_during_extraction_reports_a_fixed_failure(tmp_path, monkeypatch):
    # F07 disk full: the engine exits non-zero when a write fails; the caller gets the fixed message and no path.
    archive = tmp_path / 'full.zip'
    archive.write_bytes(b'x')
    destination = tmp_path / 'out'
    destination.mkdir()
    fake_engine(tmp_path, monkeypatch, "echo 'No space left on device' >&2; exit 2")
    with pytest.raises(ValueError, match='could not be extracted') as raised:
        engine_archive_manager.extract_archive(str(archive), str(destination), lambda: None)
    assert str(destination) not in str(raised.value)
    assert 'No space left' not in str(raised.value)
