def test_calibration_status_returns_snapshot(client):
    r = client.get("/api/admin/calibration")
    assert r.status_code == 200
    body = r.json()
    for key in ("active", "section_weights_table", "section_log_stats", "history"):
        assert key in body, f"missing {key}"


def test_calibration_run_synchronous(client, mocker):
    # run_calibration_cycle is imported function-locally -> patch at source.
    mocker.patch(
        "app.core.auto_calibrator.run_calibration_cycle",
        return_value={"status": "ok", "updated": False},
    )
    r = client.post("/api/admin/calibration/run")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_calibration_run_updated_true(client, mocker):
    mocker.patch(
        "app.core.auto_calibrator.run_calibration_cycle",
        return_value={"status": "ok", "updated": True},
    )
    r = client.post("/api/admin/calibration/run")
    assert r.status_code == 200
    assert r.json()["updated"] is True


def test_calibration_run_error_500(client, mocker):
    mocker.patch(
        "app.core.auto_calibrator.run_calibration_cycle",
        side_effect=RuntimeError("boom"),
    )
    r = client.post("/api/admin/calibration/run")
    assert r.status_code == 500


def test_dashboard_serves_html(client):
    r = client.get("/api/admin/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Calibration Dashboard" in r.text
