"""Every OfficeKit move to Trash is recorded in the same critical section as the move.

Synthetic home folders only; the real ~/.Trash is never touched.
"""

import os

import pytest

from officekit.engines.engine_file_selections import identity
from officekit.engines.engine_storage_cleaner import StorageCleaner


@pytest.fixture
def home(tmp_path):
    root = tmp_path / 'home'
    (root / '.Trash').mkdir(parents=True)
    (root / 'Documents').mkdir(parents=True)
    return root


def test_a_cleaner_move_is_recorded_with_its_original_folder(home):
    source = home / 'Documents' / 'report.txt'
    source.write_bytes(b'data')
    service = StorageCleaner(home=str(home), platform='darwin')
    assert service._trash(str(source), identity(os.stat(source)), 4) is True
    assert not source.exists()
    page = service.ledger.page(0, 10)
    assert page['total'] == 1
    record = page['records'][0]
    assert record['original_name'] == 'report.txt' and record['size'] == 4
    assert record['original_parent_path'] == str(home / 'Documents')
    assert (home / '.Trash' / record['trash_name']).read_bytes() == b'data'
    assert service.ledger.path == str(home / 'Library' / 'Application Support' / 'OfficeKit' / 'trash-ledger.json')


def test_size_defaults_to_the_identity_size_when_none_is_given(home):
    source = home / 'Documents' / 'sized.txt'
    source.write_bytes(b'12345678')
    service = StorageCleaner(home=str(home), platform='darwin')
    assert service._trash(str(source), identity(os.stat(source))) is True
    assert service.ledger.page(0, 10)['records'][0]['size'] == 8


def test_a_ledger_failure_keeps_the_file_in_trash_and_reports_not_restorable(home, monkeypatch):
    source = home / 'Documents' / 'keep.txt'
    source.write_bytes(b'keep')
    service = StorageCleaner(home=str(home), platform='darwin')

    def unavailable(**fields):
        raise OSError('ledger unavailable')

    monkeypatch.setattr(service.ledger, 'add', unavailable)
    assert service._trash(str(source), identity(os.stat(source)), 4) is False
    assert not source.exists()
    moved = [name for name in os.listdir(home / '.Trash') if name.endswith('-keep.txt')]
    assert len(moved) == 1
    assert (home / '.Trash' / moved[0]).read_bytes() == b'keep'
    assert not os.path.exists(service.ledger.path)


def test_a_failed_move_rolls_back_and_records_nothing(home, monkeypatch):
    source = home / 'Documents' / 'stays.txt'
    source.write_bytes(b'stays')
    service = StorageCleaner(home=str(home), platform='darwin')
    def busy(*args):
        raise OSError(16, 'busy')

    monkeypatch.setattr(service, '_trash_move', busy)
    with pytest.raises(OSError):
        service._trash(str(source), identity(os.stat(source)), 5)
    assert source.read_bytes() == b'stays'
    assert service.ledger.page(0, 10)['total'] == 0


def test_a_record_failure_after_the_move_is_not_rolled_back(home, monkeypatch):
    source = home / 'Documents' / 'gone-missing.txt'
    source.write_bytes(b'x')
    service = StorageCleaner(home=str(home), platform='darwin')
    monkeypatch.setattr(service, '_remember', lambda *args: False)
    assert service._trash(str(source), identity(os.stat(source)), 1) is False
    assert not source.exists()
