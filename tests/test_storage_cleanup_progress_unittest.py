import os
import time

import pytest

from officekit.engines.engine_file_selections import identity
from officekit.engines.engine_storage_cleaner import StorageCleaner

NATIVE = 'native-grant'


def _service(tmp_path, monkeypatch, count):
    home = tmp_path / 'home'
    (home / '.Trash').mkdir(parents=True)
    (home / 'Documents').mkdir()
    service = StorageCleaner(native_token=NATIVE, home=str(home), platform='darwin')
    selected = []
    for index in range(count):
        source = home / 'Documents' / f'file-{index}.txt'
        source.write_bytes(b'data')
        item = {'id': f'i{index}', 'method': 'trash', 'path': str(source), 'sizeBytes': 4}
        selected.append((item, identity(os.stat(source))))
    service.plans['plan-1'] = {'id': 'plan-1', 'expiresAt': time.time() + 600, 'selected': selected}
    return service


def test_progress_is_reported_and_finishes(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch, 3)
    monkeypatch.setattr(service, '_open_paths', lambda paths: set())
    monkeypatch.setattr(service, '_trash', lambda path, expected, size_bytes=None, open_paths=None: True)
    result = service.execute('plan-1', NATIVE)
    status = service.execution_status('plan-1')
    assert status == {'id': 'plan-1', 'state': 'finished', 'done': 3, 'total': 3, 'movedBytes': 12, 'stopRequested': False}
    assert [item['status'] for item in result['items']] == ['moved'] * 3


def test_stop_skips_remaining_items_and_keeps_the_result_shape(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch, 3)
    monkeypatch.setattr(service, '_open_paths', lambda paths: set())

    def trash(path, expected, size_bytes=None, open_paths=None):
        service.stop_execution('plan-1')
        return True

    monkeypatch.setattr(service, '_trash', trash)
    result = service.execute('plan-1', NATIVE)
    assert [item['status'] for item in result['items']] == ['moved', 'skipped', 'skipped']
    assert result['items'][1]['message'] == 'Stopped before this item.'
    assert result['movedBytes'] == 4
    status = service.execution_status('plan-1')
    assert status['stopRequested'] is True and status['done'] == 3


def test_unknown_execution_is_not_found_and_old_ones_are_trimmed(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch, 1)
    with pytest.raises(FileNotFoundError):
        service.execution_status('missing')
    with pytest.raises(FileNotFoundError):
        service.stop_execution('missing')
    for index in range(40):
        service.executions[f'old-{index}'] = {}
    monkeypatch.setattr(service, '_open_paths', lambda paths: set())
    monkeypatch.setattr(service, '_trash', lambda path, expected, size_bytes=None, open_paths=None: True)
    service.execute('plan-1', NATIVE)
    assert len(service.executions) <= 32 and 'plan-1' in service.executions


def test_batched_in_use_result_skips_an_open_file(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch, 1)
    path = service.plans['plan-1']['selected'][0][0]['path']
    monkeypatch.setattr(service, '_open_paths', lambda paths: {os.path.realpath(path)})
    result = service.execute('plan-1', NATIVE)
    assert result['items'][0]['status'] == 'skipped'
    assert os.path.exists(path)
