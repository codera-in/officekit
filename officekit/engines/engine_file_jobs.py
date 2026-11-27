"""Bounded background operations over native-authorized original files."""

import hashlib
from datetime import datetime, timezone
import contextlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .engine_file_ops import FileOpsEngine
from .engine_file_selections import MAX_ENTRIES, SelectedFile, checked_path, exclusive_rename, identity, open_parent, remove_owned_file
from .engine_file_inspect import DEVELOPMENT_ONLY_KINDS, INSPECT_KINDS, FileAgeOptions, SubfolderOptions, compare_files, empty_files, empty_folders, file_age, file_info, symlink_links
from .engine_file_type import FileTypeDetector
from .engine_similar_images import SimilarImageEngine
from . import engine_archive_manager

CHUNK_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 ** 3
MAX_REPORT_BYTES = 32 * 1024 ** 2
MAX_RETAINED_REPORT_BYTES = 128 * 1024 ** 2
MAX_JOBS = 64
MAX_PENDING = 10
PREVIEW_TTL = 300
JOB_TTL = 1800


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, populate_by_name=True)


class SelectionRequest(StrictModel):
    paths: list[str] = Field(min_length=1, max_length=10_000)
    access: Literal['read', 'read-write'] = 'read'


class OutputGrantRequest(StrictModel):
    path: str
    kind: Literal['file', 'directory']
    job_kind: str = Field(alias='jobKind')
    overwrite: bool = False


class HashOptions(StrictModel):
    algorithm: Literal['sha256', 'sha512'] = 'sha256'


class EmptyOptions(StrictModel):
    pass


class DuplicateOptions(StrictModel):
    include_subfolders: bool = Field(default=True, alias='includeSubfolders')
    match_kind: Literal['files', 'folders'] = Field(default='files', alias='matchKind')


class StorageOptions(StrictModel):
    top_n: int = Field(default=10, ge=1, le=200, alias='topN')


class SimilarOptions(StrictModel):
    threshold: int = Field(default=8, ge=0, le=64)


class RenameOptions(StrictModel):
    pattern_type: Literal['sequence', 'affix', 'casing', 'replace'] = 'sequence'
    prefix: str = Field(default='', max_length=100)
    suffix: str = Field(default='', max_length=100)
    start_num: int = Field(default=1, ge=0, le=1_000_000)
    digits: int = Field(default=3, ge=1, le=12)
    casing: Literal['kebab', 'snake', 'camel', 'title'] = 'kebab'
    find_text: str = Field(default='', max_length=100)
    replace_text: str = Field(default='', max_length=100)


class ApplyOptions(StrictModel):
    preview_id: str = Field(alias='previewId', pattern=r'^[a-f0-9-]{36}$')


class DuplicateTrashOptions(StrictModel):
    source_job_id: str = Field(alias='sourceJobId', pattern=r'^[a-f0-9-]{36}$')
    file_ids: list[str] = Field(alias='fileIds', min_length=1, max_length=10_000)

    @model_validator(mode='after')
    def unique_files(self):
        if len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError('Choose each copy once')
        for key in [self.source_job_id, *self.file_ids]:
            if str(uuid.UUID(key)) != key:
                raise ValueError('Invalid identifier')
        return self


class SplitOptions(StrictModel):
    chunk_size: int = Field(default=52_428_800, ge=1024, le=1024 ** 3, alias='chunkSize')


class ArchiveCreateOptions(StrictModel):
    format: Literal['zip'] = 'zip'


class ArchiveExtractOptions(StrictModel):
    all: bool = True
    entry_ids: list[str] = Field(default_factory=list, alias='entryIds', max_length=500)

    @model_validator(mode='after')
    def validate_entries(self):
        if self.all == bool(self.entry_ids):
            raise ValueError('Choose all entries or up to 500 selected entries')
        if len(set(self.entry_ids)) != len(self.entry_ids):
            raise ValueError('Archive entries must be unique')
        for key in self.entry_ids:
            if str(uuid.UUID(key)) != key:
                raise ValueError('Invalid archive entry identifier')
        return self


OPTION_MODELS = {'hash': HashOptions, 'file-type': EmptyOptions, 'storage': StorageOptions, 'duplicates': EmptyOptions, 'compare-folders': EmptyOptions, 'similar-images': SimilarOptions, 'rename-preview': RenameOptions, 'rename-apply': ApplyOptions, 'split': SplitOptions, 'join': EmptyOptions, 'archive-create': ArchiveCreateOptions, 'archive-extract': ArchiveExtractOptions}
OPTION_MODELS['duplicate-trash'] = DuplicateTrashOptions
OPTION_MODELS['duplicates'] = DuplicateOptions
OPTION_MODELS.update({'file-info': SubfolderOptions, 'file-age': FileAgeOptions, 'empty-files': SubfolderOptions, 'compare-files': EmptyOptions, 'empty-folders': EmptyOptions, 'symlinks': SubfolderOptions})
MUTATING_KINDS = {'rename-apply', 'duplicate-trash'}
OUTPUT_KINDS = {'split', 'join', 'archive-create', 'archive-extract'}
OUTPUT_INSIDE_SELECTION = 'The output file is inside the selected folder. Choose another place to save it.'
TWO_SELECTION_KINDS = frozenset({'compare-folders', 'compare-files'})


def _is_within(path, root):
    """True when path is root or lies below it (both real, absolute paths; different drives are never within)."""
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


class ReleaseScopeError(PermissionError):
    """A development-only operation was requested under the private-beta profile."""


class FileJobRequest(StrictModel):
    kind: Literal['hash', 'file-type', 'storage', 'duplicates', 'duplicate-trash', 'compare-folders', 'similar-images', 'rename-preview', 'rename-apply', 'split', 'join', 'archive-create', 'archive-extract', 'file-info', 'compare-files', 'file-age', 'empty-files', 'empty-folders', 'symlinks']
    selection_ids: list[str] = Field(alias='selectionIds', min_length=1, max_length=2)
    options: dict = Field(default_factory=dict)
    output_grant_id: str | None = Field(default=None, alias='outputGrantId')

    @model_validator(mode='after')
    def validate_options(self):
        for key in self.selection_ids:
            if str(uuid.UUID(key)) != key:
                raise ValueError('Invalid selection identifier')
        if len(set(self.selection_ids)) != len(self.selection_ids):
            raise ValueError('Selections must be unique')
        if len(self.selection_ids) != (2 if self.kind in TWO_SELECTION_KINDS else 1):
            raise ValueError('Invalid number of selections for operation')
        self.options = OPTION_MODELS[self.kind].model_validate(self.options).model_dump()
        if (self.kind in OUTPUT_KINDS) != (self.output_grant_id is not None):
            raise ValueError('This operation requires its own output grant')
        return self


class Cancelled(Exception):
    pass


@dataclass
class Job:
    request: FileJobRequest
    state: str = 'queued'
    progress: int = 0
    total: int | None = None
    phase: str = 'Queued'
    insights: dict = field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    expires: float = 0
    mutation: bool = False
    result_bytes: int = 0
    duplicate_groups: list = field(default_factory=list)
    reveal_items: dict = field(default_factory=dict)


