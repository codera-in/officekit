from types import SimpleNamespace
from unittest.mock import Mock, patch
import plistlib
import subprocess
import pytest

from officekit.engines.engine_process_manager import (
    ProcessManagerService,
    ProcessManagerError,
    ProcessNotFoundError,
    ProcessAccessDeniedError,
    ProcessSafetyError,
)
import psutil


def make_mock_process(pid, name, cpu_percent=0.0, rss=1024 * 1024, memory_percent=1.0, status="running"):
    proc = Mock()
    proc.info = {
        "pid": pid,
        "name": name,
        "cpu_percent": cpu_percent,
        "memory_info": SimpleNamespace(rss=rss),
        "memory_percent": memory_percent,
        "status": status,
    }
    proc.name.return_value = name
    return proc


def test_list_processes_sorting_and_bounds():
    clock = Mock(return_value=100.0)
    procs = [
        make_mock_process(101, "Safari", cpu_percent=15.2, rss=500 * 1024 * 1024, memory_percent=3.1),
        make_mock_process(102, "Terminal", cpu_percent=2.5, rss=100 * 1024 * 1024, memory_percent=0.6),
        make_mock_process(103, "PythonJob", cpu_percent=85.0, rss=300 * 1024 * 1024, memory_percent=1.8),
    ]
    service = ProcessManagerService(
        process_iter_provider=lambda attrs: procs,
        monotonic_clock=clock,
        wall_clock=lambda: 1700000000.0,
    )

    # Sort by cpu (default)
    result = service.list_processes(limit=10, sort_by="cpu")
    assert result["total_count"] == 3
    assert len(result["processes"]) == 3
    assert result["processes"][0]["name"] == "PythonJob"
    assert result["processes"][0]["cpu_percent"] == 85.0
    assert result["processes"][1]["name"] == "Safari"
    assert result["processes"][2]["name"] == "Terminal"

    # Sort by memory
    result_mem = service.list_processes(limit=10, sort_by="memory")
    assert result_mem["processes"][0]["name"] == "Safari"
    assert result_mem["processes"][0]["memory_bytes"] == 500 * 1024 * 1024
    assert result_mem["processes"][1]["name"] == "PythonJob"


def test_processes_are_grouped_by_application_with_combined_resource_totals(tmp_path):
    bundle = tmp_path / "Example.app"
    contents = bundle / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleDisplayName": "Example Editor"}, stream)
    main = make_mock_process(201, "Example", 10.0, 100 * 1024 * 1024, 1.0)
    helper = make_mock_process(202, "Example Helper (Renderer)", 5.0, 50 * 1024 * 1024, 0.5)
    main.info.update(exe=str(macos / "Example"), ppid=1)
    helper.info.update(exe="/usr/bin/helper", ppid=201)
    service = ProcessManagerService(
        process_iter_provider=lambda attrs: [main, helper],
        gpu_usage_provider=lambda: None,
        wall_clock=lambda: 1700000000.0,
    )

    result = service.list_processes(limit=1)

    assert len(result["processes"]) == 1
    assert result["total_count"] == 2
    assert result["total_applications"] == 1
    app = result["applications"][0]
    assert app["name"] == "Example Editor"
    assert app["process_count"] == 2
    assert app["process_names"] == ["Example", "Example Helper (Renderer)"]
    assert app["cpu_percent"] == 15.0
    assert app["memory_bytes"] == 150 * 1024 * 1024
    assert app["gpu_percent"] is None
    assert "_app_bundle_path" not in app
    assert "_app_bundle_path" not in result["processes"][0]


def test_unresolved_same_name_processes_keep_separate_application_rows():
    service = ProcessManagerService(
        process_iter_provider=lambda attrs: [make_mock_process(401, "python"), make_mock_process(402, "python")],
        gpu_usage_provider=lambda: None,
    )

    result = service.list_processes()

    assert result["total_applications"] == 2
    assert [item["name"] for item in result["applications"]] == ["python", "python"]
    assert [item["process_count"] for item in result["applications"]] == [1, 1]


