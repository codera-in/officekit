import os
import stat
import subprocess
import threading
from unittest.mock import Mock
import pytest
from officekit.engines.engine_storage_cleaner import StorageCleaner, ScanRequest, PlanRequest
from officekit.engines import engine_storage_cleaner as engine
from officekit.engines.engine_file_selections import identity


def test_additional_developer_caches_and_python_java_outputs(tmp_path):
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    for relative in ('.gradle/caches', '.m2/repository', '.cargo/registry/cache',
                     '.cargo/registry/src', '.cargo/git/db', 'Library/Developer/Xcode/DerivedData'):
        assert service._classification(str(tmp_path / relative / 'artifact')) == 'caches'
    for relative in ('.cargo/credentials.toml', '.m2/settings.xml', '.gradle/gradle.properties'):
        assert service._classification(str(tmp_path / relative)) != 'caches'
    (tmp_path / 'pyproject.toml').write_text('[project]')
    assert service._generated(str(tmp_path / '.pytest_cache' / 'v' / 'cache' / 'nodeids'))
    assert service._generated(str(tmp_path / '.mypy_cache' / 'data.json'))
    (tmp_path / 'pom.xml').write_text('<project/>')
    assert service._generated(str(tmp_path / 'target' / 'classes' / 'Example.class'))
    assert not service._generated(str(tmp_path / 'src' / 'target' / 'source.java'))


def test_native_authorization_and_strict_dtos(tmp_path):
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path)])
    with pytest.raises(PermissionError):
        service.submit(ScanRequest(), '')
    with pytest.raises(ValueError):
        ScanRequest(olderThanDays=0)
    with pytest.raises(ValueError):
        PlanRequest(scanId='x', candidateIds=[])


def test_scan_candidates_accounting_and_single_use(tmp_path):
    downloads = tmp_path / 'Downloads'
    downloads.mkdir()
    old = downloads / 'old.zip'
    old.write_bytes(b'abc')
    os.utime(old, (1, 1))
    (downloads / 'link').symlink_to(old)
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path)], home=str(tmp_path), platform='linux')
    job = service.submit(ScanRequest(), 'secret')
    service.wait(job['id'])
    result = service.status(job['id'])
    assert result['state'] == 'ready'
    assert result['entriesScanned'] == result['report']['entriesScanned']
    assert result['candidateCount'] == len(result['report']['candidates'])
    assert result['candidateBytes'] >= 3
    report = result['report']
    assert report['logicalBytes'] == 3
    assert len(report['candidates']) == 1
    candidate = report['candidates'][0]
    assert candidate['category'] == 'downloads'
    assert candidate['eligible'] is False
    with pytest.raises(ValueError):
        service.plan(PlanRequest(scanId=job['id'], candidateIds=[candidate['id']]))


def test_cancel_and_unknown_job(tmp_path):
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path)])
    with pytest.raises(FileNotFoundError):
        service.status('unknown')
    job = service.submit(ScanRequest(), 'secret')
    service.cancel(job['id'])
    service.wait(job['id'])
    assert service.status(job['id'])['state'] in {'ready', 'cancelled'}


def completed(service):
    job = service.submit(ScanRequest(), 'secret')
    service.wait(job['id'])
    return service.status(job['id'])


