"""Restore items OfficeKit moved to Trash.

Every step runs on descriptors held for the call: the Trash folder, the original
(or chosen) folder, and a no-replace rename between them. The ledger is advisory,
so each record is re-checked against the live filesystem before anything moves.
Nothing is replaced, a changed name is skipped, and a moved item is checked again.
"""

import ctypes
import dataclasses
import errno
import hmac
import os
import re
import sys
import threading
import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .engine_storage_cleaner import PROTECTED

RESTORE_GRANT_TTL_SECONDS = 600
MAX_RESTORE_IDS = 100
MAX_RESTORE_GRANTS = 32
APPROVAL_MESSAGE = 'Restore approval is missing, expired or does not match these items. Choose them again.'
NATIVE_MESSAGE = 'Native restore authorization required'
_RECORD_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_RENAME_NO_REPLACE = {'darwin': ('renameatx_np', 4), 'linux': ('renameat2', 1)}
_MOVE_REASON = {errno.EEXIST: 'name-taken', errno.ENOENT: 'missing'}
_LISTING_STATE = {None: 'restorable', 'name-taken': 'name-taken', 'missing': 'missing', 'changed': 'changed', 'protected': 'changed'}


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def _unique_record_ids(value):
    if any(not _RECORD_ID.fullmatch(item) for item in value):
        raise ValueError('Invalid record id')
    if len(set(value)) != len(value):
        raise ValueError('Choose each item once')
    return value


class TrashRestoreGrantRequest(_Strict):
    record_ids: list[str] = Field(alias='recordIds', min_length=1, max_length=MAX_RESTORE_IDS)
    destination_grant_id: Optional[str] = Field(default=None, alias='destinationGrantId', max_length=64)

    @field_validator('record_ids')
    @classmethod
    def check_ids(cls, value):
        return _unique_record_ids(value)


class TrashRestoreRequest(_Strict):
    record_ids: list[str] = Field(alias='recordIds', min_length=1, max_length=MAX_RESTORE_IDS)
    restore_grant_id: str = Field(alias='restoreGrantId', min_length=1, max_length=64)

    @field_validator('record_ids')
    @classmethod
    def check_ids(cls, value):
        return _unique_record_ids(value)


# Response bodies (API-CONTRACT.md, Restore from Trash). Field names are the wire names.
class TrashRecord(BaseModel):
    id: str
    name: str
    original_folder_display: str
    moved_at: float
    size_bytes: int
    state: Literal['restorable', 'name-taken', 'changed', 'missing']


class TrashRecordPage(BaseModel):
    records: list[TrashRecord]
    total: int
    hasMore: bool


class TrashRestoreGrant(BaseModel):
    id: str
    expiresIn: int


class TrashRestoredItem(BaseModel):
    id: str
    state: Literal['restored', 'skipped']
    reason: Optional[str] = None
    restored_to: Optional[str] = None


class TrashRestoration(BaseModel):
    items: list[TrashRestoredItem]
    restored_bytes: int


@dataclasses.dataclass(frozen=True)
class _Grant:
    ids: frozenset
    destination: Optional['_Destination']
    expires: float


@dataclasses.dataclass(frozen=True)
class _Destination:
    path: str
    parent_identity: tuple


class _Hold:
    """Descriptors and the classification for one record. The caller closes them."""

    def __init__(self):
        self.trash_fd = None
        self.parent_fd = None
        self.parent_path = None
        self.target = None
        self.reason = None

    def close(self):
        for descriptor in (self.trash_fd, self.parent_fd):
            if descriptor is not None:
                os.close(descriptor)


def _single_component(name):
    return bool(name) and name not in ('.', '..') and os.sep not in name and '\x00' not in name


def _open_directory(path):
    """Descriptor for an existing absolute directory, every component opened without following links."""
    descriptor = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.split(os.sep):
            if component:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _protected(path):
    return any(part in PROTECTED for part in path.split(os.sep))


def _same_volume(trash_value, folder_value):
    return trash_value.st_dev == folder_value.st_dev


def _trash_item_matches(trash_fd, record):
    name = record['trash_name']
    if not _single_component(name):
        return False
    try:
        value = os.stat(name, dir_fd=trash_fd, follow_symlinks=False)
    except OSError:
        return False
    return (value.st_dev, value.st_ino) == tuple(record['trash_identity'])


def _name_exists(name, parent_fd):
    try:
        os.lstat(name, dir_fd=parent_fd)
    except FileNotFoundError:
        return False
    return True


def _exclusive_move(source, source_fd, destination, destination_fd):
    """Rename between two held folders without ever replacing the destination."""
    symbol, flag = _RENAME_NO_REPLACE.get(sys.platform, (None, 0))
    function = getattr(ctypes.CDLL(None, use_errno=True), symbol, None) if symbol else None
    if function is None:
        raise OSError(errno.ENOTSUP, 'Exclusive filesystem publication is unavailable')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(source_fd, os.fsencode(source), destination_fd, os.fsencode(destination), flag) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _skipped(record_id, reason):
    return {'id': record_id, 'state': 'skipped', 'reason': reason}


