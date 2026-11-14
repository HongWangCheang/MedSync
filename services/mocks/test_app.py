from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def setup_function() -> None:
    client.post("/admin/reset")


def booking(ref: str, date: str = "2026-11-18") -> dict:
    return {"patient_id": "p1", "department": "cardiology", "date": date, "ref": ref}


def test_duplicate_posts_are_real_side_effects_and_show_up_in_metrics() -> None:
    assert client.post("/hospital/bookings", json=booking("k1")).status_code == 200
    assert client.post("/hospital/bookings", json=booking("k1")).status_code == 200
    metrics = client.get("/metrics/side_effects").json()
    assert metrics["bookings"] == 2
    assert metrics["duplicated"]["bookings"] == {"k1": 2}


def test_lookup_by_ref_and_full_slot() -> None:
    client.post("/admin/slots/2026-11-18", json={"available": 1})
    assert client.post("/hospital/bookings", json=booking("a")).status_code == 200
    full = client.post("/hospital/bookings", json=booking("b"))
    assert full.status_code == 409 and full.json()["detail"] == "slot_full"
    assert len(client.get("/hospital/bookings", params={"ref": "a"}).json()) == 1
    assert client.get("/hospital/bookings", params={"ref": "b"}).json() == []


def test_lost_response_fault_commits_before_the_delay() -> None:
    client.post("/admin/faults", json={"path": "/notify", "delay_s": 0.2, "count": 1})
    client.post("/notify", json={"to": "d", "message": "m", "ref": "r1"})
    assert client.get("/metrics/side_effects").json()["notifications"] == 1
    assert client.post("/admin/faults", json={"path": "/notify", "delay_s": 0.2}).status_code == 200