def test_gpu_process_times_are_sampled_and_sorted_as_percentages():
    current_time = [10.0]
    readings = iter([{301: 1_000_000_000, 302: 2_000_000_000}, {301: 1_400_000_000, 302: 2_200_000_000}])
    processes = [make_mock_process(301, "GPU App"), make_mock_process(302, "Other App")]
    service = ProcessManagerService(
        process_iter_provider=lambda attrs: processes,
        gpu_usage_provider=lambda: next(readings),
        monotonic_clock=lambda: current_time[0],
    )

    service.list_processes()
    current_time[0] = 12.0
    result = service.list_processes(sort_by="gpu")

    assert result["applications"][0]["gpu_percent"] == 20.0
    assert result["applications"][1]["gpu_percent"] == 10.0


def test_gpu_unavailable_and_counter_reset_remain_unavailable():
    current_time = [10.0]
    readings = iter([{301: 2_000}, {301: 1_000}, None])
    process = make_mock_process(301, "GPU App")
    service = ProcessManagerService(
        process_iter_provider=lambda attrs: [process],
        gpu_usage_provider=lambda: next(readings),
        monotonic_clock=lambda: current_time[0],
    )

    first = service.list_processes()
    assert first["processes"][0]["gpu_percent"] is None
    current_time[0] = 12.0
    reset = service.list_processes()
    assert reset["processes"][0]["gpu_percent"] is None
    current_time[0] = 14.0
    unavailable = service.list_processes()
    assert unavailable["processes"][0]["gpu_percent"] is None


def test_gpu_sampler_rejects_provider_failures_invalid_values_and_bad_intervals():
    service = ProcessManagerService(gpu_usage_provider=lambda: {1: 10})
    service._gpu_usage_provider = Mock(side_effect=RuntimeError("provider unavailable"))
    assert service._sample_gpu_percentages(10.0) is None
    assert service._gpu_previous is None

    service._gpu_usage_provider = lambda: "invalid"
    assert service._sample_gpu_percentages(11.0) is None
    service._gpu_usage_provider = lambda: {True: 1, -1: 3, 4_194_305: 5, 4: -1, 5: True, 6: 2**63}
    assert service._sample_gpu_percentages(12.0) == (set(), {})

    service._gpu_usage_provider = lambda: {7: 0}
    assert service._sample_gpu_percentages(13.0) == ({7}, {7: None})
    assert service._sample_gpu_percentages(13.0) == ({7}, {7: None})
    service._gpu_usage_provider = lambda: {7: 10_000_000_000}
    assert service._sample_gpu_percentages(14.0) == ({7}, {7: 100.0})


def test_application_resolution_stops_at_missing_or_repeated_parent():
    resolve = ProcessManagerService._application_for_process
    assert resolve({"pid": 1}, {}, "worker") == ("worker", None)
    chain = {1: {"pid": 1, "ppid": 2}, 2: {"pid": 2, "ppid": 1}}
    assert resolve(chain[1], chain, "worker") == ("worker", None)


def test_macos_gpu_provider_uses_fixed_command_and_bounds_output():
    from officekit.engines.engine_process_manager import macos_gpu_process_times

    completed = SimpleNamespace(returncode=0, stdout='+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 321, test"\n  "accumulatedGPUTime" = 1234\n')
    run = Mock(return_value=completed)
    with patch("officekit.engines.engine_process_manager.sys.platform", "darwin"):
        assert macos_gpu_process_times(run) == {321: 1234}
    run.assert_called_once_with(
        ["/usr/sbin/ioreg", "-r", "-c", "AGXDeviceUserClient", "-d", "0"],
        capture_output=True, text=True, timeout=2.0, check=False,
    )

    completed.stdout = "x" * (4 * 1024 * 1024 + 1)
    with patch("officekit.engines.engine_process_manager.sys.platform", "darwin"):
        assert macos_gpu_process_times(run) is None

    completed.stdout = '+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 321, test"\n  "accumulatedGPUTime" = 0\n'
    with patch("officekit.engines.engine_process_manager.sys.platform", "darwin"):
        assert macos_gpu_process_times(run) == {321: 0}
    completed.stdout = '+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 321, test"\n  "otherField" = 1234\n'
    with patch("officekit.engines.engine_process_manager.sys.platform", "darwin"):
        assert macos_gpu_process_times(run) is None