def test_real_trash_review_identity_expiry_and_outcomes(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    (home / '.Trash').mkdir()
    (home / 'Downloads').mkdir()
    old = home / 'Downloads' / 'old.txt'
    old.write_text('old')
    os.utime(old, (1, 1))
    service = StorageCleaner(native_token='secret', roots=[str(home)], home=str(home), platform='darwin')
    monkeypatch.setattr(service, '_tools', lambda: [])
    report = completed(service)
    candidate = report['report']['candidates'][0]
    request = PlanRequest(scanId=report['id'], candidateIds=[candidate['id']])
    plan = service.plan(request)
    with pytest.raises(PermissionError):
        service.execute(plan['id'], '')
    result = service.execute(plan['id'], 'secret')
    assert result['items'][0]['status'] == 'moved'
    assert result['reclaimedBytes'] == 0
    assert result['trashOccupancyIncreaseBytes'] == 3
    assert not old.exists()
    assert next((home / '.Trash').iterdir()).read_text() == 'old'
    with pytest.raises(FileNotFoundError):
        service.execute(plan['id'], 'secret')
    with pytest.raises(ValueError):
        service.plan(PlanRequest(scanId=report['id'], candidateIds=[candidate['id']] * 2))
    plan = service.plan(request)
    service.plans[plan['id']]['expiresAt'] = 0
    with pytest.raises(FileNotFoundError):
        service.execute(plan['id'], 'secret')
    plan = service.plan(request)
    result = service.execute(plan['id'], 'secret')
    assert result['items'][0]['status'] == 'failed'
    plan = service.plan(request)
    monkeypatch.setattr(service, '_trash', Mock(side_effect=FileExistsError()))
    assert service.execute(plan['id'], 'secret')['items'][0]['status'] == 'skipped'
    service.platform = 'linux'
    plan = service.plan(request)
    with pytest.raises(PermissionError):
        service.execute(plan['id'], 'secret')


def test_trash_guards_and_rollback(tmp_path, monkeypatch):
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    file = tmp_path / 'file'
    file.write_text('x')
    expected = identity(file.stat())
    with pytest.raises(FileNotFoundError):
        service._trash(str(file), expected)
    trash = tmp_path / '.Trash'
    trash.mkdir()
    with pytest.raises(FileExistsError):
        service._trash(str(file), (0,) * 6)
    original = service._trash_move
    monkeypatch.setattr(service, '_trash_move', Mock(side_effect=OSError('locked')))
    with pytest.raises(OSError):
        service._trash(str(file), expected)
    assert file.read_text() == 'x'
    monkeypatch.setattr(service, '_trash_move', original)
    hardlink = tmp_path / 'linked'
    os.link(file, hardlink)
    with pytest.raises(FileExistsError):
        service._trash(str(file), identity(file.stat()))
    hardlink.unlink()
    expected = identity(file.stat())
    original_stat = engine.os.fstat
    monkeypatch.setattr(engine.os, 'fstat', lambda descriptor: type('Stat', (), {'st_dev': -1, 'st_uid': os.getuid()})())
    with pytest.raises(ValueError):
        service._trash(str(file), expected)
    monkeypatch.setattr(engine.os, 'fstat', original_stat)


def test_scan_bounds_classification_and_protection(tmp_path, monkeypatch):
    (tmp_path / 'package.json').write_text('{}')
    (tmp_path / 'node_modules').mkdir()
    generated = tmp_path / 'node_modules' / 'generated.js'
    generated.write_text('x')
    os.utime(generated, (1, 1))
    (tmp_path / '.ssh').mkdir()
    (tmp_path / '.ssh' / 'secret').write_text('secret')
    (tmp_path / 'image.jpg').write_text('img')
    (tmp_path / 'app.exe').write_text('app')
    os.link(generated, tmp_path / 'duplicate')
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path)], home=str(tmp_path), platform='darwin')
    monkeypatch.setattr(service, '_tools', lambda: [])
    report = completed(service)['report']
    assert report['logicalBytes'] == 9
    assert all('secret' not in item['path'] for item in report['candidates'])
    assert sum(item['sizeBytes'] for item in report['volumes'][0]['categories']) == report['volumes'][0]['capacityBytes']
    assert service._classification('/file.png') == 'media'
    assert service._classification('/file.docx') == 'documents'
    assert service._classification('/Applications/Test.app/file') == 'applications'
    assert service._classification('/usr/file') == 'system'
    assert service._classification('/other') == 'other'
    assert service._classification(str(tmp_path / 'Library/Caches/cache')) == 'caches'
    assert service._generated(str(generated)) is True
    assert service._generated(str(tmp_path / 'target/source.rs')) is False
    (tmp_path / 'Cargo.toml').write_text('[package]')
    assert service._generated(str(tmp_path / 'target/debug/binary')) is True
    assert service._display_path('/System/Volumes/Data/Users/me') == '/Users/me'
    service.platform = 'win32'
    assert any('AppData' in root for root in service._cache_roots())
    service.max_entries = 1
    assert completed(service)['report']['complete'] is False
    service.max_entries = 100
    service.max_seconds = 0
    assert completed(service)['report']['entriesScanned'] == 0


def test_scan_unavailable_failure_cancel_and_queue(tmp_path, monkeypatch):
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path / 'missing')])
    assert completed(service)['report']['coverage'][0]['state'] == 'inaccessible'
    monkeypatch.setattr(service, '_scan', Mock(side_effect=OSError()))
    assert completed(service)['state'] == 'failed'
    monkeypatch.setattr(service, '_scan', lambda job, request: job['cancel'].set() or {})
    assert completed(service)['state'] == 'cancelled'
    service.jobs['busy'] = {'created': service.clock(), 'state': 'running'}
    with pytest.raises(RuntimeError):
        service.submit(ScanRequest(), 'secret')
    with pytest.raises(ValueError):
        service.plan(PlanRequest(scanId='busy', candidateIds=['x']))


