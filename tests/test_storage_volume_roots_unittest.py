from unittest.mock import Mock

from officekit.engines import engine_storage_cleaner as engine
from officekit.engines.engine_storage_cleaner import darwin_scan_roots, apfs_container_of

DATA = '/System/Volumes/Data'
SAME_CONTAINER_MOUNTS = [
    ('/', 'apfs'),
    ('/System/Volumes/VM', 'apfs'),
    ('/System/Volumes/Preboot', 'apfs'),
    (DATA, 'apfs'),
    ('/Volumes/Recovery', 'apfs'),
    ('/private/var/folders/x/X/WRAPPER', 'nullfs'),
]


def containers(mapping):
    return lambda mount: mapping.get(mount)


def test_one_apfs_container_is_counted_once_so_a_256_gb_disk_is_not_shown_as_three_times_that():
    roots = darwin_scan_roots(SAME_CONTAINER_MOUNTS, containers({DATA: 'disk3', '/Volumes/Recovery': 'disk3'}))
    assert roots == [DATA]


def test_a_second_physical_apfs_disk_is_kept_and_a_second_volume_on_it_is_not():
    mounts = SAME_CONTAINER_MOUNTS + [('/Volumes/Backup', 'apfs'), ('/Volumes/Backup 2', 'apfs')]
    found = containers({DATA: 'disk3', '/Volumes/Recovery': 'disk3', '/Volumes/Backup': 'disk8', '/Volumes/Backup 2': 'disk8'})
    assert darwin_scan_roots(mounts, found) == [DATA, '/Volumes/Backup']


def test_an_apfs_volume_with_an_unknown_container_is_skipped_rather_than_risk_double_counting():
    assert darwin_scan_roots([('/Volumes/Mystery', 'apfs')], containers({DATA: 'disk3'})) == [DATA]


def test_external_non_apfs_disks_and_network_or_wrapper_filesystems():
    mounts = [('/Volumes/Stick', 'exfat'), ('/Volumes/Share', 'smbfs'), ('/Volumes/Wrapper', 'nullfs'), ('/Volumes/Stick', 'exfat')]
    assert darwin_scan_roots(mounts, containers({DATA: 'disk3'})) == [DATA, '/Volumes/Stick']


def test_data_volume_is_always_first_even_when_diskutil_cannot_name_its_container():
    assert darwin_scan_roots([('/Volumes/Recovery', 'apfs')], containers({})) == [DATA]


def test_apfs_container_lookup_reads_diskutil_and_fails_closed(monkeypatch):
    import plistlib
    run = Mock(return_value=Mock(stdout=plistlib.dumps({'APFSContainerReference': 'disk3'})))
    monkeypatch.setattr(engine.subprocess, 'run', run)
    assert apfs_container_of(DATA) == 'disk3'
    assert run.call_args.args[0] == ['/usr/sbin/diskutil', 'info', '-plist', DATA]
    monkeypatch.setattr(engine.subprocess, 'run', Mock(return_value=Mock(stdout=plistlib.dumps({'APFSContainerReference': ''}))))
    assert apfs_container_of(DATA) is None
    monkeypatch.setattr(engine.subprocess, 'run', Mock(side_effect=OSError('missing')))
    assert apfs_container_of(DATA) is None
