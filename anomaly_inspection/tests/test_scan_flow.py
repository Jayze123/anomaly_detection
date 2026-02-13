from io import BytesIO


def _user_token(client):
    return client.post("/auth/login", json={"email": "user@local", "password": "user123"}).json()["data"]["access_token"]


def test_scan_creation_and_history(client):
    token = _user_token(client)
    products = client.get("/user/products", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    product_id = products[0]["id"]

    create = client.post(
        "/user/scans",
        data={"product_id": product_id, "notes": "test scan"},
        files=[("files", ("scan.jpg", BytesIO(b"x" * 2048), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    scan_id = create.json()["data"]["id"]

    history = client.get("/user/scans", headers={"Authorization": f"Bearer {token}"})
    assert history.status_code == 200
    rows = history.json()["data"]
    assert any(r["id"] == scan_id for r in rows)

    detail = client.get(f"/user/scans/{scan_id}", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    assert len(detail.json()["data"]["images"]) == 1
