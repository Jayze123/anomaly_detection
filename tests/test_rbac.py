def _token(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password}).json()["data"]["access_token"]


def test_admin_endpoint_forbidden_for_user(client):
    token = _token(client, "user@local", "user123")
    resp = client.get("/admin/factories", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_user_endpoint_forbidden_for_admin(client):
    token = _token(client, "admin@local", "admin123")
    resp = client.get("/user/products", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_invalid_token_rejected(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer broken"})
    assert resp.status_code == 401
