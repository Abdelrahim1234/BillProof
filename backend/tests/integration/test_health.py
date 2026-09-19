def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"


def test_ready(client):
    resp = client.get("/api/v1/ready")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["db"] == "ok"
    assert body["seeded"] is False
