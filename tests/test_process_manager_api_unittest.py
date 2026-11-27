from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
import pytest
from app import app
from officekit.engines.engine_process_manager import ProcessSafetyError, ProcessNotFoundError, ProcessAccessDeniedError


@pytest.fixture
def client():
    return TestClient(app)


def test_api_get_processes(client):
    with patch("app.process_manager_service.list_processes") as mock_list:
        mock_list.return_value = {
            "processes": [
                {
                    "pid": 1234,
                    "name": "Safari",
                    "cpu_percent": 12.5,
                    "memory_bytes": 1024 * 1024 * 100,
                    "memory_mb": 100.0,
                    "memory_percent": 2.5,
                    "status": "running",
                    "is_killable": True,
                }
            ],
            "applications": [
                {
                    "name": "Safari",
                    "pid": 1234,
                    "process_count": 2,
                    "process_names": ["Safari", "Safari Networking"],
                    "cpu_percent": 12.5,
                    "gpu_percent": None,
                    "memory_bytes": 104857600,
                    "memory_mb": 100.0,
                    "memory_percent": 2.5,
                    "status": "running",
                    "is_killable": True,
                }
            ],
            "total_applications": 1,
            "total_count": 1,
            "captured_at": "2026-10-18T16:00:00Z",
        }
        res = client.get("/api/system/processes?limit=10&sort_by=cpu")
        assert res.status_code == 200
        data = res.json()
        assert len(data["processes"]) == 1
        assert data["processes"][0]["name"] == "Safari"
        assert data["processes"][0]["pid"] == 1234
        assert data["applications"][0]["name"] == "Safari"
        assert data["applications"][0]["process_count"] == 2
        assert data["applications"][0]["gpu_percent"] is None
        assert data["total_applications"] == 1


def test_api_get_processes_accepts_gpu_sort(client):
    with patch("app.process_manager_service.list_processes") as mock_list:
        mock_list.return_value = {"processes": [], "applications": [], "total_applications": 0, "total_count": 0, "captured_at": "2026-10-18T16:00:00Z"}
        res = client.get("/api/system/processes?sort_by=gpu")
        assert res.status_code == 200
        mock_list.assert_called_once_with(limit=30, sort_by="gpu")


@pytest.mark.parametrize("invalid_field,invalid_value", [
    ("name", "A" * 129),
    ("process_names", ["one", "two", "three", "four", "five"]),
    ("process_names", ["A" * 129]),
    ("process_count", 0),
    ("process_count", 100001),
    ("gpu_percent", 100.1),
    ("gpu_percent", -0.1),
    ("gpu_percent", float("nan")),
])
def test_api_rejects_invalid_application_aggregate_responses(invalid_field, invalid_value):
    application = {
        "name": "Safari",
        "pid": 1234,
        "process_count": 1,
        "process_names": ["Safari"],
        "cpu_percent": 12.5,
        "gpu_percent": None,
        "memory_bytes": 1024,
        "memory_mb": 0.0,
        "memory_percent": 0.0,
        "status": "running",
        "is_killable": True,
    }
    application[invalid_field] = invalid_value
    with patch("app.process_manager_service.list_processes", return_value={
        "processes": [], "applications": [application], "total_applications": 1,
        "total_count": 0, "captured_at": "2026-10-18T16:00:00Z",
    }):
        response = TestClient(app, raise_server_exceptions=False).get("/api/system/processes")
    assert response.status_code == 500


def test_api_terminate_process_success(client):
    with patch("app.process_manager_service.terminate_process") as mock_term:
        mock_term.return_value = {
            "success": True,
            "pid": 2345,
            "name": "HeavyWorker",
            "message": "Successfully terminated HeavyWorker (PID 2345).",
        }
        res = client.post("/api/system/processes/terminate", json={"pid": 2345, "force": False})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["pid"] == 2345


def test_api_terminate_process_forbidden_protected(client):
    with patch("app.process_manager_service.terminate_process") as mock_term:
        mock_term.side_effect = ProcessSafetyError("Terminating OfficeKit is not permitted.")
        res = client.post("/api/system/processes/terminate", json={"pid": 9999})
        assert res.status_code == 403
        assert "not permitted" in res.json()["detail"]


def test_api_terminate_process_not_found(client):
    with patch("app.process_manager_service.terminate_process") as mock_term:
        mock_term.side_effect = ProcessNotFoundError("Process 9999 was not found.")
        res = client.post("/api/system/processes/terminate", json={"pid": 9999})
        assert res.status_code == 404
        assert "not found" in res.json()["detail"]


def test_api_terminate_process_access_denied(client):
    with patch("app.process_manager_service.terminate_process") as mock_term:
        mock_term.side_effect = ProcessAccessDeniedError("Permission denied.")
        res = client.post("/api/system/processes/terminate", json={"pid": 9999})
        assert res.status_code == 403
        assert "Permission denied" in res.json()["detail"]


def test_api_terminate_process_validation_error(client):
    res = client.post("/api/system/processes/terminate", json={"pid": 1})
    assert res.status_code == 422
