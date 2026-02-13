from io import BytesIO


def _admin_token(client):
    return client.post("/auth/login", json={"email": "admin@local", "password": "admin123"}).json()["data"]["access_token"]


def test_status_images_limit(client):
    token = _admin_token(client)
    products = client.get("/admin/products", headers={"Authorization": f"Bearer {token}"}).json()["data"]["items"]
    product_id = products[0]["id"]

    created = client.post(
        f"/admin/products/{product_id}/statuses",
        json={"status": "LIMIT_TEST", "status_description": "limit"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201
    status_id = created.json()["data"]["id"]

    for i in range(4):
        resp = client.post(
            f"/admin/statuses/{status_id}/images",
            files={"file": (f"{i}.jpg", BytesIO(b"x" * 1024), "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    fifth = client.post(
        f"/admin/statuses/{status_id}/images",
        files={"file": ("5.jpg", BytesIO(b"x" * 1024), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert fifth.status_code == 400
    assert "Maximum of 4 images" in fifth.text
