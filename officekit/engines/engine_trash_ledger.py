"""Private, bounded record of what OfficeKit moved to Trash, so it can be put back.

The ledger is advisory: restore re-checks every item against the live filesystem
before it moves anything. Names and paths are stored only in this file (0600,
in the user's Application Support folder), are never logged and never exported.
"""

import json
import os
import threading
import time
import uuid

MAX_RECORDS = 10_000
TTL_SECONDS = 30 * 24 * 60 * 60
LEDGER_VERSION = 1
_RECORD_KEYS = {'record_id', 'trash_name', 'trash_identity', 'original_parent_path',
                'original_parent_identity', 'original_name', 'moved_at', 'size'}


def _valid_record(value):
    if not isinstance(value, dict) or set(value) != _RECORD_KEYS:
        return False
    identities = (value['trash_identity'], value['original_parent_identity'])
    return (all(isinstance(text, str) and text for text in (value['record_id'], value['trash_name'], value['original_parent_path'], value['original_name']))
            and all(isinstance(pair, list) and len(pair) == 2 and all(type(item) is int for item in pair) for pair in identities)
            and isinstance(value['moved_at'], (int, float)) and type(value['size']) is int and value['size'] >= 0)


class TrashLedger:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.RLock()

    def _load(self):
        try:
            with open(self.path, 'rb') as handle:
                document = json.loads(handle.read(64 * 1024 * 1024).decode('utf-8'))
        except (OSError, ValueError):
            return []
        records = document.get('records') if isinstance(document, dict) else None
        if not isinstance(records, list):
            return []
        return [record for record in records if _valid_record(record)]

    def _save(self, records):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.name == 'posix':
            # makedirs applies the mode only when it creates the folder; a folder another store made stays as it was.
            os.chmod(directory, 0o700)
        temporary = os.path.join(directory, f'.trash-ledger-{uuid.uuid4()}.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                json.dump({'version': LEDGER_VERSION, 'records': records}, handle, separators=(',', ':'))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _pruned(self, records):
        now = self.clock()
        live = [record for record in records if record['moved_at'] + TTL_SECONDS > now]
        live.sort(key=lambda record: record['moved_at'])
        return live[-MAX_RECORDS:]

    def _mutate(self, change):
        # Pruning happens only on writes, and after the change: the stored file never holds more than MAX_RECORDS.
        with self.lock:
            records = self._pruned(self._load())
            result = change(records)
            records = self._pruned(records)
            self._save(records)
            return result

    def add(self, *, trash_name, trash_identity, original_parent_path, original_parent_identity, original_name, size):
        record = {'record_id': str(uuid.uuid4()), 'trash_name': trash_name, 'trash_identity': list(trash_identity),
                  'original_parent_path': original_parent_path, 'original_parent_identity': list(original_parent_identity),
                  'original_name': original_name, 'moved_at': self.clock(), 'size': size}

        def change(records):
            records.append(record)
            return dict(record)

        return self._mutate(change)

    def page(self, offset, limit):
        # A read: expired and over-cap records are filtered in memory and the file is not rewritten.
        with self.lock:
            records = self._pruned(self._load())
        ordered = sorted(records, key=lambda record: record['moved_at'], reverse=True)
        window = ordered[offset:offset + limit]
        return {'records': [dict(record) for record in window], 'total': len(ordered),
                'hasMore': offset + limit < len(ordered)}

    def get(self, record_id):
        with self.lock:
            for record in self._pruned(self._load()):
                if record['record_id'] == record_id:
                    return dict(record)
        return None

    def remove(self, record_id):
        return self._mutate(lambda records: _drop(records, record_id))


def _drop(records, record_id):
    before = len(records)
    records[:] = [record for record in records if record['record_id'] != record_id]
    return len(records) != before
