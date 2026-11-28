"""Bounded local storage discovery and native-authorised, reviewed cleanup.

No client path is accepted. Scans are logical estimates; volume capacity is a
separate OS measurement. Cleanup never recursively deletes a directory.
"""
import concurrent.futures
import ctypes
import errno
import hmac
import heapq
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import threading
import tempfile
import time
import uuid
from pathlib import Path
from typing import Literal
from types import SimpleNamespace
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from officekit.engines.engine_file_selections import checked_path, identity, open_parent, exclusive_rename
from officekit.engines.engine_trash_ledger import TrashLedger


LOCAL_DISK_FILESYSTEMS = {'apfs', 'hfs', 'msdos', 'exfat', 'ntfs', 'ufsd', 'udf'}
MACOS_DATA_VOLUME = '/System/Volumes/Data'


def apfs_container_of(mount):
    """The APFS container a mounted volume lives in, or None when macOS cannot say."""
    try:
        output = subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', mount],
                                capture_output=True, timeout=5, check=True).stdout
        reference = plistlib.loads(output).get('APFSContainerReference')
        return reference if isinstance(reference, str) and reference else None
    except Exception:
        return None


def darwin_scan_roots(partitions, container_of):
    """Scan roots for macOS: the Data volume plus other physical disks, each container once.

    Volumes in one APFS container (Data, VM, Preboot, Recovery) all report the container's
    total size, and nullfs app-wrapper mounts mirror it again, so adding them would multiply
    the capacity (a 256 GB disk shown as 735 GB). An APFS volume whose container is unknown is
    skipped for the same reason."""
    roots = [MACOS_DATA_VOLUME]
    seen = {container_of(MACOS_DATA_VOLUME)} - {None}
    for mount, filesystem in partitions:
        if mount == '/' or mount.startswith('/System/Volumes/') or filesystem not in LOCAL_DISK_FILESYSTEMS:
            continue
        if filesystem == 'apfs':
            container = container_of(mount)
            if container is None or container in seen:
                continue
            seen.add(container)
        if mount not in roots:
            roots.append(mount)
    return roots


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    olderThanDays: StrictInt = Field(default=90, ge=1, le=3650)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scanId: StrictStr = Field(min_length=1, max_length=64)
    candidateIds: list[StrictStr] = Field(min_length=1, max_length=200)


class StorageCandidate(BaseModel):
    id: str
    name: str
    path: str
    category: str
    sizeBytes: int = Field(ge=0)
    modifiedAt: float = Field(allow_inf_nan=False)
    createdAt: float | None = Field(allow_inf_nan=False)
    method: Literal['trash', 'unsupported', 'tool']
    eligible: bool
    reason: str
    impact: str


class StorageCategory(BaseModel):
    id: Literal['applications', 'documents', 'media', 'developer', 'caches', 'system', 'other', 'unclassified', 'available']
    sizeBytes: int = Field(ge=0)


class StorageVolume(BaseModel):
    path: str
    capacityBytes: int = Field(ge=0)
    usedBytes: int = Field(ge=0)
    availableBytes: int = Field(ge=0)
    logicalBytes: int = Field(ge=0)
    categories: list[StorageCategory] = Field(max_length=9)
    logicalCategories: list[StorageCategory] = Field(max_length=7)
    unclassifiedUsedBytes: int = Field(ge=0)
    categoryBasis: Literal['allocated-estimate']


class StorageCoverage(BaseModel):
    path: str
    state: Literal['complete', 'partial', 'inaccessible']
    reason: str
    inaccessibleCount: int | None = Field(default=None, ge=0)


class StorageDockerUsage(BaseModel):
    id: Literal['images', 'containers', 'volumes', 'build-cache', 'other']
    label: str
    totalCount: int | None = Field(ge=0)
    activeCount: int | None = Field(ge=0)
    sizeBytes: int | None = Field(ge=0)
    reclaimableBytes: int | None = Field(ge=0)


class StorageTool(BaseModel):
    id: Literal['docker', 'npm', 'yarn', 'pnpm', 'pip', 'uv']
    available: bool
    cleanupSupported: bool
    reason: str
    cachePath: str | None = None
    impact: str | None = None
    usage: list[StorageDockerUsage] = Field(default_factory=list, max_length=16)


class StorageOutcome(BaseModel):
    id: str
    status: Literal['moved', 'cleaned', 'skipped', 'failed']
    sizeBytes: int = Field(ge=0)
    message: str


class StorageCancellation(BaseModel):
    id: str
    cancellationRequested: bool


class StorageLargestEntry(BaseModel):
    path: str
    name: str
    sizeBytes: int = Field(ge=0)
    fileCount: int = Field(ge=0)
    modifiedAt: float = Field(allow_inf_nan=False)
    createdAt: float | None = Field(allow_inf_nan=False)
    partial: bool


class StorageReport(BaseModel):
    scope: Literal['system']
    volumes: list[StorageVolume] = Field(max_length=256)
    categories: list[StorageCategory] = Field(max_length=7)
    logicalBytes: int = Field(ge=0)
    candidates: list[StorageCandidate] = Field(max_length=2006)
    coverage: list[StorageCoverage] = Field(max_length=256)
    complete: bool
    entriesScanned: int = Field(ge=0)
    tools: list[StorageTool] = Field(max_length=6)
    mutationSupported: bool
    limitations: list[str]
    largestFiles: list[StorageLargestEntry] = Field(default_factory=list, max_length=100)
    largestFolders: list[StorageLargestEntry] = Field(default_factory=list, max_length=100)


