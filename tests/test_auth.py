def test_login_and_me(client):
    resp = client.post("/auth/login", json={"email": "admin@local", "password": "admin123"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    token = payload["data"]["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    data = me.json()["data"]
    assert data["email"] == "admin@local"
    assert data["role"] == "ADMIN"
    assert data["user_role"] == "admin"