def test_macos_gpu_provider_fails_closed_for_unsupported_or_malformed_data():
    from officekit.engines.engine_process_manager import macos_gpu_process_times

    with patch("officekit.engines.engine_process_manager.sys.platform", "linux"):
        assert macos_gpu_process_times(Mock(side_effect=AssertionError("must not execute"))) is None
    with patch("officekit.engines.engine_process_manager.sys.platform", "darwin"):
        assert macos_gpu_process_times(Mock(side_effect=OSError("missing ioreg"))) is None
        assert macos_gpu_process_times(Mock(side_effect=subprocess.TimeoutExpired("ioreg", 2))) is None
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=1, stdout=""))) is None
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=0, stdout=None))) is None
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=0, stdout="no clients"))) is None
        invalid = '+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 99999999, test"\n  "accumulatedGPUTime" = 4\n'
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=0, stdout=invalid))) is None
        no_creator = '+-o AGXDeviceUserClient\n  "accumulatedGPUTime" = 4\n'
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=0, stdout=no_creator))) is None
        too_many_digits = "9" * 5000
        invalid_integer = f'+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid {too_many_digits}, test"\n  "accumulatedGPUTime" = 4\n'
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=0, stdout=invalid_integer))) is None
        counter_overflow = f'+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 321, test"\n  "accumulatedGPUTime" = {2**63}\n'
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=0, stdout=counter_overflow))) is None
        mixed_overflow = (
            '+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 321, valid"\n  "accumulatedGPUTime" = 4\n'
            f'+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 322, overflow"\n  "accumulatedGPUTime" = {2**63}\n'
        )
        assert macos_gpu_process_times(Mock(return_value=SimpleNamespace(returncode=0, stdout=mixed_overflow))) is None


def test_macos_gpu_provider_rejects_partial_snapshot_on_counter_overflow():
    from officekit.engines.engine_process_manager import macos_gpu_process_times

    output = (
        '+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 321, valid"\n  "accumulatedGPUTime" = 4\n'
        f'+-o AGXDeviceUserClient\n  "IOUserClientCreator" = "pid 322, overflow"\n  "accumulatedGPUTime" = {2**63}\n'
    )
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=output))
    with patch("officekit.engines.engine_process_manager.sys.platform", "darwin"):
        assert macos_gpu_process_times(run) is None

def test_application_bundle_metadata_is_sanitized(tmp_path):
    from officekit.engines.engine_process_manager import _application_name_from_bundle

    bundle = tmp_path / "Bounded.app"
    contents = bundle / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleDisplayName": "  Useful\nName  "}, stream)
    _application_name_from_bundle.cache_clear()
    assert _application_name_from_bundle(str(bundle)) == "UsefulName"


