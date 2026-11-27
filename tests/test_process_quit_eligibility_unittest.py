from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from officekit.engines.engine_process_manager import ProcessManagerService, ProcessSafetyError

USER = 501


def make_process(pid, name, uid=USER):
    proc = Mock()
    proc.info = {
        "pid": pid,
        "name": name,
        "cpu_percent": 1.0,
        "memory_info": SimpleNamespace(rss=1024 * 1024),
        "memory_percent": 1.0,
        "status": "running",
        "uids": SimpleNamespace(real=uid, effective=uid, saved=uid),
    }
    return proc


def listing(processes, protected=frozenset({900})):
    service = ProcessManagerService(process_iter_provider=lambda attrs: processes,
                                    monotonic_clock=lambda: 1.0, wall_clock=lambda: 1.0)
    with patch("officekit.engines.engine_process_manager.os.getuid", return_value=USER), \
            patch.object(ProcessManagerService, "_protected_pids", staticmethod(lambda: protected)):
        rows = service._collect_processes()
    return {row["pid"]: row["is_killable"] for row in rows}


def test_only_the_signed_in_users_own_processes_can_be_quit():
    killable = listing([
        make_process(300, "Google Chrome Helper"),
        make_process(301, "WindowServer", uid=88),
        make_process(302, "launchd", uid=0),
        make_process(303, "mobileassetd", uid=501),
    ])
    assert killable == {300: True, 301: False, 302: False, 303: True}


def test_officekit_its_launcher_and_its_helpers_are_never_offered_quit():
    killable = listing([
        make_process(900, "Tauri"),
        make_process(901, "OfficeKit"),
        make_process(902, "officekit-api"),
        make_process(903, "Superset Helper"),
    ], protected=frozenset({900, 902}))
    assert killable == {900: False, 901: False, 902: False, 903: True}


def test_pids_below_two_are_never_killable_even_for_the_user():
    assert listing([make_process(1, "init", uid=USER), make_process(0, "kernel", uid=USER)]) == {1: False, 0: False}


def test_terminate_refuses_protected_pids_before_any_lookup():
    lookup = Mock()
    service = ProcessManagerService(process_lookup_provider=lookup)
    with patch.object(ProcessManagerService, "_protected_pids", staticmethod(lambda: frozenset({4242}))):
        with pytest.raises(ProcessSafetyError):
            service.terminate_process(4242)
    lookup.assert_not_called()