def test_command_bounds_and_failure(tmp_path, monkeypatch):
    service = StorageCleaner(home=str(tmp_path))
    def run(argv, **kwargs):
        assert kwargs['shell'] is False
        assert kwargs['timeout'] == 5
        kwargs['stdout'].write(b' result ')
        return type('Process', (), {'returncode': 0})()
    monkeypatch.setattr(engine.subprocess, 'run', run)
    assert service._command(['/bin/test']) == 'result'
    monkeypatch.setattr(engine.subprocess, 'run', lambda *args, **kwargs: type('Process', (), {'returncode': 1})())
    with pytest.raises(ValueError):
        service._command(['/bin/test'])
    def oversized(*args, **kwargs):
        kwargs['stdout'].write(b'x' * (1024 * 1024 + 1))
        return type('Process', (), {'returncode': 0})()
    monkeypatch.setattr(engine.subprocess, 'run', oversized)
    with pytest.raises(ValueError):
        service._command(['/bin/test'])


def test_package_tools_and_execution(tmp_path, monkeypatch):
    executable = tmp_path / 'tool'
    executable.write_text('fixture')
    executable.chmod(0o700)
    cache = tmp_path / '.npm'
    cache.mkdir()
    service = StorageCleaner(native_token='secret', home=str(tmp_path), roots=[str(tmp_path)], platform='darwin')
    monkeypatch.setattr(engine.shutil, 'which', lambda name, path=None: str(executable))
    command = Mock(return_value=str(cache))
    monkeypatch.setattr(service, '_command', command)
    tool = service._tool('npm')
    assert tool['cleanupSupported'] is True
    assert tool['command'] == [str(executable), 'cache', 'clean', '--force', '--cache', str(cache)]
    assert service._tool('yarn')['cleanupSupported'] is False
    assert service._tool('pnpm')['cleanupSupported'] is False
    for name in ('pip', 'uv'):
        location = tmp_path / '.cache' / name
        location.mkdir(parents=True)
        command.return_value = str(location)
        assert service._tool(name)['cleanupSupported'] is True
    command.return_value = str(tmp_path)
    assert service._tool('npm')['cleanupSupported'] is False
    command.return_value = str(cache)
    monkeypatch.setattr(service, '_tools', lambda: [tool])
    report = completed(service)
    candidate = next(item for item in report['report']['candidates'] if item['method'] == 'tool')
    plan = service.plan(PlanRequest(scanId=report['id'], candidateIds=[candidate['id']]))
    assert service.execute(plan['id'], 'secret')['items'][0]['status'] == 'cleaned'
    assert command.call_args.args[0][:-1] == tool['command'][:-1]
    assert '/.officekit-cache-' in command.call_args.args[0][-1]
    assert command.call_args.args[0][-1].endswith('/cache')
    assert cache.is_dir()
    plan = service.plan(PlanRequest(scanId=report['id'], candidateIds=[candidate['id']]))
    monkeypatch.setattr(service, '_tool', lambda name: {})
    assert service.execute(plan['id'], 'secret')['items'][0]['status'] == 'skipped'


def test_tool_discovery_includes_node_and_docker_gui_install_paths(tmp_path, monkeypatch):
    node_bin = tmp_path / '.nvm' / 'versions' / 'node' / 'v22.0.0' / 'bin'
    node_bin.mkdir(parents=True)
    npm = node_bin / 'npm'
    npm.write_text('#!/bin/sh\nexit 0\n')
    npm.chmod(0o700)
    docker_bin = tmp_path / '.docker' / 'bin'
    docker_bin.mkdir(parents=True)
    docker = docker_bin / 'docker'
    docker.write_text('#!/bin/sh\nexit 0\n')
    docker.chmod(0o700)
    monkeypatch.setenv('PATH', '/usr/bin')
    monkeypatch.setattr(engine.shutil, 'which', lambda name, path=None: next(
        (os.path.join(directory, name) for directory in path.split(os.pathsep)
         if os.path.isfile(os.path.join(directory, name))), None))
    service = StorageCleaner(native_token='secret', home=str(tmp_path), roots=[str(tmp_path)], platform='darwin')
    assert service._tool_executable('npm') == str(npm)
    assert service._tool_executable('docker') == str(docker)
    assert str(node_bin) in service._tool_search_path().split(os.pathsep)
    assert str(docker_bin) in service._tool_search_path().split(os.pathsep)