def test_application_bundle_metadata_fallbacks_and_failures(tmp_path):
    from officekit.engines.engine_process_manager import _application_name_from_bundle

    _application_name_from_bundle.cache_clear()
    assert _application_name_from_bundle(str(tmp_path / "Missing.app")) is None
    oversized = tmp_path / "Oversized.app" / "Contents"
    oversized.mkdir(parents=True)
    (oversized / "Info.plist").write_bytes(b"x" * (512 * 1024 + 1))
    assert _application_name_from_bundle(str(oversized.parent)) is None
    invalid = tmp_path / "Invalid.app" / "Contents"
    invalid.mkdir(parents=True)
    (invalid / "Info.plist").write_bytes(b"not a plist")
    assert _application_name_from_bundle(str(invalid.parent)) is None
    fallback = tmp_path / "Fallback.app" / "Contents"
    fallback.mkdir(parents=True)
    with (fallback / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleDisplayName": "  ", "CFBundleName": "Fallback Name"}, stream)
    assert _application_name_from_bundle(str(fallback.parent)) == "Fallback Name"
    non_mapping = tmp_path / "NonMapping.app" / "Contents"
    non_mapping.mkdir(parents=True)
    with (non_mapping / "Info.plist").open("wb") as stream:
        plistlib.dump(["not", "a", "dictionary"], stream)
    assert _application_name_from_bundle(str(non_mapping.parent)) is None


def test_bundle_resolution_uses_fallback_and_fails_closed_for_invalid_paths():
    from officekit.engines.engine_process_manager import _bundle_for_executable

    assert _bundle_for_executable(None) is None
    assert _bundle_for_executable("/usr/bin/python") is None
    with patch("officekit.engines.engine_process_manager._application_name_from_bundle", return_value="\n"):
        assert _bundle_for_executable("/Applications/Hidden.app/Contents/MacOS/Hidden") is None
    with patch("officekit.engines.engine_process_manager.Path", side_effect=ValueError("bad path")):
        assert _bundle_for_executable("bad") is None


def test_collection_skips_malformed_process_entries_and_normalizes_rss(tmp_path):
    invalid_pid = make_mock_process(1, "invalid")
    invalid_pid.info["pid"] = True
    broken = Mock()
    broken.info = property(Mock(side_effect=psutil.AccessDenied(999)))
    broken_runtime = Mock()
    broken_runtime.info = property(Mock(side_effect=RuntimeError("bad process")))
    bad_rss = make_mock_process(402, "bad rss")
    bad_rss.info["memory_info"] = SimpleNamespace(rss=-100)
    invalid_path = make_mock_process(403, "bad path")
    invalid_path.info.update(exe="/Applications/Path.app/Contents/MacOS/App")
    with patch("officekit.engines.engine_process_manager.Path", side_effect=ValueError("bad path")):
        service = ProcessManagerService(
            process_iter_provider=lambda attrs: [invalid_pid, broken, broken_runtime, bad_rss, invalid_path],
            gpu_usage_provider=lambda: None,
        )
        result = service.list_processes()
    assert len(result["processes"]) == 2
    assert next(item for item in result["processes"] if item["pid"] == 402)["memory_bytes"] == 0


def test_collection_handles_permission_and_unexpected_process_errors():
    class DeniedProcess:
        @property
        def info(self):
            raise psutil.AccessDenied(404)

    class BrokenName:
        def __init__(self, error):
            self.error = error

        def __str__(self):
            raise self.error

    broken_name = make_mock_process(405, "placeholder")
    broken_name.info["name"] = BrokenName(RuntimeError("bad name"))
    vanished_name = make_mock_process(407, "placeholder")
    vanished_name.info["name"] = BrokenName(psutil.NoSuchProcess(407))
    service = ProcessManagerService(
        process_iter_provider=lambda attrs: [DeniedProcess(), broken_name, vanished_name],
        gpu_usage_provider=lambda: None,
    )
    assert service.list_processes()["processes"] == []


def test_collection_handles_primary_path_comparison_failure():
    process = make_mock_process(406, "App")
    process.info["exe"] = "/Applications/App.app/Contents/MacOS/App"
    service = ProcessManagerService(
        process_iter_provider=lambda attrs: [process],
        gpu_usage_provider=lambda: None,
    )
    with patch.object(ProcessManagerService, "_application_for_process", return_value=("App", "/Applications/App.app")), \
            patch("officekit.engines.engine_process_manager.Path", side_effect=ValueError("bad path")):
        assert service.list_processes()["processes"][0]["name"] == "App"


def test_application_ancestry_search_stops_after_nine_levels():
    infos = {pid: {"pid": pid, "ppid": pid + 1} for pid in range(1, 11)}
    assert ProcessManagerService._application_for_process(infos[1], infos, "worker") == ("worker", None)


@pytest.mark.parametrize("failure", [psutil.NoSuchProcess(123), psutil.AccessDenied(123)])
def test_terminate_process_uses_pid_fallback_when_name_is_unavailable(failure):
    proc = Mock()
    proc.name.side_effect = failure
    proc.terminate.return_value = None
    proc.wait.return_value = None
    service = ProcessManagerService(process_lookup_provider=lambda pid: proc)
    result = service.terminate_process(123)
    assert result["name"] == "Process-123"


@pytest.mark.parametrize("failure,expected", [
    (psutil.NoSuchProcess(123), ProcessNotFoundError),
    (psutil.AccessDenied(123), ProcessAccessDeniedError),
])
def test_terminate_process_maps_signal_failures(failure, expected):
    proc = Mock()
    proc.name.return_value = "Worker"
    proc.terminate.side_effect = failure
    service = ProcessManagerService(process_lookup_provider=lambda pid: proc)
    with pytest.raises(expected):
        service.terminate_process(123)


@pytest.mark.parametrize("failure", [psutil.NoSuchProcess(123), psutil.AccessDenied(123)])
def test_terminate_process_maps_kill_failures_after_timeout(failure):
    proc = Mock()
    proc.name.return_value = "Worker"
    proc.wait.side_effect = psutil.TimeoutExpired(1.0)
    proc.kill.side_effect = failure
    service = ProcessManagerService(process_lookup_provider=lambda pid: proc)
    expected = ProcessNotFoundError if isinstance(failure, psutil.NoSuchProcess) else ProcessAccessDeniedError
    with pytest.raises(expected):
        service.terminate_process(123)


def test_terminate_process_ignores_final_wait_error_after_kill():
    proc = Mock()
    proc.name.return_value = "Worker"
    proc.wait.side_effect = [psutil.TimeoutExpired(1.0), RuntimeError("wait failed")]
    service = ProcessManagerService(process_lookup_provider=lambda pid: proc)
    assert service.terminate_process(123)["success"] is True


def test_list_processes_caching():
    clock = Mock(return_value=100.0)
    iter_mock = Mock(return_value=[make_mock_process(101, "App", 10.0)])
    service = ProcessManagerService(
        process_iter_provider=iter_mock,
        monotonic_clock=clock,
    )

    first = service.list_processes()
    assert iter_mock.call_count == 1

    # Within 1.0s cache
    clock.return_value = 100.5
    second = service.list_processes()
    assert iter_mock.call_count == 1
    assert second["processes"] == first["processes"]

    # Past 1.0s cache
    clock.return_value = 101.5
    third = service.list_processes()
    assert iter_mock.call_count == 2


def test_list_processes_invalid_parameters():
    service = ProcessManagerService()
    with pytest.raises(ValueError, match="Limit"):
        service.list_processes(limit=0)
    with pytest.raises(ValueError, match="Limit"):
        service.list_processes(limit=101)
    with pytest.raises(ValueError, match="Limit"):
        service.list_processes(limit=True)
    with pytest.raises(ValueError, match="sort_by"):
        service.list_processes(sort_by="network")


def test_list_processes_skips_failed_or_inaccessible_entries():
    bad_proc = Mock()
    bad_proc.info = property(Mock(side_effect=psutil.NoSuchProcess(999)))
    zombie_proc = Mock()
    zombie_proc.info = property(Mock(side_effect=psutil.ZombieProcess(998)))
    good_proc = make_mock_process(200, "GoodApp", 5.0)

    service = ProcessManagerService(
        process_iter_provider=lambda attrs: [bad_proc, zombie_proc, good_proc],
    )
    result = service.list_processes()
    assert len(result["processes"]) == 1
    assert result["processes"][0]["name"] == "GoodApp"


def test_terminate_process_safety_bounds():
    service = ProcessManagerService()

    # PID 0 and 1 forbidden
    with pytest.raises(ProcessSafetyError, match="outside permitted termination bounds"):
        service.terminate_process(0)
    with pytest.raises(ProcessSafetyError, match="outside permitted termination bounds"):
        service.terminate_process(1)

    # Negative PID
    with pytest.raises(ProcessSafetyError):
        service.terminate_process(-5)

    # Oversized PID
    with pytest.raises(ProcessSafetyError):
        service.terminate_process(10_000_000)

    # Boolean or invalid type
    with pytest.raises(ValueError):
        service.terminate_process(True)
    with pytest.raises(ValueError):
        service.terminate_process("1234")

    # Current process and parent process protected
    with patch("os.getpid", return_value=5555), patch("os.getppid", return_value=4444):
        with pytest.raises(ProcessSafetyError, match="OfficeKit"):
            service.terminate_process(5555)
        with pytest.raises(ProcessSafetyError, match="OfficeKit"):
            service.terminate_process(4444)


def test_terminate_process_normal_termination():
    proc = Mock()
    proc.name.return_value = "TestWorker"
    lookup = Mock(return_value=proc)

    service = ProcessManagerService(process_lookup_provider=lookup)
    result = service.terminate_process(3456, force=False)

    lookup.assert_called_once_with(3456)
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=1.0)
    assert result["success"] is True
    assert result["pid"] == 3456
    assert result["name"] == "TestWorker"


