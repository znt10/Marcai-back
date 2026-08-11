def test_saude_responde_ok(client):
    r = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