def test_docker_local_and_remote_contexts(tmp_path, monkeypatch):
    import socket
    executable = tmp_path / 'docker'
    executable.write_text('fixture')
    executable.chmod(0o700)
    connection = socket.socket(socket.AF_UNIX)
    import tempfile
    short = tempfile.TemporaryDirectory(prefix='ok-docker-', dir='/tmp')
    endpoint = engine.Path(short.name).resolve() / 'docker.sock'
    connection.bind(str(endpoint))
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    monkeypatch.setattr(engine.shutil, 'which', lambda name, path=None: str(executable))
    command = Mock(side_effect=['desktop-linux', '[{"Endpoints":{"docker":{"Host":"unix://' + str(endpoint) + '"}}}]', ''])
    monkeypatch.setattr(service, '_command', command)
    assert service._tool('docker')['command'] == [str(executable), '--host', 'unix://' + str(endpoint), 'builder', 'prune', '--force', '--filter', 'until=168h']
    command.side_effect = ['remote', '[{"Endpoints":{"docker":{"Host":"tcp://remote:2375"}}}]']
    assert service._tool('docker')['cleanupSupported'] is False
    command.side_effect = ['bad context']
    assert service._tool('docker')['cleanupSupported'] is False
    command.side_effect = ['local', '[{"Endpoints":{"docker":{"Host":"unix://' + str(executable) + '"}}}]']
    assert service._tool('docker')['cleanupSupported'] is False
    connection.close()
    short.cleanup()


def test_platform_mount_adapters(monkeypatch):
    import ctypes
    import psutil
    disk = lambda mount, kind: type('Disk', (), {'mountpoint': mount, 'fstype': kind})()
    monkeypatch.setattr(psutil, 'disk_partitions', lambda all: [disk('/', 'apfs'), disk('/System/Volumes/Data', 'apfs'), disk('/Volumes/external', 'apfs'), disk('/remote', 'smbfs')])
    monkeypatch.setattr(engine, 'apfs_container_of', lambda mount: 'disk3' if mount.startswith('/System') else 'disk9')
    assert StorageCleaner(platform='darwin')._roots() == ['/System/Volumes/Data', '/Volumes/external']
    assert StorageCleaner(platform='linux')._roots() == ['/', '/System/Volumes/Data', '/Volumes/external']
    monkeypatch.setattr(psutil, 'disk_partitions', lambda all: [])
    assert StorageCleaner(platform='linux')._roots() == ['/']
    kernel = type('Kernel', (), {'GetLogicalDrives': lambda self: 12, 'GetDriveTypeW': lambda self, drive: 3 if drive.startswith('C') else 4})()
    monkeypatch.setattr(ctypes, 'windll', type('Library', (), {'kernel32': kernel})(), raising=False)
    assert StorageCleaner(platform='win32')._roots() == ['C:\\']


def test_scan_permission_entries_and_cancel(tmp_path, monkeypatch):
    os.mkfifo(tmp_path / 'pipe')
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path)], home=str(tmp_path), platform='linux')
    monkeypatch.setattr(service, '_tools', lambda: [])
    assert completed(service)['report']['logicalBytes'] == 0
    original = engine.os.scandir
    monkeypatch.setattr(engine.os, 'scandir', Mock(side_effect=PermissionError()))
    assert completed(service)['report']['coverage'][0]['inaccessibleCount'] == 1
    monkeypatch.setattr(engine.os, 'scandir', original)
    class Child:
        name = 'file'
        def stat(self, **kwargs):
            raise PermissionError()
    class Iterator:
        def __enter__(self): return iter([Child()])
        def __exit__(self, *args): return False
    monkeypatch.setattr(engine.os, 'scandir', lambda path: Iterator())
    assert completed(service)['report']['coverage'][0]['inaccessibleCount'] == 1
    class CancelIterator:
        def __enter__(self):
            for job in service.jobs.values():
                job['cancel'].set()
            return iter([Child()])
        def __exit__(self, *args): return False
    monkeypatch.setattr(engine.os, 'scandir', lambda path: CancelIterator())
    assert completed(service)['state'] == 'cancelled'