class StorageStatus(BaseModel):
    id: str
    state: Literal['queued', 'running', 'ready', 'cancelled', 'failed']
    progress: int = Field(ge=0, le=100)
    entriesScanned: int = Field(default=0, ge=0)
    candidateCount: int = Field(default=0, ge=0)
    candidateBytes: int = Field(default=0, ge=0)
    report: StorageReport | None
    error: str | None


class StoragePlan(BaseModel):
    id: str
    expiresAt: float
    items: list[StorageCandidate] = Field(max_length=200)
    estimatedBytes: int = Field(ge=0)
    impact: str


class StorageExecutionProgress(BaseModel):
    id: str
    state: Literal['running', 'finished']
    done: int = Field(ge=0)
    total: int = Field(ge=0)
    movedBytes: int = Field(ge=0)
    stopRequested: bool


class StorageExecutionStop(BaseModel):
    id: str
    stopRequested: bool


class StorageExecution(BaseModel):
    id: str
    items: list[StorageOutcome] = Field(max_length=200)
    movedBytes: int = Field(ge=0)
    measuredFreeSpaceChangeBytes: int
    trashOccupancyIncreaseBytes: int
    reclaimedBytes: int


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CleanupRecoveryError(ValueError):
    """A cache was preserved in staging because its original name was recreated."""


CATEGORIES = ('applications', 'documents', 'media', 'developer', 'caches', 'system', 'other')
PROTECTED = {'.ssh', '.aws', '.gnupg', '.venv', 'venv', 'env', '.git', '.Trash', 'Trash', '$Recycle.Bin'}
UNRECORDED_TRASH_MESSAGE = 'Moved to Trash. OfficeKit could not keep a restore record for it, so it cannot be put back from Restore from Trash.'
MEDIA = {'.jpg', '.jpeg', '.png', '.heic', '.gif', '.mp4', '.mov', '.mp3', '.wav', '.webp'}
DOCUMENTS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md'}
PROJECT_MARKERS = {'package.json', 'pyproject.toml', 'Cargo.toml', 'pom.xml', 'build.gradle', 'go.mod'}


# AI assistant folders reviewed as cache or history. Credentials, settings, skills, knowledge and git
# worktrees sit next to these folders and are deliberately not listed: only what is named here is offered.
_VSCODE_CACHE_FOLDERS = ('Cache', 'CachedData', 'Code Cache', 'GPUCache', 'logs')
ASSISTANT_FOLDERS = {
    'Antigravity': ['.gemini/antigravity/' + name for name in ('brain', 'conversations', 'cache', 'crashes', 'log', 'scratch')]
                   + ['Library/Application Support/Antigravity/' + name for name in _VSCODE_CACHE_FOLDERS],
    'Gemini': ['.gemini/tmp', '.gemini/logs'],
    'Cursor': ['.cursor/projects', '.cursor/cache']
              + ['Library/Application Support/Cursor/' + name for name in _VSCODE_CACHE_FOLDERS],
    'Windsurf': ['.windsurf/cache']
                + ['Library/Application Support/Windsurf/' + name for name in _VSCODE_CACHE_FOLDERS],
}