class FileJobStore:
    def __init__(self, selections, clock=time.monotonic, trash=None, *, release_profile):
        # Required: the private-beta exclusion must not depend on a caller remembering an argument (ARCH-3).
        self.selections = selections
        self.clock = clock
        self.trash = trash
        self.release_profile = release_profile
        self.jobs = {}
        self.previews = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='officekit-files')

    def submit(self, request):
        if not isinstance(request, FileJobRequest):
            request = FileJobRequest.model_validate(request)
        if request.kind in DEVELOPMENT_ONLY_KINDS and self.release_profile == 'private-beta':
            raise ReleaseScopeError('This operation is not available in the OfficeKit private beta.')
        with self.lock:
            self.jobs = {key: job for key, job in self.jobs.items() if job.state in {'queued', 'running'} or job.expires > self.clock()}
            self.previews = {key: preview for key, preview in self.previews.items() if preview['expires'] > self.clock()}
            if len(self.jobs) >= MAX_JOBS or sum(job.state in {'queued', 'running'} for job in self.jobs.values()) >= MAX_PENDING:
                raise RuntimeError('File job queue is full')
            for existing in self.jobs.values():
                if existing.state in {'queued', 'running'} and MUTATING_KINDS.intersection({existing.request.kind, request.kind}):
                    old_roots = [root[0] for key in existing.request.selection_ids for root in self.selections.get(key).roots]
                    new_roots = [root[0] for key in request.selection_ids for root in self.selections.get(key).roots]
                    if any(first == second or first.startswith(second + os.sep) or second.startswith(first + os.sep) for first in old_roots for second in new_roots):
                        raise FileExistsError('Selection is busy; wait for its current operation')
            for key in request.selection_ids:
                self.selections.get(key, write=request.kind in MUTATING_KINDS)
            if request.kind == 'duplicate-trash':
                source = self._get(request.options['source_job_id'])
                if source.state != 'ready' or source.request.kind != 'duplicates' or source.request.selection_ids != request.selection_ids or not source.duplicate_groups:
                    raise FileExistsError('Run duplicate search again before moving copies')
                selected = set(request.options['file_ids'])
                known = {item.id for group in source.duplicate_groups for item in group}
                if not selected <= known or any(all(item.id in selected for item in group) for group in source.duplicate_groups):
                    raise ValueError('Keep at least one file in every duplicate group')
            if request.kind == 'rename-apply':
                preview = self.previews.get(request.options['preview_id'])
                if not preview or preview['selection'] != request.selection_ids[0]:
                    raise FileExistsError('Rename preview is stale')
            grant = self.selections.consume_output(request.output_grant_id, request.kind) if request.output_grant_id else None
            for key in request.selection_ids:
                self.selections.pin(key)
            key = str(uuid.uuid4())
            job = Job(request)
            if request.kind == 'duplicate-trash':
                job.duplicate_groups = source.duplicate_groups
            self.jobs[key] = job
            self.executor.submit(self._run, job, grant)
            return {'id': key, 'state': 'queued'}

    def status(self, key):
        with self.lock:
            job = self._get(key)
            return {'id': key, 'state': job.state, 'kind': job.request.kind, 'progress': job.progress,
                    'total': job.total, 'phase': job.phase, 'insights': dict(job.insights),
                    'error': job.error, 'resultRef': key if job.result is not None else None}

    def _get(self, key):
        job = self.jobs.get(key)
        if not job or (job.state not in {'queued', 'running'} and job.expires <= self.clock()):
            raise FileNotFoundError('File job is unavailable')
        return job

    def cancel(self, key):
        with self.lock:
            job = self._get(key)
            if job.state not in {'queued', 'running'} or job.mutation:
                raise FileExistsError('Job cannot be cancelled at this stage')
            job.cancel.set()
            return {'id': key, 'state': job.state, 'cancellationRequested': True}

    @staticmethod
    def _duplicate_insights(groups):
        return {'duplicateGroups': len(groups),
                'extraCopies': sum(len(group) - 1 for group in groups),
                'potentialRecoveryBytes': sum((len(group) - 1) * group[0].signature[2] for group in groups),
                'inspectionOnly': False}

    def revoke_selection(self, key):
        with self.lock:
            related = [job for job in self.jobs.values() if key in job.request.selection_ids and job.state in {'queued', 'running'}]
            if any(job.mutation for job in related):
                raise FileExistsError('Selection has an active mutation; wait for completion')
            self.selections.revoke(key)
            for job in related:
                job.cancel.set()

    def result(self, key, offset=0, limit=200):
        with self.lock:
            job = self._get(key)
            if job.state != 'ready' and not (job.state == 'failed' and job.result is not None):
                raise FileExistsError('Result is not ready')
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
                raise ValueError('Invalid result pagination')
            result = dict(job.result)
            for field_name, values in result.items():
                if isinstance(values, list):
                    result[field_name] = values[offset:offset + limit]
            return {**result, 'offset': offset, 'hasMore': any(isinstance(value, list) and len(value) > offset + limit for value in job.result.values())}

    def export(self, key):
        with self.lock:
            job = self._get(key)
            if job.state != 'ready' and not (job.state == 'failed' and job.result is not None):
                raise FileExistsError('Result is not ready')
            return json.dumps(job.result, ensure_ascii=False).encode('utf-8')

    def _check(self, job):
        if job.cancel.is_set():
            raise Cancelled()
        for key in job.request.selection_ids:
            self.selections.get(key)

    def _begin_mutation(self, job):
        with self.lock:
            self._check(job)
            job.mutation = True

    def _retain_result(self, job, result):
        encoded_size = len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        if encoded_size > min(MAX_REPORT_BYTES, MAX_RETAINED_REPORT_BYTES):
            raise ValueError('Result exceeds report retention limit')
        with self.lock:
            self.jobs = {key: value for key, value in self.jobs.items() if value is job or value.state in {'queued', 'running'} or value.expires > self.clock()}
            retained = sum(value.result_bytes for value in self.jobs.values() if value is not job)
            for key, previous in sorted(self.jobs.items(), key=lambda pair: pair[1].expires):
                if retained + encoded_size <= MAX_RETAINED_REPORT_BYTES:
                    break
                if previous is not job and previous.state not in {'queued', 'running'}:
                    retained -= previous.result_bytes
                    del self.jobs[key]
            job.result = result
            job.result_bytes = encoded_size

    def _run(self, job, grant):
        try:
            job.state = 'running'
            job.phase = 'Preparing operation'
            self._check(job)
            result = self._compute(job, grant)
            self._retain_result(job, result)
            job.state = 'ready'
            job.phase = 'Complete'
            if job.request.kind == 'duplicates' and job.request.options.get('match_kind') != 'folders':
                job.insights = self._duplicate_insights(job.duplicate_groups)
            elif job.request.kind == 'duplicate-trash':
                moved = [item for item in result.get('items', []) if item.get('state') == 'trashed']
                selected = {item.id: item for group in job.duplicate_groups for item in group}
                moved_bytes = sum(selected[item['id']].signature[2] for item in moved if item['id'] in selected)
                job.insights = {'copiesMovedToTrash': len(moved), 'movedBytes': moved_bytes}
                job.phase = 'Moved to Trash'
        except Cancelled:
            job.state = 'cancelled'
            job.phase = 'Cancelled'
        except PermissionError:
            job.duplicate_groups = []
            job.error = 'Permission denied. OfficeKit needs access to this folder. Grant access in macOS System Settings.'
            job.state = 'failed'
            job.phase = 'Permission required'
        except ValueError as exc:
            job.duplicate_groups = []
            job.error = str(exc)
            job.state = 'failed'
            job.phase = 'Could not complete'
        except FileExistsError as exc:
            job.duplicate_groups = []
            job.error = str(exc) or 'A file or folder already exists with that name.'
            job.state = 'failed'
            job.phase = 'Could not complete'
        except FileNotFoundError as exc:
            job.duplicate_groups = []
            job.error = str(exc) or 'Selected file or folder was moved or is no longer available.'
            job.state = 'failed'
            job.phase = 'Could not complete'
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            job.duplicate_groups = []
            job.error = f'Archive error: {exc}'
            job.state = 'failed'
            job.phase = 'Could not complete'
        except OSError as exc:
            job.duplicate_groups = []
            if 'permission' in str(exc).lower() or getattr(exc, 'errno', None) in (1, 13):
                job.error = 'Permission denied. OfficeKit needs access to this folder. Grant access in macOS System Settings.'
                job.phase = 'Permission required'
            else:
                job.error = f'Filesystem error: {exc.strerror or exc}'
                job.phase = 'Could not complete'
            job.state = 'failed'
        except Exception as exc:
            job.duplicate_groups = []
            job.error = str(exc) if str(exc) else 'Operation failed. Check permissions, unchanged inputs, selection limits and destination availability.'
            job.state = 'failed'
            job.phase = 'Could not complete'
        finally:
            if job.request.kind == 'duplicate-trash':
                job.duplicate_groups = []
            job.expires = self.clock() + JOB_TTL
            for key in job.request.selection_ids:
                self.selections.unpin(key)

    def _files(self, job, key=None):
        for item in self.selections.iter_files(key or job.request.selection_ids[0],
                                               include_subfolders=job.request.options.get('include_subfolders', True)):
            self._check(job)
            if job.request.kind == 'duplicates' and job.phase == 'Counting selected files':
                job.progress += 1
            yield item

    def _inspect_files(self, job, key, stats, include_subfolders):
        for item in self.selections.iter_files(key, include_subfolders=include_subfolders, stats=stats):
            self._check(job)
            job.progress += 1
            job.reveal_items[item.id] = item
            yield item

    def _single_file(self, key):
        selection = self.selections.get(key)
        if len(selection.roots) != 1 or selection.roots[0][2]:
            raise ValueError('Choose two single files to compare')
        items = list(self.selections.iter_files(key))
        if len(items) != 1:
            raise ValueError('Choose two single files to compare')
        return items[0]

    def _inspect(self, job):
        kind, options = job.request.kind, job.request.options

        def check():
            self._check(job)

        if kind == 'compare-files':
            first = self._single_file(job.request.selection_ids[0])
            second = self._single_file(job.request.selection_ids[1])
            return compare_files(first, second, check=check, open_file=self.selections.open_file)
        if kind == 'empty-folders':
            key = job.request.selection_ids[0]
            result, items = empty_folders(self.selections.get(key).roots, selection_id=key, check=check)
            job.reveal_items = {item.id: item for item in items}
            return result
        if kind == 'symlinks':
            roots = self.selections.get(job.request.selection_ids[0]).roots
            return symlink_links(roots, check=check, include_subfolders=options['include_subfolders'])
        stats = {}
        items = self._inspect_files(job, job.request.selection_ids[0], stats, options['include_subfolders'])
        if kind == 'file-info':
            return file_info(items, stats, check=check, dates=self._file_dates)
        if kind == 'file-age':
            return file_age(items, stats, options=options, check=check, dates=self._file_dates)
        return empty_files(items, stats, check=check, dates=self._file_dates)

    def reveal_path(self, key, item_id):
        with self.lock:
            job = self._get(key)
            self._check(job)
            if job.state != 'ready' or item_id not in job.reveal_items:
                raise FileNotFoundError('Scanned item is unavailable')
            item = job.reveal_items[item_id]
            selection = self.selections.get(item.selection_id)
            for root, root_id, _ in selection.roots:
                if identity(os.lstat(checked_path(root)))[:2] != root_id:
                    raise FileExistsError('Selected root changed')
            checked_path(item.path)
            if identity(os.lstat(item.path)) != item.signature:
                raise FileExistsError('Scanned item changed')
            return item.path

    def _duplicate_folders(self, job):
        job.phase = 'Scanning folder contents'
        selection_id = job.request.selection_ids[0]
        selection = self.selections.get(selection_id)
        trees, order, pending = {}, [], []
        for index, (root, root_identity, directory) in enumerate(selection.roots):
            if not directory or identity(os.lstat(checked_path(root)))[:2] != root_identity:
                raise ValueError('Choose unchanged folders for folder matching')
            pending.append((root, root, index))
        count = files_scanned = skipped = links = 0
        scanned_files = []
        while pending:
            self._check(job)
            path, root, index = pending.pop()
            if path in trees:
                continue
            signature = identity(os.lstat(checked_path(path)))
            relative = os.path.relpath(path, root).replace(os.sep, '/')
            name = f'{index + 1}/{relative}' if len(selection.roots) > 1 else relative
            item = SelectedFile(selection_id, root, path, name, signature)
            node = {'item': item, 'parts': [], 'children': [], 'size': 0, 'files': 0, 'valid': True}
            trees[path] = node
            order.append(path)
            try:
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        self._check(job)
                        count += 1
                        if count > MAX_ENTRIES:
                            raise ValueError('Selection exceeds scan entry limit')
                        value = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(value.st_mode):
                            node['children'].append((entry.name, entry.path))
                            pending.append((entry.path, root, index))
                        elif stat.S_ISREG(value.st_mode):
                            file = SelectedFile(selection_id, root, entry.path, name + '/' + entry.name, identity(value))
                            node['parts'].append(('file', entry.name, self._digest(file, job)))
                            scanned_files.append(file)
                            node['size'] += value.st_size
                            node['files'] += 1
                            files_scanned += 1
                            job.progress += 1
                        else:
                            # A skipped link/special entry prevents an exact-folder claim
                            # for this folder and its ancestors, rather than being ignored.
                            node['valid'] = False
                            skipped += 1
                            links += int(stat.S_ISLNK(value.st_mode))
            except PermissionError:
                if path == root:
                    raise
                node['valid'] = False
                skipped += 1
        for file in scanned_files:
            self._check(job)
            with self.selections.open_file(file):
                pass
        matches = {}
        for path in sorted(order, key=lambda value: value.count(os.sep), reverse=True):
            self._check(job)
            node = trees[path]
            if identity(os.lstat(checked_path(path))) != node['item'].signature:
                raise FileExistsError('Folder changed during scan')
            for name, child_path in node['children']:
                child = trees[child_path]
                node['valid'] = node['valid'] and child['valid']
                node['parts'].append(('directory', name, child['digest']))
                node['size'] += child['size']
                node['files'] += child['files']
            node['digest'] = hashlib.sha256(json.dumps(sorted(node['parts']), ensure_ascii=True).encode()).hexdigest()
            if node['valid']:
                matches.setdefault(node['digest'], []).append(node)
        groups = []
        for digest, nodes in matches.items():
            if len(nodes) < 2:
                continue
            entries = []
            for node in sorted(nodes, key=lambda value: value['item'].name):
                item = node['item']
                job.reveal_items[item.id] = item
                entries.append({'id': item.id, 'name': item.name, 'display_name': os.path.basename(item.path),
                                'full_path': item.path, 'file_count': node['files'], **self._file_dates(item)})
            groups.append({'hash': digest, 'size_bytes': nodes[0]['size'], 'files': [entry['name'] for entry in entries], 'entries': entries})
        job.insights = {'duplicateGroups': len(groups),
                        'extraCopies': sum(max(0, len(group['entries']) - 1) for group in groups),
                        'potentialRecoveryBytes': 0,
                        'matchedFolderBytes': sum((len(nodes) - 1) * nodes[0]['size'] for nodes in matches.values() if len(nodes) > 1),
                        'inspectionOnly': True}
        job.total = files_scanned
        return {'groups': groups, 'match_kind': 'folders', 'include_subfolders': True,
                'files_scanned': files_scanned, 'folders_scanned': len(trees), 'skipped_links': links, 'skipped_entries': skipped,
                'complete': skipped == 0, 'trash_supported': False}

    @staticmethod
    def _file_dates(item):
        def iso(nanoseconds):
            if nanoseconds is None:
                return None
            try:
                return datetime.fromtimestamp(nanoseconds / 1_000_000_000, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            except (OverflowError, OSError, ValueError):
                return None

        return {'created_at': iso(item.signature[5] if len(item.signature) > 5 else None),
                'modified_at': iso(item.signature[3])}

    def _digest(self, item, job, algorithm='sha256'):
        digest = hashlib.new(algorithm)
        with self.selections.open_file(item) as source:
            while chunk := source.read(CHUNK_BYTES):
                self._check(job)
                digest.update(chunk)
        return digest.hexdigest()

    def _compute(self, job, grant):
        kind, options = job.request.kind, job.request.options
        if kind == 'hash':
            rows = []
            total = 0
            for item in self._files(job):
                rows.append({'id': item.id, 'name': item.name, 'size_bytes': item.signature[2], 'digest': self._digest(item, job, options['algorithm'])})
                total += item.signature[2]
                job.progress += 1
            return {'algorithm': options['algorithm'], 'files': rows, 'total_files': len(rows), 'total_bytes': total, 'complete': True}
        if kind == 'file-type':
            rows = []
            for item in self._files(job):
                with self.selections.open_file(item) as source:
                    rows.append(FileTypeDetector.detect(item.name, source.read(FileTypeDetector.MAX_HEADER_BYTES), item.signature[2]))
            return {'files': rows, 'total_files': len(rows), 'complete': True}
        if kind == 'storage':
            largest = []
            total = count = 0
            for item in self._files(job):
                total += item.signature[2]
                count += 1
                largest.append({'name': item.name, 'size_bytes': item.signature[2], **self._file_dates(item)})
                largest.sort(key=lambda row: (-row['size_bytes'], row['name']))
                del largest[options['top_n']:]
            return {'total_files': count, 'total_size_bytes': total, 'largest_files': largest, 'complete': True}
        if kind == 'duplicates':
            if options['match_kind'] == 'folders':
                return self._duplicate_folders(job)
            job.phase = 'Counting selected files'
            items = list(self._files(job))
            job.total = len(items)
            job.progress = 0
            job.phase = 'Comparing file contents'
            sizes = {}
            for item in items:
                sizes.setdefault(item.signature[2], []).append(item)
            candidate_items = [item for same_size in sizes.values() if len(same_size) > 1 for item in same_size]
            job.progress = len(items) - len(candidate_items)
            digests = {}
            for size, items in sizes.items():
                if len(items) > 1:
                    for item in items:
                        digest = self._digest(item, job)
                        matches = digests.setdefault((size, digest), [])
                        matches.append(item)
                        job.progress += 1
                        groups_so_far = [group for group in digests.values() if len(group) > 1]
                        job.insights = {'duplicateGroups': len(groups_so_far),
                                        'extraCopies': sum(len(group) - 1 for group in groups_so_far),
                                        'potentialRecoveryBytes': sum((len(group) - 1) * group[0].signature[2] for group in groups_so_far)}
            keeper_order = lambda item: (len(os.path.basename(item.path)), item.name.casefold(), item.name)
            job.duplicate_groups = [tuple(sorted(items, key=keeper_order)) for items in digests.values() if len(items) > 1]
            job.reveal_items = {item.id: item for group in job.duplicate_groups for item in group}
            groups = [{'hash': digest, 'size_bytes': size, 'files': sorted(item.name for item in items),
                       'entries': [{'id': item.id, 'name': item.name, 'full_path': item.path, **self._file_dates(item)} for item in sorted(items, key=keeper_order)]}
                      for (size, digest), items in digests.items() if len(items) > 1]
            return {'groups': groups, 'files_scanned': sum(len(items) for items in sizes.values()), 'complete': True,
                    'include_subfolders': options['include_subfolders'], 'match_kind': 'files',
                    'trash_supported': sys.platform == 'darwin' or self.trash is not None}
        if kind == 'duplicate-trash':
            selected = set(options['file_ids'])
            plans = []
            for group in job.duplicate_groups:
                copies = [item for item in group if item.id in selected]
                if not copies:
                    continue
                keeper = next(item for item in group if item.id not in selected)
                digest = self._digest(keeper, job)
                for item in copies:
                    if self._digest(item, job) != digest:
                        raise FileExistsError('Duplicate content changed; scan again')
                    plans.append((keeper, item))
            mover = self.trash
            if mover is None:
                if sys.platform != 'darwin':
                    raise ValueError('Moving duplicate copies to Trash requires macOS')
                from .engine_storage_cleaner import storage_cleaner
                mover = storage_cleaner._trash
            self._begin_mutation(job)
            outcomes = []
            for keeper, item in plans:
                try:
                    # Recheck the retained file and candidate immediately before
                    # the identity-checked, reversible Trash move.
                    if self._digest(keeper, job) != self._digest(item, job):
                        raise FileExistsError('Duplicate content changed')
                    # A mover returns False when the move happened but its restore record could not be kept.
                    recorded = mover(item.path, item.signature)
                    outcomes.append({'id': item.id, 'name': item.name, 'state': 'trashed', 'restorable': recorded is not False})
                except Exception:
                    # Preserve earlier move outcomes even when a native service
                    # times out or becomes unavailable partway through a batch.
                    outcomes.append({'id': item.id, 'name': item.name, 'state': 'failed', 'message': 'File changed, is in use, or could not be moved. Rescan before retrying.'})
                job.progress += 1
            # A cleanup consumes its selection: individual file roots may now
            # be in Trash, and a subsequent search needs fresh picker authority.
            self.selections.revoke(job.request.selection_ids[0])
            return {'items': outcomes, 'moved_count': sum(item['state'] == 'trashed' for item in outcomes),
                    'complete': all(item['state'] == 'trashed' for item in outcomes)}
        if kind == 'compare-folders':
            sides = []
            for key in job.request.selection_ids:
                sides.append({item.name: (item.signature[2], self._digest(item, job)) for item in self._files(job, key)})
            left, right = sides
            rows = [{'name': name, 'status': 'only-left' if name not in right else 'only-right' if name not in left else 'equal' if left[name] == right[name] else 'different'} for name in sorted(left.keys() | right.keys())]
            return {'files': rows, 'complete': True}
        if kind == 'similar-images':
            supported_exts = SimilarImageEngine.SUPPORTED_EXTENSIONS | SimilarImageEngine.MACOS_HEIC_EXTENSIONS
            all_files = list(self._files(job))
            items = [item for item in all_files if os.path.splitext(item.name)[1].lower() in supported_exts]
            if not items and all_files and len(all_files) <= SimilarImageEngine.MAX_FILES:
                items = all_files
            if len(items) > SimilarImageEngine.MAX_FILES:
                raise ValueError(f'Too many selected images ({len(items)}). Maximum is {SimilarImageEngine.MAX_FILES}.')
            if not items:
                raise ValueError('No supported images found in the selected folder.')
            from PIL import Image, ImageOps
            hashes, errors = [], []
            capture_times = {}
            pixels = 0
            job.phase = 'Reading images'
            job.total = len(items)
            job.progress = 0
            for item in items:
                self._check(job)
                job.progress += 1
                # File modified time stands in when a picture carries no EXIF capture time.
                capture_times[item.name] = item.signature[3] / 1_000_000_000
                try:
                    with self.selections.open_file(item) as source, Image.open(source) as image:
                        work = image.width * image.height
                        pixels += work
                        if work > SimilarImageEngine.MAX_PIXELS or pixels > SimilarImageEngine.MAX_TOTAL_PIXELS:
                            raise ValueError('Image scan exceeds pixel limits')
                        taken = SimilarImageEngine.capture_time(image)
                        if taken is not None:
                            capture_times[item.name] = taken
                        if image.format == 'JPEG':
                            # Let the decoder shrink large photos while reading; the hash only needs 32x32.
                            image.draft('RGB', (256, 256))
                        image.seek(0)
                        normalized = ImageOps.exif_transpose(image)
                        if normalized.mode in {'RGBA', 'LA'} or (normalized.mode == 'P' and 'transparency' in normalized.info):
                            rgba = normalized.convert('RGBA')
                            normalized = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba)
                        luma = normalized.convert('L').resize((32, 32), Image.Resampling.LANCZOS)
                        hashes.append((item.name, SimilarImageEngine._perceptual_fingerprint(luma.tobytes())))
                except (OSError, ValueError):
                    errors.append({'name': item.name, 'message': 'Image could not be decoded within the scan limits'})
            job.phase = 'Grouping similar images'
            return {**SimilarImageEngine.group_hashes(hashes, options['threshold'], capture_times, lambda: self._check(job)), 'scanned_images': len(hashes), 'errors': errors, 'complete': not errors, 'method': 'dct-perceptual-hash'}
        if kind in INSPECT_KINDS:
            return self._inspect(job)
        if kind == 'rename-preview':
            items = list(self._files(job))
            if not items:
                raise ValueError('No files found in the selection.')
            names = FileOpsEngine.generate_rename_plan([os.path.basename(item.path) for item in items], **options)
            mapping = []
            destinations = set()
            sources = {item.path for item in items}
            for item, name in zip(items, names):
                self._safe_name(name)
                target = os.path.join(os.path.dirname(item.path), name)
                collision = os.path.normcase(target).casefold()
                if collision in destinations or (os.path.lexists(target) and target not in sources):
                    raise FileExistsError('Rename would collide with existing files')
                destinations.add(collision)
                mapping.append((item, target))
            key = str(uuid.uuid4())
            self.previews[key] = {'selection': job.request.selection_ids[0], 'mapping': mapping, 'expires': self.clock() + PREVIEW_TTL}
            return {'previewId': key, 'files': [{'id': item.id, 'oldName': item.name, 'newName': os.path.basename(target)} for item, target in mapping], 'expiresIn': PREVIEW_TTL}
        if kind == 'rename-apply':
            return self._rename(job, options['preview_id'])
        return self._output(job, grant)

    @staticmethod
    def _safe_name(name):
        if not name or name in {'.', '..'} or any(char in name for char in '/\\\x00:') or len(name.encode()) > 240:
            raise ValueError('Unsafe output filename')

    def _rename(self, job, key):
        self._check(job)
        preview = self.previews.pop(key, None)
        if not preview or preview['expires'] <= self.clock():
            raise FileExistsError('Rename preview is stale')
        mapping = preview['mapping']
        sources = {item.path for item, target in mapping}
        for item, target in mapping:
            with self.selections.open_file(item):
                pass
            if os.path.lexists(target) and target not in sources:
                raise FileExistsError('Rename destination changed')
        self._begin_mutation(job)
        staged = []
        staged_by_path = {}
        published = []
        parents = contextlib.ExitStack()
        try:
            for item, target in mapping:
                if item.path == target:
                    continue
                parent = parents.enter_context(open_parent(item.path))
                original = os.path.basename(item.path) if parent is not None else item.path
                target = os.path.basename(target) if parent is not None else target
                temporary = '.officekit-rename-' + str(uuid.uuid4())
                if parent is None:
                    temporary = os.path.join(os.path.dirname(item.path), temporary)
                exclusive_rename(original, temporary, parent)
                if identity(os.stat(temporary, dir_fd=parent, follow_symlinks=False))[:4] != item.signature[:4]:
                    try:
                        exclusive_rename(temporary, original, parent)
                    except OSError:
                        pass
                    raise ValueError('Source changed during rename')
                staged.append((original, temporary, target, parent, item.signature))
                staged_by_path[item.path] = (temporary, target, parent)
            for original, temporary, target, parent, expected in staged:
                exclusive_rename(temporary, target, parent)
                published.append((original, temporary, target, parent, expected))
            return {'renamed': len(staged), 'rollback': None, 'complete': True}
        except Exception:
            rollback_complete = True
            for original, temporary, target, parent, expected in reversed(published):
                try:
                    if identity(os.stat(target, dir_fd=parent, follow_symlinks=False))[:4] != expected[:4]:
                        raise OSError('Rename target changed during recovery')
                    exclusive_rename(target, original, parent)
                except OSError:
                    rollback_complete = False
            for original, temporary, target, parent, expected in reversed(staged):
                try:
                    os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                    exclusive_rename(temporary, original, parent)
                except FileNotFoundError:
                    pass
                except OSError:
                    rollback_complete = False
            recovery = []
            for item, target_path in mapping:
                original = os.path.basename(item.path)
                stage = staged_by_path.get(item.path)
                temporary, target, parent = stage if stage else (None, os.path.basename(target_path), None)
                def owned(name):
                    try:
                        value = os.stat(name, dir_fd=parent, follow_symlinks=False)
                        return (value.st_dev, value.st_ino) == item.signature[:2]
                    except OSError:
                        return False
                restored = owned(original if stage else item.path)
                at_target = owned(target) if stage else False
                at_stage = owned(temporary) if temporary else False
                recovery.append({'id': item.id, 'oldName': item.name, 'newName': os.path.basename(target_path),
                                 'state': 'restored' if restored else 'published' if at_target else 'staged' if at_stage else 'changed-or-missing',
                                 'currentName': original if restored else target if at_target else temporary if at_stage else None,
                                 'temporaryName': temporary if at_stage else None})
            self._retain_result(job, {'complete': False, 'rollback': 'complete' if rollback_complete else 'partial', 'recoveryRequired': not rollback_complete, 'files': recovery})
            raise
        finally:
            parents.close()

    def _copy(self, source, target, job, budget):
        total = 0
        while chunk := source.read(CHUNK_BYTES):
            self._check(job)
            total += len(chunk)
            if total > budget:
                raise ValueError('Output exceeds 32 GiB limit')
            target.write(chunk)
        return total

    def _refuse_output_inside_selected_folder(self, job, grant):
        # QA-10: a temporary output in a selected folder would change that folder while it is read. Refuse before any
        # temporary file exists, with a message that names the cause. Only folder selections can contain the output.
        output_parent = os.path.realpath(os.path.dirname(grant.path))
        for key in job.request.selection_ids:
            for root, _root_id, directory in self.selections.get(key).roots:
                if directory and _is_within(output_parent, os.path.realpath(root)):
                    raise ValueError(OUTPUT_INSIDE_SELECTION)

    def _output(self, job, grant):
        if grant is None:
            raise ValueError('Output grant required')
        self._refuse_output_inside_selected_folder(job, grant)
        with open_parent(grant.path) as parent_fd:
            if parent_fd is not None:
                parent_stat = os.fstat(parent_fd)
                if (parent_stat.st_dev, parent_stat.st_ino) != grant.parent_identity:
                    raise FileExistsError('Output parent changed')
            return self._output_in_parent(job, grant, parent_fd)

    def _output_in_parent(self, job, grant, parent_fd):
        kind = job.request.kind
        if grant.kind != ('directory' if kind == 'archive-extract' else 'file'):
            raise ValueError('Output destination kind mismatch')
        parent = os.path.dirname(grant.path)
        if kind == 'archive-extract':
            return self._extract(job, grant, parent_fd)
        temporary_name = '.officekit-output-' + str(uuid.uuid4())
        if parent_fd is not None:
            descriptor = os.open(temporary_name, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=parent_fd)
            temporary = temporary_name
            temporary_identity = identity(os.fstat(descriptor))
        else:
            descriptor, temporary = tempfile.mkstemp(prefix='.officekit-output-', dir=parent)
            temporary_identity = identity(os.fstat(descriptor))
        published = False
        try:
            with os.fdopen(descriptor, 'w+b') as output:
                if kind in {'archive-create', 'split'}:
                    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                        items = list(self._files(job))
                        if not items:
                            raise ValueError('No files found in the selection.')
                        total = 0
                        for item in items:
                            with self.selections.open_file(item) as source:
                                if kind == 'archive-create':
                                    with archive.open(item.name, 'w', force_zip64=True) as member:
                                        total += self._copy(source, member, job, MAX_OUTPUT_BYTES - total)
                                else:
                                    if total or len(items) != 1:
                                        raise ValueError('Split requires one file')
                                    chunks = []
                                    part = 0
                                    while True:
                                        self._check(job)
                                        block = source.read(min(CHUNK_BYTES, job.request.options['chunk_size']))
                                        if not block:
                                            break
                                        part += 1
                                        name = f'part-{part:06d}'
                                        size = len(block)
                                        digest = hashlib.sha256(block)
                                        with archive.open(name, 'w') as member:
                                            member.write(block)
                                            while size < job.request.options['chunk_size']:
                                                block = source.read(min(CHUNK_BYTES, job.request.options['chunk_size'] - size))
                                                if not block:
                                                    break
                                                self._check(job)
                                                member.write(block)
                                                digest.update(block)
                                                size += len(block)
                                        total += size
                                        if total > MAX_OUTPUT_BYTES or part > 10_000:
                                            raise ValueError('Split output exceeds limits')
                                        chunks.append({'name': name, 'size': size, 'sha256': digest.hexdigest()})
                                    archive.writestr('manifest.json', json.dumps({'name': os.path.basename(item.path), 'chunks': chunks}))
                elif kind == 'join':
                    items = list(self._files(job))
                    if not items:
                        raise ValueError('No split archive found in the selection. Choose the split ZIP archive.')
                    if len(items) != 1:
                        raise ValueError('Join requires one split archive')
                    with self.selections.open_file(items[0]) as source, zipfile.ZipFile(source) as archive:
                        self._validate_archive(archive)
                        info = archive.getinfo('manifest.json')
                        if info.file_size > MAX_REPORT_BYTES:
                            raise ValueError('Split manifest exceeds limit')
                        manifest = json.loads(archive.read(info))
                        if set(manifest) != {'name', 'chunks'} or not isinstance(manifest['chunks'], list) or len(manifest['chunks']) > 10_000:
                            raise ValueError('Invalid split manifest')
                        total = 0
                        names = set()
                        for part in manifest['chunks']:
                            if set(part) != {'name', 'size', 'sha256'} or part['name'] in names:
                                raise ValueError('Invalid split part')
                            names.add(part['name'])
                            digest = hashlib.sha256()
                            size = 0
                            with archive.open(part['name']) as member:
                                while block := member.read(CHUNK_BYTES):
                                    self._check(job)
                                    total += len(block)
                                    size += len(block)
                                    if total > MAX_OUTPUT_BYTES:
                                        raise ValueError('Joined output exceeds limit')
                                    digest.update(block)
                                    output.write(block)
                            if size != part['size'] or digest.hexdigest() != part['sha256']:
                                raise ValueError('Split part failed integrity verification')
                output.flush()
                os.fsync(output.fileno())
                size = output.tell()
            self._check(job)
            self.selections.validate_output(grant)
            self._begin_mutation(job)
            destination = os.path.basename(grant.path) if parent_fd is not None else grant.path
            exclusive_rename(temporary, destination, parent_fd)
            published = True
            return {'saved': True, 'displayName': os.path.basename(grant.path), 'size_bytes': size, 'complete': True}
        finally:
            if not published:
                if parent_fd is not None:
                    remove_owned_file(temporary, parent_fd, temporary_identity)
                else:
                    try:
                        if identity(os.stat(temporary, follow_symlinks=False))[:2] == temporary_identity[:2]:
                            os.unlink(temporary)
                    except FileNotFoundError:
                        pass

    @staticmethod
    def _validate_archive(archive):
        entries = archive.infolist()
        if len(entries) > 10_000 or sum(entry.file_size for entry in entries) > MAX_OUTPUT_BYTES:
            raise ValueError('Archive exceeds extraction limits')
        names = set()
        reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', *(f'COM{index}' for index in range(1, 10)), *(f'LPT{index}' for index in range(1, 10))}
        for entry in entries:
            name = entry.filename.rstrip('/')
            path = PurePosixPath(name)
            mode = entry.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            parts = name.split('/')
            windows_unsafe = any(part.endswith((' ', '.')) or part.split('.')[0].upper() in reserved
                                 or any(ord(char) < 32 or char in '<>:"|?*' for char in part) for part in parts)
            if not name or len(name) > 32767 or path.is_absolute() or '\\' in name or '\x00' in name or windows_unsafe or any(part in {'', '.', '..'} or len(part) > 255 for part in parts) or name.casefold() in names or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError('Unsafe archive member')
            names.add(name.casefold())

    def _extract(self, job, grant, parent_fd):
        items = list(self._files(job))
        if not items:
            raise ValueError('No archive found in the selection.')
        if len(items) != 1 or grant.destination_identity is not None:
            raise ValueError('Extraction requires one archive and a new folder')
        with self.selections.open_file(items[0]) as source:
            is_zip = zipfile.is_zipfile(source)
        if not is_zip:
            if engine_archive_manager.extension_hint(items[0].name) not in engine_archive_manager.SEVEN_ZIP_READ:
                raise ValueError('This archive format is not enabled for extraction.')
            return self._extract_external(job, grant, items[0], parent_fd)
        if parent_fd is None:
            return self._extract_windows_zip(job, grant, items[0])
        temporary = '.officekit-output-' + str(uuid.uuid4())
        os.mkdir(temporary, 0o700, dir_fd=parent_fd)
        stage_fd = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent_fd)

        def directory_at(parent, name):
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            return os.open(name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent)

        def open_member_parent(parts):
            current = os.dup(stage_fd)
            try:
                for component in parts:
                    next_fd = directory_at(current, component)
                    os.close(current)
                    current = next_fd
                return current
            except Exception:
                os.close(current)
                raise

        def clear_directory(descriptor):
            for name in os.listdir(descriptor):
                value = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(value.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=descriptor)
                    try:
                        clear_directory(child)
                    finally:
                        os.close(child)
                    os.rmdir(name, dir_fd=descriptor)
                else:
                    os.unlink(name, dir_fd=descriptor)

        published = False
        try:
            with self.selections.open_file(items[0]) as source, zipfile.ZipFile(source) as archive:
                self._validate_archive(archive)
                entries = archive.infolist()
                if not job.request.options['all']:
                    wanted = set(job.request.options['entry_ids'])
                    by_id = {str(uuid.uuid5(uuid.UUID(items[0].selection_id), entry.filename.rstrip('/'))): entry for entry in entries}
                    if not wanted or not wanted.issubset(by_id):
                        raise ValueError('Selected archive entries are unavailable. Browse the archive again.')
                    selected_names = {by_id[key].filename.rstrip('/') for key in wanted}
                    entries = [entry for entry in entries if any(entry.filename.rstrip('/') == name or entry.filename.startswith(name + '/') for name in selected_names)]
                if any(entry.flag_bits & 1 for entry in entries):
                    raise ValueError('Password-protected archives are not supported.')
                total = 0
                for entry in entries:
                    self._check(job)
                    parts = entry.filename.rstrip('/').split('/')
                    if entry.is_dir():
                        directory = open_member_parent(parts)
                        os.close(directory)
                    else:
                        parent = open_member_parent(parts[:-1])
                        try:
                            descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=parent)
                            with archive.open(entry) as member, os.fdopen(descriptor, 'wb') as output:
                                total += self._copy(member, output, job, MAX_OUTPUT_BYTES - total)
                        finally:
                            os.close(parent)
            parent_stat = os.fstat(parent_fd)
            if (parent_stat.st_dev, parent_stat.st_ino) != grant.parent_identity:
                raise FileExistsError('Output parent changed')
            self._begin_mutation(job)
            exclusive_rename(temporary, os.path.basename(grant.path), parent_fd)
            published = True
            return {'saved': True, 'displayName': os.path.basename(grant.path), 'size_bytes': total, 'complete': True}
        finally:
            if not published:
                stage_identity = os.fstat(stage_fd)
                quarantine = '.officekit-cleanup-' + str(uuid.uuid4())
                try:
                    exclusive_rename(temporary, quarantine, parent_fd)
                    moved = os.stat(quarantine, dir_fd=parent_fd, follow_symlinks=False)
                    if (moved.st_dev, moved.st_ino) == (stage_identity.st_dev, stage_identity.st_ino):
                        clear_directory(stage_fd)
                        os.rmdir(quarantine, dir_fd=parent_fd)
                    else:
                        exclusive_rename(quarantine, temporary, parent_fd)
                except FileNotFoundError:
                    pass
            os.close(stage_fd)

    def _extract_external(self, job, grant, item, parent_fd):
        """Extract a 7-Zip-readable format into validated private staging."""
        parent = os.path.dirname(grant.path)
        if parent_fd is not None:
            parent_stat = os.fstat(parent_fd)
            if (parent_stat.st_dev, parent_stat.st_ino) != grant.parent_identity:
                raise FileExistsError('Output parent changed')
            work_name = '.officekit-archive-work-' + str(uuid.uuid4())
            stage_name = '.officekit-output-' + str(uuid.uuid4())
            work_fd = stage_fd = None
            try:
                os.mkdir(work_name, 0o700, dir_fd=parent_fd)
                os.mkdir(stage_name, 0o700, dir_fd=parent_fd)
                work_fd = os.open(work_name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent_fd)
                stage_fd = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent_fd)
            except BaseException:
                for descriptor in (work_fd, stage_fd):
                    if descriptor is not None:
                        os.close(descriptor)
                self._remove_tree_at(parent_fd, work_name)
                self._remove_tree_at(parent_fd, stage_name)
                raise
            work_path = f'/dev/fd/{parent_fd}/{work_name}'
            stage_path = f'/dev/fd/{parent_fd}/{stage_name}'
        else:
            if identity(os.stat(parent, follow_symlinks=False))[:2] != grant.parent_identity[:2]:
                raise FileExistsError('Output parent changed')
            operation_root = tempfile.mkdtemp(prefix='.officekit-archive-', dir=parent)
            work_name, stage_name = 'work', 'publish'
            work_path, stage_path = (os.path.join(operation_root, work_name), os.path.join(operation_root, stage_name))
            try:
                os.mkdir(work_path, 0o700)
                os.mkdir(stage_path, 0o700)
            except BaseException:
                shutil.rmtree(operation_root, ignore_errors=True)
                raise
            work_fd = stage_fd = None
        published = False
        try:
            with self.selections.open_file(item) as source:
                if os.name == 'nt':
                    archive_path, pass_fds = item.path, ()
                else:
                    archive_path, pass_fds = f'/dev/fd/{source.fileno()}', (source.fileno(), parent_fd)
                entries = engine_archive_manager.list_archive(archive_path, pass_fds=pass_fds)
                if not entries:
                    raise ValueError('The archive contains no extractable entries.')
                by_id = {str(uuid.uuid5(uuid.UUID(item.selection_id), entry['name'])): entry for entry in entries}
                if job.request.options['all']:
                    chosen = entries
                else:
                    wanted = set(job.request.options['entry_ids'])
                    if not wanted or not wanted.issubset(by_id):
                        raise ValueError('Selected archive entries are unavailable. Browse the archive again.')
                    selected_names = {by_id[key]['name'] for key in wanted}
                    chosen = [entry for entry in entries if any(entry['name'] == name or entry['name'].startswith(name + '/') for name in selected_names)]
                if any(entry['encrypted'] for entry in chosen):
                    raise ValueError('Password-protected archives are not supported.')
                engine_archive_manager.extract_archive(archive_path, work_path, lambda: self._check(job), pass_fds=pass_fds)
                self._validate_engine_output(work_path, entries, job)
                total = 0
                for entry in chosen:
                    self._check(job)
                    target = os.path.join(stage_path, *entry['name'].split('/'))
                    if entry['kind'] == 'directory':
                        os.makedirs(target, mode=0o700, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
                    with open(os.path.join(work_path, *entry['name'].split('/')), 'rb') as source_file:
                        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
                        with os.fdopen(descriptor, 'wb') as output:
                            total += self._copy(source_file, output, job, MAX_OUTPUT_BYTES - total)
            if parent_fd is not None:
                parent_stat = os.fstat(parent_fd)
                if (parent_stat.st_dev, parent_stat.st_ino) != grant.parent_identity:
                    raise FileExistsError('Output parent changed')
                self._begin_mutation(job)
                exclusive_rename(stage_name, os.path.basename(grant.path), parent_fd)
                published = True
                return {'saved': True, 'displayName': os.path.basename(grant.path), 'size_bytes': total, 'complete': True}
            if identity(os.stat(parent, follow_symlinks=False))[:2] != grant.parent_identity[:2]:
                raise FileExistsError('Output parent changed')
            self._begin_mutation(job)
            exclusive_rename(stage_path, grant.path, None)
            published = True
            return {'saved': True, 'displayName': os.path.basename(grant.path), 'size_bytes': total, 'complete': True}
        finally:
            if parent_fd is not None:
                for descriptor in (work_fd, stage_fd):
                    if descriptor is not None:
                        os.close(descriptor)
                for name in (work_name, stage_name):
                    if name == stage_name and published:
                        continue
                    self._remove_tree_at(parent_fd, name)
            elif os.path.exists(operation_root):
                shutil.rmtree(operation_root, ignore_errors=True)

    @staticmethod
    def _remove_tree_at(parent_fd, name):
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent_fd)
        except FileNotFoundError:
            return
        try:
            for child in os.listdir(descriptor):
                value = os.stat(child, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(value.st_mode):
                    FileJobStore._remove_tree_at(descriptor, child)
                else:
                    os.unlink(child, dir_fd=descriptor)
        finally:
            os.close(descriptor)
        os.rmdir(name, dir_fd=parent_fd)

    @staticmethod
    def _validate_engine_output(root, entries, job):
        expected_files = {entry['name']: entry for entry in entries if entry['kind'] == 'file'}
        allowed_dirs = {entry['name'] for entry in entries if entry['kind'] == 'directory'}
        for name in expected_files:
            parts = name.split('/')[:-1]
            for index in range(1, len(parts) + 1):
                allowed_dirs.add('/'.join(parts[:index]))
        seen_files = set()
        total = 0
        for current, directories, files in os.walk(root, followlinks=False):
            job.cancel.is_set() and FileJobStore._raise_cancelled()
            relative_dir = os.path.relpath(current, root)
            relative_dir = '' if relative_dir == '.' else relative_dir.replace(os.sep, '/')
            for name in list(directories):
                path = os.path.join(current, name)
                value = os.lstat(path)
                if stat.S_ISLNK(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('The archive produced an unsafe link or reparse point.')
                rel = '/'.join(part for part in (relative_dir, name) if part)
                if rel not in allowed_dirs:
                    raise ValueError('The archive produced an unlisted directory.')
            for name in files:
                path = os.path.join(current, name)
                value = os.lstat(path)
                if not stat.S_ISREG(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('The archive produced a special file or reparse point.')
                rel = '/'.join(part for part in (relative_dir, name) if part)
                expected = expected_files.get(rel)
                if expected is None or expected['size_bytes'] != value.st_size:
                    raise ValueError('The extracted files do not match the validated archive listing.')
                seen_files.add(rel)
                total += value.st_size
                if total > MAX_OUTPUT_BYTES:
                    raise ValueError('Archive exceeds the 32 GiB extraction limit')
        if seen_files != set(expected_files):
            raise ValueError('The extracted files do not match the validated archive listing.')

    @staticmethod
    def _raise_cancelled():
        raise Cancelled()

    def _extract_windows_zip(self, job, grant, item):
        """Extract validated ZIP members into a private sibling, then publish once."""
        parent = os.path.dirname(grant.path)
        parent_identity = identity(os.stat(parent, follow_symlinks=False))
        if parent_identity[:2] != grant.parent_identity[:2]:
            raise FileExistsError('Output parent changed')
        temporary = tempfile.mkdtemp(prefix='.officekit-output-', dir=parent)
        published = False
        try:
            with self.selections.open_file(item) as source, zipfile.ZipFile(source) as archive:
                self._validate_archive(archive)
                entries = archive.infolist()
                if not job.request.options['all']:
                    wanted = set(job.request.options['entry_ids'])
                    by_id = {str(uuid.uuid5(uuid.UUID(item.selection_id), entry.filename.rstrip('/'))): entry for entry in entries}
                    if not wanted or not wanted.issubset(by_id):
                        raise ValueError('Selected archive entries are unavailable. Browse the archive again.')
                    selected_names = {by_id[key].filename.rstrip('/') for key in wanted}
                    entries = [entry for entry in entries if any(entry.filename.rstrip('/') == name or entry.filename.startswith(name + '/') for name in selected_names)]
                if any(entry.flag_bits & 1 for entry in entries):
                    raise ValueError('Password-protected archives are not supported.')
                total = 0
                for entry in entries:
                    self._check(job)
                    parts = entry.filename.rstrip('/').split('/')
                    destination = os.path.join(temporary, *parts)
                    if entry.is_dir():
                        os.makedirs(destination, mode=0o700, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
                    descriptor = os.open(destination, flags, 0o600)
                    with archive.open(entry) as member, os.fdopen(descriptor, 'wb') as output:
                        total += self._copy(member, output, job, MAX_OUTPUT_BYTES - total)
            if identity(os.stat(parent, follow_symlinks=False))[:2] != grant.parent_identity[:2]:
                raise FileExistsError('Output parent changed')
            self._begin_mutation(job)
            exclusive_rename(temporary, grant.path, None)
            published = True
            return {'saved': True, 'displayName': os.path.basename(grant.path), 'size_bytes': total, 'complete': True}
        finally:
            if not published:
                shutil.rmtree(temporary, ignore_errors=True)

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                if not job.mutation:
                    job.cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=False)
        self.jobs.clear()
        self.previews.clear()