def test_plan_overlap_limits_and_tools_failure(tmp_path, monkeypatch):
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path)], home=str(tmp_path), platform='darwin')
    monkeypatch.setattr(service, '_tools', lambda: [])
    report = completed(service)
    base = {'id': 'tool', 'path': str(tmp_path / '.npm'), 'eligible': True, 'method': 'tool', 'sizeBytes': 0}
    file = {**base, 'id': 'file', 'method': 'trash', 'path': str(tmp_path / '.npm/file')}
    service.jobs[report['id']]['candidates'] = {'tool': (base, {}), 'file': (file, ())}
    with pytest.raises(ValueError):
        service.plan(PlanRequest(scanId=report['id'], candidateIds=['tool', 'file']))
    service.plans = {str(index): {'expiresAt': service.clock() + 30} for index in range(32)}
    with pytest.raises(RuntimeError):
        service.plan(PlanRequest(scanId=report['id'], candidateIds=['file']))
    monkeypatch.delattr(service, '_tools')
    monkeypatch.setattr(service, '_tool', Mock(side_effect=ValueError()))
    assert all(tool['cleanupSupported'] is False for tool in service._tools())
    executable = tmp_path / 'executable'
    executable.write_text('x')
    executable.chmod(0o777)
    monkeypatch.delattr(service, '_tool')
    monkeypatch.setattr(engine.shutil, 'which', lambda name, path=None: str(executable))
    assert service._tool('npm')['cleanupSupported'] is False


def test_trash_replacement_after_quarantine(tmp_path, monkeypatch):
    file = tmp_path / 'file'
    file.write_text('original')
    (tmp_path / '.Trash').mkdir()
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    expected = identity(file.stat())
    original = engine.exclusive_rename
    def swapped(source, destination, fd):
        original(source, destination, fd)
        if destination.startswith('.officekit-trash-'):
            os.unlink(destination, dir_fd=fd)
            descriptor = os.open(destination, os.O_CREAT | os.O_WRONLY, dir_fd=fd)
            os.write(descriptor, b'replacement')
            os.close(descriptor)
    monkeypatch.setattr(engine, 'exclusive_rename', swapped)
    with pytest.raises(FileExistsError):
        service._trash(str(file), expected)
    assert file.read_text() == 'replacement'


def test_tool_directory_replacement_and_atomic_destination_collision(tmp_path, monkeypatch):
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    cache = tmp_path / 'cache'
    cache.mkdir()
    tool = {'id': 'npm', 'cachePath': str(cache), 'scopeIdentity': (0,) * 6, 'command': ['/bin/npm', '--cache', str(cache)]}
    with pytest.raises(FileExistsError):
        service._clean_tool(tool)
    command = Mock(return_value='done')
    monkeypatch.setattr(service, '_command', command)
    service._clean_tool({'id': 'docker', 'command': ['/bin/docker', 'builder', 'prune']})
    command.assert_called_once_with(['/bin/docker', 'builder', 'prune'])
    source = tmp_path / 'source'
    destination = tmp_path / 'destination'
    source.write_text('source')
    destination.write_text('destination')
    with engine.open_parent(str(source)) as descriptor:
        with pytest.raises(OSError):
            service._trash_move('source', 'destination', descriptor, descriptor)
    assert source.read_text() == 'source'
    assert destination.read_text() == 'destination'


def test_largest_entries_recursive_counts_and_top100(tmp_path, monkeypatch):
    service = StorageCleaner(native_token='secret', roots=[str(tmp_path)], home=str(tmp_path), platform='linux')
    parent = tmp_path / 'folder'
    child = parent / 'nested'
    child.mkdir(parents=True)
    for index in range(105):
        (child / f'file-{index:03}.txt').write_bytes(b'x' * index)
    report = completed(service)['report']
    assert len(report['largestFiles']) == 100
    assert report['largestFiles'][0]['sizeBytes'] == 104
    assert report['largestFiles'][-1]['sizeBytes'] == 5
    root = next(entry for entry in report['largestFolders'] if entry['path'] == str(tmp_path))
    nested = next(entry for entry in report['largestFolders'] if entry['path'] == str(child))
    assert root['fileCount'] == nested['fileCount'] == 105
    assert root['sizeBytes'] == nested['sizeBytes'] == sum(range(105))
    assert nested['partial'] is True
    assert all(entry['partial'] is False for entry in report['largestFiles'])
    assert all(entry['modifiedAt'] > 0 for entry in report['largestFiles'])
    folders = {}
    original = engine.os.stat
    def unavailable(path, **kwargs):
        if path == str(parent):
            raise PermissionError()
        return original(path, **kwargs)
    monkeypatch.setattr(engine.os, 'stat', unavailable)
    service._folder_totals(str(child / 'file'), str(tmp_path), 4, folders)
    assert str(parent) not in folders
    assert folders[str(child)]['sizeBytes'] == 4
    capped = {f'/already/{index}': {} for index in range(10000)}
    service._folder_totals(str(child / 'file'), str(tmp_path), 4, capped)
    assert len(capped) == 10000