class StorageCleaner:
    def __init__(self, native_token=None, roots=None, home=None, platform=None, clock=time.time,
                 max_entries=250000, max_seconds=120, executor=None, ledger=None):
        self.native_token = native_token if native_token is not None else os.environ.get('OFFICEKIT_NATIVE_GRANT_TOKEN', '')
        self.home = os.path.abspath(home or str(Path.home()))
        # The Trash ledger lives beside the user's data, under the same home as the Trash it describes.
        self.ledger = ledger if ledger is not None else TrashLedger(os.path.join(self.home, 'Library', 'Application Support', 'OfficeKit', 'trash-ledger.json'))
        self.platform = platform or sys.platform
        self.roots = roots
        self.clock = clock
        self.max_entries = max_entries
        self.max_seconds = max_seconds
        self.executor = executor or concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='storage')
        self.lock = threading.RLock()
        self.jobs = {}
        self.plans = {}
        self.executions = {}

    def authorize(self, credential):
        if not self.native_token or not isinstance(credential, str) or not hmac.compare_digest(self.native_token, credential):
            raise PermissionError('Native storage authorization required')

    def _roots(self):
        if self.roots is not None:
            return list(dict.fromkeys(os.path.realpath(root) for root in self.roots))
        if self.platform == 'win32':
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            return [f'{chr(65 + index)}:\\' for index in range(26)
                    if mask & (1 << index) and ctypes.windll.kernel32.GetDriveTypeW(f'{chr(65 + index)}:\\') == 3]
        # psutil returns mounted local disks and distinguishes network filesystems.
        import psutil
        excluded = {'nfs', 'nfs4', 'smbfs', 'cifs', 'autofs', 'fuse.sshfs'}
        mounts = [disk.mountpoint for disk in psutil.disk_partitions(all=False) if disk.fstype not in excluded]
        if self.platform == 'darwin':
            # The firmlink Data tree is authoritative for writable user data;
            # traversing both / and Data would duplicate the same APFS contents.
            # Other APFS volumes (Recovery) and app-wrapper nullfs mounts report the
            # whole container's size, so each is counted only once per container.
            partitions = [(disk.mountpoint, disk.fstype) for disk in psutil.disk_partitions(all=False)]
            return darwin_scan_roots(partitions, apfs_container_of)
        return list(dict.fromkeys(mounts or ['/']))

    def submit(self, request, credential):
        self.authorize(credential)
        with self.lock:
            now = self.clock()
            self.jobs = {key: job for key, job in self.jobs.items() if now - job['created'] < 1800}
            if len(self.jobs) >= 8 or any(job['state'] in {'queued', 'running'} for job in self.jobs.values()):
                raise RuntimeError('Storage scan queue is full')
            key = str(uuid.uuid4())
            job = {'id': key, 'state': 'queued', 'progress': 0, 'created': now,
                   'entriesScanned': 0, 'candidateCount': 0, 'candidateBytes': 0,
                   'cancel': threading.Event(), 'candidates': {}, 'report': None, 'error': None}
            self.jobs[key] = job
            job['future'] = self.executor.submit(self._run, job, request)
            return self.status(key)

    def _job(self, key):
        job = self.jobs.get(key)
        if job is None or self.clock() - job['created'] >= 1800:
            raise FileNotFoundError('Storage scan expired')
        return job

    def wait(self, key):
        self._job(key)['future'].result(timeout=30)

    def status(self, key):
        with self.lock:
            job = self._job(key)
            return {name: job[name] for name in ('id', 'state', 'progress', 'entriesScanned',
                                                  'candidateCount', 'candidateBytes', 'report', 'error')}

    def cancel(self, key):
        with self.lock:
            job = self._job(key)
            job['cancel'].set()
            return {'id': key, 'cancellationRequested': True}

    def _cache_roots(self):
        relative = ['.npm/_cacache', '.npm/_logs', '.cache/pip', '.cache/uv', '.cache/yarn',
                    '.yarn/cache', '.local/share/pnpm/store', 'Library/Caches',
                    '.gradle/caches', '.m2/repository', '.cargo/registry/cache',
                    '.cargo/registry/src', '.cargo/git/db',
                    '.claude/cache', '.claude/file-history', '.claude/paste-cache',
                    '.claude/projects', '.claude/jobs',
                    '.codex/cache', '.codex/.tmp', '.codex/sessions']
        if self.platform == 'darwin':
            relative += ['Library/Developer/Xcode/DerivedData',
                         'Library/Caches/com.openai.codex',
                         'Library/Caches/claude-cli-nodejs',
                         'Library/Caches/com.anthropic.claudefordesktop',
                         'Library/Caches/Codex']
            for folders in ASSISTANT_FOLDERS.values():
                relative += folders
        if self.platform == 'win32':
            relative += ['AppData/Local/Temp', 'AppData/Local/pip/Cache', 'AppData/Local/npm-cache']
        return [os.path.join(self.home, part) for part in relative]

    def _assistant_label(self, path):
        """The AI assistant that owns this file, or None. Matches only the folders in ASSISTANT_FOLDERS."""
        path = self._display_path(path)
        for label, folders in ASSISTANT_FOLDERS.items():
            if any(path.startswith(os.path.join(self.home, folder) + os.sep) for folder in folders):
                return label
        return None

    def _classification(self, path, developer=False):
        path = self._display_path(path)
        if any(path.startswith(root + os.sep) for root in self._cache_roots()):
            return 'caches'
        if developer:
            return 'developer'
        suffix = Path(path).suffix.lower()
        if suffix in MEDIA:
            return 'media'
        if suffix in DOCUMENTS:
            return 'documents'
        if '/Applications/' in path or suffix in {'.app', '.exe', '.dll'}:
            return 'applications'
        if path.startswith(('/System/', '/usr/', '/bin/', '/sbin/', '/Library/')):
            return 'system'
        return 'other'

    def _display_path(self, path):
        if self.platform == 'darwin' and path.startswith('/System/Volumes/Data/'):
            return path[len('/System/Volumes/Data'):]
        return path

    def _run(self, job, request):
        job['state'] = 'running'
        try:
            job['report'] = self._scan(job, request)
            job['state'] = 'cancelled' if job['cancel'].is_set() else 'ready'
            job['progress'] = 100
        except Exception:
            job['state'] = 'failed'
            job['error'] = 'Storage scan could not complete. No files were changed.'

    def _scan(self, job, request):
        started = time.monotonic()
        seen = set()
        volumes, coverage, candidates = [], [], []
        counts = {name: 0 for name in CATEGORIES}
        entries = 0
        truncated = False
        largest_files = []
        folders = {}
        roots = self._roots()
        for root in roots:
            try:
                usage = shutil.disk_usage(root)
                root_device = os.stat(root).st_dev
            except OSError:
                coverage.append({'path': root, 'state': 'inaccessible', 'reason': 'Volume is unavailable or access was denied.'})
                continue
            local = {name: 0 for name in CATEGORIES}
            allocated = {name: 0 for name in CATEGORIES}
            priority = [path for path in self._cache_roots() + [os.path.join(self.home, 'Downloads')]
                        if os.path.isdir(path) and os.stat(path).st_dev == root_device]
            stack = [(root, False)] + [(path, False) for path in priority]
            inaccessible = 0
            while stack:
                if job['cancel'].is_set() or entries >= self.max_entries or time.monotonic() - started >= self.max_seconds:
                    truncated = True
                    break
                folder, parent_project = stack.pop()
                try:
                    children = self._children(folder, self.max_entries - entries)
                    if len(children) >= self.max_entries - entries:
                        truncated = True
                    project = parent_project or any(child.name in PROJECT_MARKERS for child in children)
                    for child in children:
                        entries += 1
                        job['entriesScanned'] = entries
                        if job['cancel'].is_set():
                            break
                        try:
                            value = child.stat(follow_symlinks=False)
                            if value.st_dev != root_device or stat.S_ISLNK(value.st_mode):
                                continue
                            signature = (value.st_dev, value.st_ino)
                            if signature in seen:
                                continue
                            seen.add(signature)
                            if stat.S_ISDIR(value.st_mode):
                                in_downloads = self._display_path(child.path).startswith(os.path.join(self.home, 'Downloads') + os.sep)
                                if in_downloads and child.name in {'node_modules', 'vendor'}:
                                    continue
                                if child.name not in PROTECTED and child.path not in roots and child.name not in {'proc', 'sys', 'dev'}:
                                    stack.append((child.path, project))
                                continue
                            if not stat.S_ISREG(value.st_mode):
                                continue
                            category = self._classification(child.path, project)
                            counts[category] += value.st_size
                            local[category] += value.st_size
                            allocated[category] += getattr(value, 'st_blocks', (value.st_size + 511) // 512) * 512
                            entry = self._largest_entry(child.path, value)
                            heapq.heappush(largest_files, (value.st_size, entry['path'], entries, entry))
                            if len(largest_files) > 100:
                                heapq.heappop(largest_files)
                            self._folder_totals(child.path, root, value.st_size, folders)
                            downloads = self._display_path(child.path).startswith(os.path.join(self.home, 'Downloads') + os.sep)
                            old = value.st_mtime < self.clock() - request.olderThanDays * 86400
                            generated = self._generated(child.path)
                            if category == 'caches' or (downloads and old) or generated:
                                if len(candidates) < 2000:
                                    parts = Path(child.path).parts
                                    claude = any(part in {'.claude', 'claude-cli-nodejs', 'com.anthropic.claudefordesktop', 'com.anthropic.claudefordesktop.ShipIt'} or part.startswith('.claude') for part in parts)
                                    codex = any(part in {'.codex', 'com.openai.codex', 'Codex'} or part.startswith('.codex') for part in parts)
                                    if claude:
                                        reason = 'Claude cache/history file'
                                    elif codex:
                                        reason = 'Codex cache/session file'
                                    elif self._assistant_label(child.path):
                                        reason = self._assistant_label(child.path) + ' cache/history file'
                                    elif downloads:
                                        reason = 'Old download'
                                    elif generated:
                                        reason = 'Generated project file'
                                    else:
                                        reason = 'Cache file'
                                    candidate = self._candidate(child.path, value, 'downloads' if downloads else category, reason)
                                    candidates.append(candidate)
                                    job['candidates'][candidate['id']] = (candidate, identity(value))
                                    job['candidateCount'] = len(candidates)
                                    job['candidateBytes'] += candidate['sizeBytes']
                        except OSError:
                            inaccessible += 1
                except OSError:
                    inaccessible += 1
            scanned = sum(local.values())
            used = usage.total - usage.free
            # Logical sizes can exceed physical usage (sparse/compressed files).
            # Never present those estimates as physical category measurements.
            # Allocated file bytes remain estimates (APFS clones/compression).
            # Clamp estimates to measured used space and leave the unscanned
            # remainder explicitly unclassified; capacity always reconciles.
            measured = sum(allocated.values())
            ratio = min(1, used / measured) if measured else 1
            physical = [{'id': key, 'sizeBytes': int(size * ratio)} for key, size in allocated.items()]
            residual = used - sum(item['sizeBytes'] for item in physical)
            physical.append({'id': 'unclassified', 'sizeBytes': residual})
            physical.append({'id': 'available', 'sizeBytes': usage.free})
            volumes.append({'path': root, 'capacityBytes': usage.total, 'usedBytes': used,
                            'availableBytes': usage.free, 'logicalBytes': scanned,
                            'categories': physical,
                            'logicalCategories': [{'id': key, 'sizeBytes': size} for key, size in local.items()],
                            'unclassifiedUsedBytes': residual, 'categoryBasis': 'allocated-estimate'})
            coverage.append({'path': root, 'state': 'partial',
                             'reason': 'Scan limit, skipped protected locations or inaccessible files; logical category estimates only.',
                             'inaccessibleCount': inaccessible})
        tools = self._tools() if not job['cancel'].is_set() and time.monotonic() - started < self.max_seconds else []
        for tool in tools:
            if tool['cleanupSupported']:
                candidate = {'id': str(uuid.uuid4()), 'name': tool['id'] + ' tool-managed cache', 'path': tool['cachePath'],
                             'category': 'developer', 'sizeBytes': 0, 'modifiedAt': self.clock(), 'createdAt': None,
                             'method': 'tool', 'eligible': True, 'reason': 'Tool-managed permanent cache cleanup; size not measured.',
                             'impact': tool['impact']}
                candidates.append(candidate)
                job['candidates'][candidate['id']] = (candidate, tool)
        return {'scope': 'system', 'volumes': volumes, 'categories': [{'id': key, 'sizeBytes': size} for key, size in counts.items()],
                'logicalBytes': sum(counts.values()), 'candidates': candidates, 'coverage': coverage,
                'complete': not truncated and all(item['state'] == 'complete' for item in coverage),
                'entriesScanned': entries, 'tools': [StorageTool.model_validate(tool).model_dump() for tool in tools],
                'mutationSupported': self.platform == 'darwin',
                'largestFiles': sorted((entry[3] for entry in largest_files), key=lambda entry: (-entry['sizeBytes'], entry['path'])),
                'largestFolders': sorted(folders.values(), key=lambda entry: (-entry['sizeBytes'], entry['path']))[:100],
                'limitations': ['Logical file sizes are estimates, not physical category usage.',
                                'Protected credentials, virtual environments, Trash and other mounted volumes are not traversed.',
                                'Only current-user regular files are eligible; active data and files modified within 7 days are protected.',
                                'At most 2,000 file cleanup candidates are shown per scan; rerun after cleanup to discover additional items.',
                                'Largest folders aggregate scanned descendants only (up to 10,000 folders and 64 ancestor levels); sizes and counts are partial estimates.',
                                'Tool cleanup is permanent and global for the reviewed cache; Docker volumes are never deleted.']}

    def _largest_entry(self, path, value, partial=False):
        path = self._display_path(path)
        return {'path': path, 'name': os.path.basename(path) or path, 'sizeBytes': value.st_size,
                'fileCount': 1, 'modifiedAt': value.st_mtime,
                'createdAt': getattr(value, 'st_birthtime', None), 'partial': partial}

    def _folder_totals(self, path, root, size, folders):
        parent = os.path.dirname(self._display_path(path))
        root = self._display_path(root)
        for depth in range(64):
            if parent not in folders and len(folders) < 10000:
                try:
                    entry = self._largest_entry(parent, os.stat(parent, follow_symlinks=False), partial=True)
                    entry.update(sizeBytes=0, fileCount=0)
                    folders[parent] = entry
                except OSError:
                    pass
            if parent in folders:
                folders[parent]['sizeBytes'] += size
                folders[parent]['fileCount'] += 1
            if parent == root or parent == os.path.dirname(parent):
                break
            parent = os.path.dirname(parent)

    @staticmethod
    def _children(folder, limit):
        # Bind discovery to an opened, no-follow directory chain. A queued
        # pathname replaced by a link never redirects traversal.
        with open_parent(os.path.join(folder, 'placeholder')) as descriptor:
            with os.scandir(descriptor if descriptor is not None else folder) as iterator:
                children = []
                for child in iterator:
                    if len(children) >= limit:
                        break
                    try:
                        value = child.stat(follow_symlinks=False)
                        failure = None
                    except OSError as error:
                        value, failure = None, error
                    def captured_stat(follow_symlinks=False, value=value, failure=failure):
                        if failure is not None:
                            raise failure
                        return value
                    children.append(SimpleNamespace(name=child.name, path=os.path.join(folder, child.name), stat=captured_stat))
                return children

    @staticmethod
    def _generated(path):
        parts = Path(path).parts
        for index, part in enumerate(parts[:-1]):
            markers = {'node_modules': ('package.json',), '.next': ('package.json',), '.nuxt': ('package.json',),
                       'target': ('Cargo.toml', 'pom.xml'),
                       '__pycache__': ('pyproject.toml', 'setup.py', 'requirements.txt'),
                       '.pytest_cache': ('pyproject.toml', 'setup.py', 'requirements.txt'),
                       '.mypy_cache': ('pyproject.toml', 'setup.py', 'requirements.txt'),
                       '.ruff_cache': ('pyproject.toml', 'setup.py', 'requirements.txt')}.get(part)
            if markers:
                parent = os.path.join(*parts[:index])
                if any(os.path.isfile(os.path.join(parent, marker)) for marker in markers):
                    return True
        return False

    def _candidate(self, path, value, category, reason):
        path = self._display_path(path)
        owned = value.st_uid == os.getuid() if hasattr(os, 'getuid') else False
        home_path = path.startswith(self.home + os.sep)
        quiet = value.st_mtime < self.clock() - 7 * 86400
        eligible = self.platform == 'darwin' and owned and home_path and quiet and value.st_nlink == 1
        impact = ('Personal download; review before moving.' if category == 'downloads'
                  else 'May remove cached project snapshots or conversation history; close the application before cleaning.' if reason.endswith(('cache/history file', 'cache/session file'))
                  else 'May require a rebuild or cache download; close the owning application first.')
        return {'id': str(uuid.uuid4()), 'name': os.path.basename(path), 'path': path, 'category': category,
                'sizeBytes': value.st_size, 'modifiedAt': value.st_mtime,
                'createdAt': getattr(value, 'st_birthtime', None), 'method': 'trash' if eligible else 'unsupported',
                'eligible': eligible, 'reason': reason,
                'impact': impact}

    def _command(self, argv, pass_fds=()):
        environment = {key: value for key, value in os.environ.items()
                       if key in {'PATH', 'HOME', 'USER', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT'}}
        environment['HOME'] = self.home
        environment['PATH'] = self._tool_search_path()
        with tempfile.TemporaryFile() as output:
            cleanup = any(part in {'clean', 'purge', 'prune'} for part in argv)
            process = subprocess.run(argv, stdout=output, stderr=subprocess.DEVNULL, shell=False,
                                     env=environment, timeout=30 if cleanup else 5, check=False, pass_fds=pass_fds)
            if process.returncode:
                raise ValueError('Tool command failed')
            output.seek(0)
            result = output.read(1024 * 1024 + 1)
            if len(result) > 1024 * 1024:
                raise ValueError('Tool response exceeds limit')
            return result.decode('utf-8').strip()

    def _tool_search_path(self):
        """Include common interactive-shell install locations omitted by GUI launchers."""
        directories = list(os.environ.get('PATH', '').split(os.pathsep))
        directories.extend([os.path.join(self.home, '.local/bin'),
                            os.path.join(self.home, '.docker/bin'),
                            os.path.join(self.home, '.volta/bin'),
                            os.path.join(self.home, '.bun/bin'),
                            os.path.join(self.home, '.local/share/pnpm'),
                            os.path.join(self.home, 'Library/pnpm'),
                            os.path.join(self.home, '.asdf/shims'),
                            '/Applications/Docker.app/Contents/Resources/bin'])
        versioned_patterns = ('.nvm/versions/node/*/bin', '.fnm/node-versions/*/installation/bin')
        for pattern in versioned_patterns:
            paths = list(Path(self.home).glob(pattern))
            paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
            directories.extend(str(path) for path in paths)
        directories.extend(['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin'])
        return os.pathsep.join(dict.fromkeys(path for path in directories if path and os.path.isdir(path)))

    def _tool_executable(self, name):
        search_path = self._tool_search_path()
        return shutil.which(name, path=search_path) or (
            shutil.which('pip3', path=search_path) if name == 'pip' else None)

    def _tool(self, name):
        executable = self._tool_executable(name)
        result = {'id': name, 'available': executable is not None, 'cleanupSupported': False, 'usage': [],
                  'reason': 'Tool unavailable or cache location could not be safely validated.'}
        if executable is None or self.platform != 'darwin':
            return result
        executable = os.path.realpath(executable)
        value = os.stat(executable)
        if not stat.S_ISREG(value.st_mode) or value.st_mode & 0o022 or value.st_uid not in {0, os.getuid()}:
            return result
        queries = {'npm': ['config', 'get', 'cache'], 'pip': ['cache', 'dir'], 'uv': ['cache', 'dir']}
        if name in {'yarn', 'pnpm'}:
            result['reason'] = 'Detected; review individual store files for Trash cleanup.'
            return result
        if name == 'docker':
            context = self._command([executable, 'context', 'show'])
            if not context or len(context) > 128 or not all(character.isalnum() or character in '_.-' for character in context):
                return result
            data = json.loads(self._command([executable, 'context', 'inspect', context]))
            endpoint = data[0]['Endpoints']['docker']['Host']
            if not endpoint.startswith('unix:///'):
                result['reason'] = 'Remote Docker contexts are excluded.'
                return result
            socket = os.path.realpath(endpoint[len('unix://'):])
            checked_path(socket)
            socket_value = os.stat(socket)
            if not stat.S_ISSOCK(socket_value.st_mode) or socket_value.st_uid not in {0, os.getuid()}:
                return result
            endpoint = 'unix://' + socket
            command = [executable, '--host', endpoint, 'builder', 'prune', '--force', '--filter', 'until=168h']
            cache = endpoint
            impact = 'Permanently prunes unused Docker build cache older than 7 days on this local daemon. Volumes and images are not selected.'
            scope_identity = identity(socket_value)
            result['usage'] = self._docker_usage(executable, endpoint)
        else:
            query = [executable, *queries[name]]
            if name == 'npm':
                query = [executable, 'config', 'get', 'cache']
            cache = self._command(query)
            checked_path(cache)
            expected = {'npm': [os.path.join(self.home, '.npm')],
                        'pip': [os.path.join(self.home, 'Library/Caches/pip'), os.path.join(self.home, '.cache/pip')],
                        'uv': [os.path.join(self.home, 'Library/Caches/uv'), os.path.join(self.home, '.cache/uv')]}
            if cache not in expected[name] or not os.path.isdir(cache) or os.stat(cache).st_uid != os.getuid():
                return result
            args = {'npm': ['cache', 'clean', '--force', '--cache', cache],
                    'pip': ['cache', 'purge', '--cache-dir', cache], 'uv': ['cache', 'clean', '--cache-dir', cache]}
            command = [executable, *args[name]]
            impact = 'Permanently clears the complete ' + name + ' cache. Close package installations first; packages must be downloaded again.'
            scope_identity = identity(os.stat(cache))
        result.update(cleanupSupported=True, reason='Validated local tool cache.', cachePath=cache,
                      command=command, executableIdentity=identity(value), scopeIdentity=scope_identity, impact=impact)
        return result

    @staticmethod
    def _docker_count(value):
        text = str(value)
        if not re.fullmatch(r'\d{1,19}', text):
            return None
        number = int(text)
        return number if number <= 9223372036854775807 else None

    @staticmethod
    def _docker_bytes(value):
        if not isinstance(value, str) or len(value) > 96:
            return None
        match = re.fullmatch(r'\s*(\d{1,19}(?:\.\d{1,9})?)\s*([KMGTPE]?i?B)(?:\s*\(\d{1,3}(?:\.\d+)?%\))?\s*', value, re.IGNORECASE)
        if match is None:
            return None
        unit = match[2].lower()
        exponent = 'bkmgtpe'.index(unit[0]) if unit != 'b' else 0
        # The first character index has b=0,k=1,...; Docker SI units use
        # powers of 1000, explicit IEC iB units powers of 1024.
        size = Decimal(match[1]) * (1024 if 'i' in unit else 1000) ** exponent
        return int(size) if size <= 9223372036854775807 else None

    def _docker_usage(self, executable, endpoint):
        output = self._command([executable, '--host', endpoint, 'system', 'df', '--format', '{{json .}}'])
        lines = [line for line in output.splitlines() if line.strip()]
        if len(lines) > 16:
            raise ValueError('Docker usage response exceeds limit')
        result = []
        names = {'Images': ('images', 'Images'), 'Containers': ('containers', 'Containers'),
                 'Local Volumes': ('volumes', 'Volumes (inspection only)'), 'Build Cache': ('build-cache', 'Build cache')}
        for line in lines:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError('Docker usage response must contain objects')
            category, label = names.get(entry.get('Type'), ('other', 'Other Docker data'))
            result.append({'id': category, 'label': label, 'totalCount': self._docker_count(entry.get('TotalCount')),
                           'activeCount': self._docker_count(entry.get('Active')),
                           'sizeBytes': self._docker_bytes(entry.get('Size')),
                           'reclaimableBytes': self._docker_bytes(entry.get('Reclaimable'))})
        return result

    def _tools(self):
        result = []
        for name in ('docker', 'npm', 'yarn', 'pnpm', 'pip', 'uv'):
            try:
                result.append(self._tool(name))
            except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
                result.append({'id': name, 'available': self._tool_executable(name) is not None, 'cleanupSupported': False,
                               'reason': 'Tool unavailable or validation failed.'})
        return result

    def plan(self, request):
        with self.lock:
            job = self._job(request.scanId)
            if job['state'] != 'ready':
                raise ValueError('A completed scan is required')
            if len(set(request.candidateIds)) != len(request.candidateIds):
                raise ValueError('Duplicate candidate')
            selected = []
            for key in request.candidateIds:
                if key not in job['candidates'] or not job['candidates'][key][0]['eligible']:
                    raise ValueError('Candidate is unavailable for cleanup')
                selected.append(job['candidates'][key])
            for item, signature in selected:
                if item['method'] == 'tool' and any(other['id'] != item['id'] and other['path'].startswith(item['path'] + os.sep)
                                                   for other, ignored in selected):
                    raise ValueError('Select either a complete tool cache or its individual files')
            now = self.clock()
            self.plans = {key: plan for key, plan in self.plans.items() if plan['expiresAt'] > now}
            if len(self.plans) >= 32:
                raise RuntimeError('Cleanup plan queue is full')
            key = str(uuid.uuid4())
            public = {'id': key, 'expiresAt': now + 300, 'items': [item for item, signature in selected],
                      'estimatedBytes': sum(item['sizeBytes'] for item, signature in selected),
                      'impact': 'Tool caches are permanently cleared. Selected files move to Trash; their disk space is not reclaimed until Trash is emptied.'}
            self.plans[key] = {**public, 'selected': selected}
            return public

    def execute(self, key, credential):
        self.authorize(credential)
        with self.lock:
            plan = self.plans.pop(key, None)
        if plan is None or plan['expiresAt'] <= self.clock():
            raise FileNotFoundError('Cleanup plan expired or already used')
        if self.platform != 'darwin':
            raise PermissionError('Cleanup is not supported on this platform')
        progress = {'id': key, 'state': 'running', 'done': 0, 'total': len(plan['selected']), 'movedBytes': 0,
                    'stopRequested': False, 'stop': threading.Event()}
        with self.lock:
            while len(self.executions) >= 32:
                self.executions.pop(next(iter(self.executions)))
            self.executions[key] = progress
        before = shutil.disk_usage(self.home).free
        outcomes = []
        # One lsof call for every file replaces one per file (up to 5 s each).
        # If it is unavailable or inconclusive, each file is checked on its own.
        try:
            open_paths = self._open_paths([item['path'] for item, expected in plan['selected'] if item['method'] != 'tool'])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            open_paths = None
        for item, expected in plan['selected']:
            if progress['stop'].is_set():
                outcomes.append({'id': item['id'], 'status': 'skipped', 'sizeBytes': 0, 'message': 'Stopped before this item.'})
                progress['done'] += 1
                continue
            try:
                if item['method'] == 'tool':
                    current = self._tool(expected['id'])
                    if {key: value for key, value in current.items() if key != 'usage'} != {key: value for key, value in expected.items() if key != 'usage'}:
                        raise FileExistsError('Tool cache or executable changed')
                    self._clean_tool(current)
                    outcome = 'cleaned'
                    message = 'Tool completed permanent cache cleanup; bytes were not measured.'
                else:
                    recorded = self._trash(item['path'], expected, item['sizeBytes'], open_paths)
                    outcome = 'moved'
                    message = 'Moved to Trash.' if recorded else UNRECORDED_TRASH_MESSAGE
                outcomes.append({'id': item['id'], 'status': outcome, 'sizeBytes': item['sizeBytes'], 'message': message})
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                outcomes.append({'id': item['id'], 'status': 'skipped' if isinstance(error, (FileExistsError, ValueError)) else 'failed',
                                 'sizeBytes': 0, 'message': str(error) if isinstance(error, CleanupRecoveryError) else 'File changed, was in use, or could not be moved. Scan again.'})
            progress['done'] += 1
            progress['movedBytes'] = sum(entry['sizeBytes'] for entry in outcomes)
        progress['state'] = 'finished'
        return {'id': key, 'items': outcomes, 'movedBytes': sum(item['sizeBytes'] for item in outcomes),
                'measuredFreeSpaceChangeBytes': shutil.disk_usage(self.home).free - before,
                'trashOccupancyIncreaseBytes': sum(item['sizeBytes'] for item in outcomes),
                'reclaimedBytes': 0}

    def execution_status(self, key):
        with self.lock:
            progress = self.executions.get(key)
            if progress is None:
                raise FileNotFoundError('Cleanup is not running')
            return {name: progress[name] for name in ('id', 'state', 'done', 'total', 'movedBytes', 'stopRequested')}

    def stop_execution(self, key):
        with self.lock:
            progress = self.executions.get(key)
            if progress is None:
                raise FileNotFoundError('Cleanup is not running')
            progress['stopRequested'] = True
            progress['stop'].set()
            return {'id': key, 'stopRequested': True}

    def _clean_tool(self, tool):
        if tool['id'] == 'docker':
            self._command(tool['command'])
            return
        cache = tool['cachePath']
        parent_path = os.path.dirname(cache)
        name = os.path.basename(cache)
        stage = '.officekit-cache-' + str(uuid.uuid4())
        stage_path = os.path.join(parent_path, stage)
        with open_parent(cache) as parent_fd:
            value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if identity(value) != tool['scopeIdentity'] or not stat.S_ISDIR(value.st_mode):
                raise FileExistsError('Cache directory changed')
            os.mkdir(stage, mode=0o700, dir_fd=parent_fd)
            stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            moved = False
            try:
                self._trash_move(name, 'cache', parent_fd, stage_fd)
                moved = True
                current = os.stat('cache', dir_fd=stage_fd, follow_symlinks=False)
                if identity(current)[:4] != tool['scopeIdentity'][:4]:
                    raise FileExistsError('Cache changed during staging')
                # The private, same-volume staging directory prevents normal
                # cache writers from sharing the tool cleanup namespace. Verify
                # both held parents before passing its real path to the tool.
                if identity(os.stat(parent_path, follow_symlinks=False))[:2] != identity(os.fstat(parent_fd))[:2] or identity(os.stat(stage_path, follow_symlinks=False))[:2] != identity(os.fstat(stage_fd))[:2]:
                    raise FileExistsError('Cache staging directory changed')
                command = [*tool['command'][:-1], os.path.join(stage_path, 'cache')]
                self._command(command)
            finally:
                try:
                    if moved:
                        try:
                            self._trash_move('cache', name, stage_fd, parent_fd)
                        except FileNotFoundError:
                            # uv may remove the cache root. Recreate only if the
                            # original name remains absent; never overwrite it.
                            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                    os.rmdir(stage, dir_fd=parent_fd)
                except OSError as error:
                    raise CleanupRecoveryError('Cache cleanup could not restore its original location. Preserved data may be at ' + stage_path + '. Review it before removing anything.') from error
                finally:
                    os.close(stage_fd)

    def _trash(self, path, expected, size_bytes=None, open_paths=None):
        """Move a candidate to Trash and record it for restore. Returns False when the record could not be kept."""
        checked_path(path)
        trash = os.path.join(self.home, '.Trash')
        checked_path(trash)
        if not os.path.isdir(trash):
            raise FileNotFoundError('User Trash is unavailable')
        with open_parent(path) as parent_fd, open_parent(os.path.join(trash, 'placeholder')) as trash_fd:
            name = os.path.basename(path)
            value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if identity(value) != expected or value.st_uid != os.getuid() or value.st_nlink != 1:
                raise FileExistsError('Candidate changed')
            if os.fstat(trash_fd).st_dev != value.st_dev or os.fstat(trash_fd).st_uid != os.getuid():
                raise ValueError('Trash is not on the same owned volume')
            if open_paths is None:
                self._ensure_not_in_use(path)
            elif os.path.realpath(path) in open_paths:
                raise ValueError('File is open')
            quarantine = '.officekit-trash-' + str(uuid.uuid4())
            exclusive_rename(name, quarantine, parent_fd)
            try:
                moved = os.stat(quarantine, dir_fd=parent_fd, follow_symlinks=False)
                if identity(moved)[:4] != expected[:4]:
                    raise FileExistsError('Candidate replaced during cleanup')
                # Random UUID destination and descriptor-relative rename preserve
                # parent identity. A symlink is never dereferenced.
                destination = str(uuid.uuid4()) + '-' + name
                # The move and its record share one critical section. Once the move
                # has happened, a record failure must not roll it back: the file is
                # in Trash either way, and the caller reports it as not restorable.
                with self.ledger.lock:
                    self._trash_move(quarantine, destination, parent_fd, trash_fd)
                    return self._remember(path, name, destination, parent_fd, trash_fd,
                                          size_bytes if size_bytes is not None else expected[2])
            except Exception:
                exclusive_rename(quarantine, name, parent_fd)
                raise

    def _remember(self, path, name, destination, parent_fd, trash_fd, size):
        try:
            moved = os.stat(destination, dir_fd=trash_fd, follow_symlinks=False)
            original = os.fstat(parent_fd)
            self.ledger.add(trash_name=destination, trash_identity=(moved.st_dev, moved.st_ino),
                            original_parent_path=os.path.dirname(os.path.abspath(path)),
                            original_parent_identity=(original.st_dev, original.st_ino),
                            original_name=name, size=size)
            return True
        except Exception:
            return False

    @staticmethod
    def _ensure_not_in_use(path):
        executable = '/usr/sbin/lsof'
        if not os.path.isfile(executable):
            raise ValueError('In-use file detection is unavailable')
        # No PID/file contents leave the subprocess. lsof exit 1 with no stderr
        # means no matching open file; missing permission/tool errors fail closed.
        result = subprocess.run([executable, '-t', '--', path], stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, shell=False, timeout=5, check=False,
                                env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C'})
        if result.returncode != 1 or result.stderr:
            raise ValueError('File is open or in-use detection was inconclusive')

    @staticmethod
    def _open_paths(paths, chunk=100):
        """Return the subset of paths that some process has open; fail closed on any doubt."""
        executable = '/usr/sbin/lsof'
        if not os.path.isfile(executable):
            raise ValueError('In-use file detection is unavailable')
        opened = set()
        for start in range(0, len(paths), chunk):
            batch = paths[start:start + chunk]
            result = subprocess.run([executable, '-Fn', '--', *batch], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, shell=False, timeout=30, check=False,
                                    env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C'})
            if result.returncode not in (0, 1) or result.stderr:
                raise ValueError('In-use detection was inconclusive')
            opened.update(os.path.realpath(line[1:]) for line in result.stdout.decode('utf-8', 'surrogateescape').splitlines() if line.startswith('n'))
        return opened

    @staticmethod
    def _trash_move(source, destination, parent_fd, trash_fd):
        library = ctypes.CDLL(None, use_errno=True)
        function = library.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        if function(parent_fd, os.fsencode(source), trash_fd, os.fsencode(destination), 4) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))


storage_cleaner = StorageCleaner()