def test_terminate_process_forced_termination():
    proc = Mock()
    proc.name.return_value = "StuckApp"
    lookup = Mock(return_value=proc)

    service = ProcessManagerService(process_lookup_provider=lookup)
    result = service.terminate_process(7890, force=True)

    lookup.assert_called_once_with(7890)
    proc.kill.assert_called_once()
    assert result["success"] is True
    assert result["name"] == "StuckApp"


def test_terminate_process_handles_timeout_escalation():
    proc = Mock()
    proc.name.return_value = "HungProcess"
    proc.wait.side_effect = [psutil.TimeoutExpired(1.0), None]
    lookup = Mock(return_value=proc)

    service = ProcessManagerService(process_lookup_provider=lookup)
    result = service.terminate_process(9999, force=False)

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    assert result["success"] is True


def test_terminate_process_handles_not_found_and_access_denied():
    lookup_not_found = Mock(side_effect=psutil.NoSuchProcess(1234))
    service_nf = ProcessManagerService(process_lookup_provider=lookup_not_found)
    with pytest.raises(ProcessNotFoundError):
        service_nf.terminate_process(1234)

    lookup_denied = Mock(side_effect=psutil.AccessDenied(2345))
    service_ad = ProcessManagerService(process_lookup_provider=lookup_denied)
    with pytest.raises(ProcessAccessDeniedError):
        service_ad.terminate_process(2345)


def test_terminate_process_invalidates_cache():
    clock = Mock(return_value=100.0)
    iter_mock = Mock(return_value=[make_mock_process(3333, "Victim", 5.0)])
    proc_mock = Mock()
    proc_mock.name.return_value = "Victim"

    service = ProcessManagerService(
        process_iter_provider=iter_mock,
        process_lookup_provider=lambda pid: proc_mock,
        monotonic_clock=clock,
    )

    service.list_processes()
    assert iter_mock.call_count == 1

    # Within 1s cache window
    clock.return_value = 100.2
    service.terminate_process(3333)

    # Next list_processes should not use cache because cache was invalidated
    service.list_processes()
    assert iter_mock.call_count == 2