def test_in_use_guard_fails_closed_and_fixed_command(tmp_path, monkeypatch):
    path = str(tmp_path / 'old-file')
    result = type('Result', (), {'returncode': 1, 'stderr': b''})()
    run = Mock(return_value=result)
    monkeypatch.setattr(engine.subprocess, 'run', run)
    monkeypatch.setattr(engine.os.path, 'isfile', lambda path: True)
    StorageCleaner._ensure_not_in_use(path)
    run.assert_called_once_with(['/usr/sbin/lsof', '-t', '--', path], stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, shell=False, timeout=5, check=False,
                                env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C'})
    result.returncode = 0
    with pytest.raises(ValueError):
        StorageCleaner._ensure_not_in_use(path)
    result.returncode = 1
    result.stderr = b'permission warning'
    with pytest.raises(ValueError):
        StorageCleaner._ensure_not_in_use(path)
    run.side_effect = subprocess.TimeoutExpired('lsof', 5)
    with pytest.raises(subprocess.TimeoutExpired):
        StorageCleaner._ensure_not_in_use(path)
    monkeypatch.setattr(engine.os.path, 'isfile', lambda path: False)
    with pytest.raises(ValueError):
        StorageCleaner._ensure_not_in_use(path)


def test_tool_staging_success_failure_recreated_and_removed_cache(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    cache.mkdir()
    file = cache / 'fixture'
    file.write_text('fixture')
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    def tool():
        return {'id': 'uv', 'cachePath': str(cache), 'scopeIdentity': identity(cache.stat()),
                'command': ['/bin/uv', 'cache', 'clean', '--cache-dir', str(cache)]}
    def clean(argv):
        staged = engine.Path(argv[-1])
        assert staged.parent.stat().st_mode & 0o077 == 0
        assert not cache.exists()
        (staged / 'fixture').unlink()
        staged.rmdir()
        return ''
    monkeypatch.setattr(service, '_command', clean)
    service._clean_tool(tool())
    assert cache.is_dir()
    assert not list(tmp_path.glob('.officekit-cache-*'))
    file.write_text('preserve')
    monkeypatch.setattr(service, '_command', Mock(side_effect=ValueError('tool failed')))
    with pytest.raises(ValueError):
        service._clean_tool(tool())
    assert file.read_text() == 'preserve'
    def concurrent(argv):
        cache.mkdir()
        (cache / 'new-writer').write_text('new')
        return ''
    monkeypatch.setattr(service, '_command', concurrent)
    with pytest.raises(engine.CleanupRecoveryError, match='Preserved data may be at'):
        service._clean_tool(tool())
    assert (cache / 'new-writer').read_text() == 'new'
    staged = next(tmp_path.glob('.officekit-cache-*')) / 'cache'
    assert (staged / 'fixture').read_text() == 'preserve'


def test_tool_staging_identity_and_pip3_fallback(tmp_path, monkeypatch):
    executable = tmp_path / 'pip3'
    executable.write_text('fixture')
    executable.chmod(0o700)
    cache = tmp_path / '.cache' / 'pip'
    cache.mkdir(parents=True)
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    monkeypatch.setattr(engine.shutil, 'which', lambda name, path=None: str(executable) if name == 'pip3' else None)
    monkeypatch.setattr(service, '_command', Mock(return_value=str(cache)))
    assert service._tool('pip')['available'] is True
    assert service._tool('pip')['command'][0] == str(executable)
    tool = {'id': 'pip', 'cachePath': str(cache), 'scopeIdentity': identity(cache.stat()),
            'command': [str(executable), 'cache', 'purge', '--cache-dir', str(cache)]}
    move = service._trash_move
    def replace(source, destination, source_fd, target_fd):
        move(source, destination, source_fd, target_fd)
        if source == 'pip':
            descriptor = os.open('cache', os.O_RDONLY | os.O_DIRECTORY, dir_fd=target_fd)
            os.mkdir('changed', dir_fd=descriptor)
            os.close(descriptor)
    monkeypatch.setattr(service, '_trash_move', replace)
    with pytest.raises(FileExistsError):
        service._clean_tool(tool)
    assert (cache / 'changed').is_dir()
    monkeypatch.setattr(service, '_trash_move', move)
    tool['scopeIdentity'] = identity(cache.stat())
    original_stat = engine.os.stat
    def replacement_stat(path, **kwargs):
        value = original_stat(path, **kwargs)
        if str(path).startswith(str(cache.parent / '.officekit-cache-')):
            return type('Stat', (), {'st_dev': -1, 'st_ino': -1, 'st_size': 0, 'st_mtime_ns': 0,
                                    'st_ctime_ns': 0})()
        return value
    monkeypatch.setattr(engine.os, 'stat', replacement_stat)
    with pytest.raises(FileExistsError):
        service._clean_tool(tool)
    assert cache.is_dir()


@pytest.mark.parametrize('text,expected', [('2.5GB', 2500000000), ('4 KiB', 4096),
                                          ('700MB (64%)', 700000000), ('0B', 0),
                                          ('unknown', None), ('-1GB', None), ('1e99GB', None)])
def test_docker_usage_sizes(text, expected):
    assert StorageCleaner._docker_bytes(text) == expected


def test_docker_usage_read_only_and_unknown_values(tmp_path, monkeypatch):
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    output = '\n'.join([
        '{"Type":"Images","TotalCount":5,"Active":2,"Size":"2.5GB","Reclaimable":"700MB (28%)"}',
        '{"Type":"Local Volumes","TotalCount":"3","Active":"1","Size":"1GiB","Reclaimable":"unknown"}',
        '{"Type":"Build Cache","TotalCount":4,"Active":0,"Size":"50MB","Reclaimable":"30MB"}',
        '{"Type":"Containers","TotalCount":"unknown","Active":-1,"Size":"0B","Reclaimable":"0B"}',
        '{"Type":"Other thing","Size":"invalid"}',
    ])
    command = Mock(return_value=output)
    monkeypatch.setattr(service, '_command', command)
    result = service._docker_usage('/bin/docker', 'unix:///fixture.sock')
    command.assert_called_once_with(['/bin/docker', '--host', 'unix:///fixture.sock', 'system', 'df', '--format', '{{json .}}'])
    assert result[0] == {'id': 'images', 'label': 'Images', 'totalCount': 5, 'activeCount': 2,
                         'sizeBytes': 2500000000, 'reclaimableBytes': 700000000}
    assert result[1]['id'] == 'volumes'
    assert result[1]['sizeBytes'] == 1073741824
    assert result[1]['reclaimableBytes'] is None
    assert result[2]['id'] == 'build-cache'
    assert result[3]['totalCount'] is None
    assert result[3]['activeCount'] is None
    assert result[4]['id'] == 'other'
    command.return_value = '[]'
    with pytest.raises(ValueError):
        service._docker_usage('/bin/docker', 'unix:///fixture.sock')
    command.return_value = '\n'.join(['{}'] * 17)
    with pytest.raises(ValueError):
        service._docker_usage('/bin/docker', 'unix:///fixture.sock')
    assert service._docker_bytes(None) is None
    assert service._docker_bytes('9999999999999999999EB') is None
    assert service._docker_count('9999999999999999999') is None


def test_codex_claude_roots_and_downloads_node_modules_filter(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    downloads = home / 'Downloads'
    downloads.mkdir()
    # Runner in Downloads with node_modules
    runner_modules = downloads / 'actions-runner' / 'node_modules' / 'tar'
    runner_modules.mkdir(parents=True)
    (runner_modules / 'index.js').write_text('// tar index')
    # Real download file in Downloads
    installer = downloads / 'Claude.dmg'
    installer.write_bytes(b'x' * 1024)

    # Claude and Codex folders in home
    claude_cache = home / '.claude' / 'cache'
    claude_cache.mkdir(parents=True)
    claude_file = claude_cache / 'session_cache.json'
    claude_file.write_text('{"cache": true}')

    codex_tmp = home / '.codex' / '.tmp'
    codex_tmp.mkdir(parents=True)
    codex_file = codex_tmp / 'git_workdir.diff'
    codex_file.write_text('diff --git')

    service = StorageCleaner(native_token='secret', home=str(home), roots=[str(home)], platform='darwin', clock=lambda: 2000000000)
    # Ensure roots contain claude and codex
    cache_roots = service._cache_roots()
    assert any('.claude' in r for r in cache_roots)
    assert any('.codex' in r for r in cache_roots)
    assert any('com.openai.codex' in r for r in cache_roots)

    # Age 1 day so installer is considered old download
    os.utime(str(installer), (1000000000, 1000000000))
    os.utime(str(claude_file), (1000000000, 1000000000))
    os.utime(str(codex_file), (1000000000, 1000000000))
    os.utime(str(runner_modules / 'index.js'), (1000000000, 1000000000))

    result = completed(service)
    candidates = result['report']['candidates']
    candidate_paths = [c['path'] for c in candidates]

    # Installer should be candidate
    assert str(installer) in candidate_paths
    # Claude and Codex cache files should be candidates with appropriate reasons
    assert str(claude_file) in candidate_paths
    claude_cand = next(c for c in candidates if c['path'] == str(claude_file))
    assert 'Claude' in claude_cand['reason']

    assert str(codex_file) in candidate_paths
    codex_cand = next(c for c in candidates if c['path'] == str(codex_file))
    assert 'Codex' in codex_cand['reason']

    # Files inside Downloads/actions-runner/node_modules must NOT be candidates
    assert str(runner_modules / 'index.js') not in candidate_paths


def test_antigravity_gemini_cursor_windsurf_history_is_reviewed_and_work_is_never_offered(tmp_path):
    home = tmp_path / 'home'
    offered = {
        '.gemini/antigravity/brain/session/plan.md': 'Antigravity',
        '.gemini/antigravity/conversations/chat.pb': 'Antigravity',
        '.gemini/antigravity/cache/blob': 'Antigravity',
        '.gemini/antigravity/crashes/crash.dmp': 'Antigravity',
        '.gemini/antigravity/log/agent.log': 'Antigravity',
        '.gemini/antigravity/scratch/note.txt': 'Antigravity',
        '.gemini/tmp/abc123/shell.log': 'Gemini',
        '.cursor/projects/p/history.json': 'Cursor',
        '.windsurf/cache/blob': 'Windsurf',
        'Library/Application Support/Antigravity/Cache/Cache_Data/f_1': 'Antigravity',
        'Library/Application Support/Antigravity/CachedData/abc/js': 'Antigravity',
        'Library/Application Support/Cursor/Cache/Cache_Data/f_1': 'Cursor',
        'Library/Application Support/Windsurf/CachedData/abc/js': 'Windsurf',
    }
    never = [
        '.gemini/oauth_creds.json',
        '.gemini/settings.json',
        '.gemini/google_account_id',
        '.gemini/antigravity/worktrees/repo/src/main.py',
        '.gemini/antigravity/knowledge/notes.md',
        '.gemini/antigravity/skills/s/SKILL.md',
        '.gemini/antigravity/installation_id',
        '.cursor/mcp.json',
        'Library/Application Support/Antigravity/User/settings.json',
    ]
    for relative in list(offered) + never:
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('x')
        os.utime(str(target), (1000000000, 1000000000))
    service = StorageCleaner(native_token='secret', home=str(home), roots=[str(home)], platform='darwin', clock=lambda: 2000000000)
    candidates = {c['path']: c for c in completed(service)['report']['candidates']}
    for relative, tool in offered.items():
        found = candidates.get(str(home / relative))
        assert found is not None, relative
        assert tool in found['reason'], (relative, found['reason'])
    for relative in never:
        assert str(home / relative) not in candidates, relative


def test_open_paths_batches_one_call_and_fails_closed(tmp_path, monkeypatch):
    first, second = str(tmp_path / 'a'), str(tmp_path / 'b')
    result = type('Result', (), {'returncode': 0, 'stderr': b'', 'stdout': f'p1\nf3\nn{first}\n'.encode()})()
    run = Mock(return_value=result)
    monkeypatch.setattr(engine.subprocess, 'run', run)
    monkeypatch.setattr(engine.os.path, 'isfile', lambda path: True)
    assert StorageCleaner._open_paths([first, second]) == {os.path.realpath(first)}
    assert run.call_count == 1
    result.returncode = 2
    with pytest.raises(ValueError):
        StorageCleaner._open_paths([first])
    result.returncode = 1
    result.stderr = b'warning'
    with pytest.raises(ValueError):
        StorageCleaner._open_paths([first])
    monkeypatch.setattr(engine.os.path, 'isfile', lambda path: False)
    with pytest.raises(ValueError):
        StorageCleaner._open_paths([first])

