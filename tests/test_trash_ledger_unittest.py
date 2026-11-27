"""Trash ledger: bounded, TTL-pruned, 0600, atomic and free of names in logs."""

import json
import os
import stat

import pytest

from officekit.engines import engine_trash_ledger as ledger_module
from officekit.engines.engine_trash_ledger import MAX_RECORDS, TTL_SECONDS, TrashLedger


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def add(ledger, name='a.txt', size=3):
    return ledger.add(trash_name=f'uuid-{name}', trash_identity=(1, 2), original_parent_path='/Users/x/Documents',
                      original_parent_identity=(1, 3), original_name=name, size=size)


def test_add_records_fields_and_page_is_newest_first(tmp_path):
    clock = Clock()
    ledger = TrashLedger(str(tmp_path / 'OfficeKit' / 'trash-ledger.json'), clock=clock)
    first = add(ledger, 'first.txt')
    clock.now += 1
    second = add(ledger, 'second.txt', size=10)
    page = ledger.page(0, 10)
    assert [record['record_id'] for record in page['records']] == [second['record_id'], first['record_id']]
    assert page['total'] == 2 and page['hasMore'] is False
    assert second == {'record_id': second['record_id'], 'trash_name': 'uuid-second.txt', 'trash_identity': [1, 2],
                      'original_parent_path': '/Users/x/Documents', 'original_parent_identity': [1, 3],
                      'original_name': 'second.txt', 'moved_at': clock.now, 'size': 10}


def test_page_pages_and_reports_more(tmp_path):
    ledger = TrashLedger(str(tmp_path / 'trash-ledger.json'), clock=Clock())
    for index in range(3):
        add(ledger, f'f{index}.txt')
    assert len(ledger.page(0, 2)['records']) == 2
    assert ledger.page(0, 2)['hasMore'] is True
    assert len(ledger.page(2, 2)['records']) == 1
    assert ledger.page(5, 2)['records'] == []


def test_file_is_owner_only_and_directory_is_private(tmp_path):
    path = tmp_path / 'OfficeKit' / 'trash-ledger.json'
    ledger = TrashLedger(str(path), clock=Clock())
    add(ledger)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert [name for name in os.listdir(path.parent) if name.endswith('.tmp')] == []


def test_ttl_prunes_entries_older_than_thirty_days(tmp_path):
    clock = Clock()
    ledger = TrashLedger(str(tmp_path / 'trash-ledger.json'), clock=clock)
    old = add(ledger, 'old.txt')
    clock.now += TTL_SECONDS
    fresh = add(ledger, 'fresh.txt')
    clock.now += 1
    page = ledger.page(0, 10)
    assert [record['record_id'] for record in page['records']] == [fresh['record_id']]
    assert ledger.get(old['record_id']) is None


def test_bounded_drops_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_module, 'MAX_RECORDS', 3)
    clock = Clock()
    ledger = TrashLedger(str(tmp_path / 'trash-ledger.json'), clock=clock)
    ids = []
    for index in range(4):
        clock.now += 1
        ids.append(add(ledger, f'f{index}.txt')['record_id'])
    kept = {record['record_id'] for record in ledger.page(0, 10)['records']}
    assert kept == set(ids[1:])


def test_max_records_constant_is_ten_thousand():
    assert MAX_RECORDS == 10_000
    assert TTL_SECONDS == 30 * 24 * 60 * 60


def test_forget_and_remove_are_per_record(tmp_path):
    ledger = TrashLedger(str(tmp_path / 'trash-ledger.json'), clock=Clock())
    keep = add(ledger, 'keep.txt')
    gone = add(ledger, 'gone.txt')
    assert ledger.remove(gone['record_id']) is True
    assert ledger.remove(gone['record_id']) is False
    assert ledger.remove(keep['record_id']) is True
    assert ledger.remove(keep['record_id']) is False
    assert ledger.page(0, 10)['total'] == 0


def test_get_returns_record_or_none(tmp_path):
    ledger = TrashLedger(str(tmp_path / 'trash-ledger.json'), clock=Clock())
    record = add(ledger)
    assert ledger.get(record['record_id'])['original_name'] == 'a.txt'
    assert ledger.get('missing') is None


def test_failed_replace_keeps_previous_ledger_intact(tmp_path, monkeypatch):
    path = tmp_path / 'trash-ledger.json'
    ledger = TrashLedger(str(path), clock=Clock())
    kept = add(ledger, 'kept.txt')
    before = path.read_bytes()

    def broken(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(ledger_module.os, 'replace', broken)
    with pytest.raises(OSError):
        add(ledger, 'new.txt')
    assert path.read_bytes() == before
    assert [name for name in os.listdir(tmp_path) if name.endswith('.tmp')] == []
    monkeypatch.undo()
    assert ledger.get(kept['record_id']) is not None


def test_corrupt_or_malformed_file_reads_as_empty_and_is_rewritten(tmp_path):
    path = tmp_path / 'trash-ledger.json'
    path.write_text('{not json')
    ledger = TrashLedger(str(path), clock=Clock())
    assert ledger.page(0, 10)['total'] == 0
    add(ledger)
    assert json.loads(path.read_text())['records'][0]['original_name'] == 'a.txt'


def test_a_ledger_whose_records_are_not_a_list_reads_as_empty(tmp_path):
    path = tmp_path / 'trash-ledger.json'
    path.write_text('{"records": 5}')
    assert TrashLedger(str(path), clock=Clock()).page(0, 10)['total'] == 0


def test_a_failed_write_that_cannot_clean_up_still_raises_the_write_error(tmp_path, monkeypatch):
    ledger = TrashLedger(str(tmp_path / 'trash-ledger.json'), clock=Clock())

    def broken(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(ledger_module.os, 'replace', broken)
    monkeypatch.setattr(ledger_module.os, 'unlink', broken)
    with pytest.raises(OSError, match='disk full'):
        add(ledger)


def test_malformed_records_are_dropped_on_load(tmp_path):
    path = tmp_path / 'trash-ledger.json'
    good = {'record_id': 'a', 'trash_name': 'n', 'trash_identity': [1, 2], 'original_parent_path': '/p',
            'original_parent_identity': [1, 3], 'original_name': 'x', 'moved_at': 1_000_000.0, 'size': 1}
    path.write_text(json.dumps({'version': 1, 'records': [good, {'record_id': 'bad'}, 'text']}))
    ledger = TrashLedger(str(path), clock=Clock())
    assert [record['record_id'] for record in ledger.page(0, 10)['records']] == ['a']


def test_nothing_is_logged_or_printed(tmp_path, capsys, caplog):
    ledger = TrashLedger(str(tmp_path / 'trash-ledger.json'), clock=Clock())
    add(ledger, 'secret-name.txt')
    ledger.remove(ledger.page(0, 1)['records'][0]['record_id'])
    captured = capsys.readouterr()
    assert 'secret-name' not in captured.out + captured.err
    assert 'secret-name' not in caplog.text