class TrashRestorer:
    def __init__(self, ledger, trash_dir, selections, *, native_token, clock=time.monotonic):
        self.ledger = ledger
        self.trash_dir = trash_dir
        self.selections = selections
        self.native_token = native_token
        self.clock = clock
        self.grants = {}
        self.lock = threading.RLock()

    def authorize(self, credential):
        if not self.native_token or not isinstance(credential, str) or not hmac.compare_digest(self.native_token, credential):
            raise PermissionError(NATIVE_MESSAGE)

    def page(self, offset, limit):
        listing = self.ledger.page(offset, limit)
        records = []
        for record in listing['records']:
            hold = self._hold(record, None)
            try:
                state = _LISTING_STATE[hold.reason]
            finally:
                hold.close()
            records.append({'id': record['record_id'], 'name': record['original_name'],
                            'original_folder_display': record['original_parent_path'], 'moved_at': record['moved_at'],
                            'size_bytes': record['size'], 'state': state})
        return {'records': records, 'total': listing['total'], 'hasMore': listing['hasMore']}

    def mint(self, request, credential):
        self.authorize(credential)
        for record_id in request.record_ids:
            if self.ledger.get(record_id) is None:
                raise FileNotFoundError('Item is no longer in the list')
        if request.destination_grant_id is not None and len(request.record_ids) != 1:
            raise ValueError('Restore to a folder works for one item at a time')
        with self.lock:
            self._prune()
            # Capacity is checked before the destination grant is spent, so a refused approval leaves it usable.
            if len(self.grants) >= MAX_RESTORE_GRANTS:
                raise RuntimeError('Too many restore approvals are waiting')
            destination = None
            if request.destination_grant_id is not None:
                output = self.selections.consume_output(request.destination_grant_id, 'trash-restore')
                destination = _Destination(output.path, output.parent_identity)
            key = str(uuid.uuid4())
            self.grants[key] = _Grant(frozenset(request.record_ids), destination, self.clock() + RESTORE_GRANT_TTL_SECONDS)
        return {'id': key, 'expiresIn': RESTORE_GRANT_TTL_SECONDS}

    def restore(self, request, credential):
        self.authorize(credential)
        with self.lock:
            grant = self._take_grant(request)
        items = []
        restored_bytes = 0
        for record_id in request.record_ids:
            record = self.ledger.get(record_id)
            if record is None:
                items.append(_skipped(record_id, 'missing'))
                continue
            item = self._restore_one(record, grant.destination)
            items.append(item)
            if item['state'] == 'restored':
                restored_bytes += record['size']
        return {'items': items, 'restored_bytes': restored_bytes}

    def forget(self, record_id, credential):
        self.authorize(credential)
        if not self.ledger.remove(record_id):
            raise FileNotFoundError('Item is no longer in the list')

    def _prune(self):
        now = self.clock()
        self.grants = {key: grant for key, grant in self.grants.items() if grant.expires > now}

    def _take_grant(self, request):
        """A grant is single use and bound to its exact item IDs. A mismatch leaves it unspent."""
        self._prune()
        grant = self.grants.get(request.restore_grant_id)
        if grant is None or grant.ids != frozenset(request.record_ids):
            raise PermissionError(APPROVAL_MESSAGE)
        del self.grants[request.restore_grant_id]
        return grant

    def _hold(self, record, destination):
        hold = _Hold()
        try:
            try:
                hold.trash_fd = _open_directory(self.trash_dir)
            except OSError:
                hold.reason = 'missing'
                return hold
            if not _trash_item_matches(hold.trash_fd, record):
                hold.reason = 'missing'
                return hold
            if destination is None:
                parent_path = record['original_parent_path']
                target = record['original_name']
                expected = tuple(record['original_parent_identity'])
            else:
                parent_path = os.path.dirname(destination.path)
                target = os.path.basename(destination.path)
                expected = destination.parent_identity
            if not os.path.isabs(parent_path) or not _single_component(target):
                hold.reason = 'changed'
                return hold
            if _protected(parent_path):
                hold.reason = 'protected'
                return hold
            hold.parent_path = parent_path
            try:
                hold.parent_fd = _open_directory(parent_path)
            except OSError:
                hold.reason = 'changed'
                return hold
            parent_value = os.fstat(hold.parent_fd)
            if ((parent_value.st_dev, parent_value.st_ino) != expected
                    or not _same_volume(os.fstat(hold.trash_fd), parent_value)
                    or parent_value.st_uid != os.getuid()):
                hold.reason = 'changed'
                return hold
            hold.target = target
            if _name_exists(target, hold.parent_fd):
                hold.reason = 'name-taken'
            return hold
        except BaseException:
            hold.close()
            raise

    def _restore_one(self, record, destination):
        record_id = record['record_id']
        hold = self._hold(record, destination)
        try:
            if hold.reason:
                return _skipped(record_id, hold.reason)
            try:
                _exclusive_move(record['trash_name'], hold.trash_fd, hold.target, hold.parent_fd)
            except OSError as error:
                return _skipped(record_id, _MOVE_REASON.get(error.errno, 'changed'))
            if not self._moved_item_matches(hold, record):
                # The name now holds something else. OfficeKit does not touch it.
                return _skipped(record_id, 'changed')
            try:
                self.ledger.remove(record_id)
            except OSError:
                pass
            return {'id': record_id, 'state': 'restored', 'reason': None,
                    'restored_to': os.path.join(hold.parent_path, hold.target)}
        finally:
            hold.close()

    @staticmethod
    def _moved_item_matches(hold, record):
        try:
            value = os.stat(hold.target, dir_fd=hold.parent_fd, follow_symlinks=False)
        except OSError:
            return False
        return (value.st_dev, value.st_ino) == tuple(record['trash_identity'])
