import base64

from app.routers.account import MAX_AVATAR_BYTES

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def data_url(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def me(client, user):
    return client.get("/api/auth/me", headers=user).json()


def test_avatar_can_be_set_replaced_and_removed(client, user):
    assert me(client, user)["avatarUrl"] is None

    png = data_url("image/png", PNG)
    r = client.put("/api/account/avatar", json={"dataUrl": png}, headers=user)
    assert r.status_code == 200, r.text
    assert r.json()["avatarUrl"] == png
    assert me(client, user)["avatarUrl"] == png  # stored, not just echoed

    jpeg = data_url("image/jpeg", JPEG)
    client.put("/api/account/avatar", json={"dataUrl": jpeg}, headers=user)
    assert me(client, user)["avatarUrl"] == jpeg

    r = client.delete("/api/account/avatar", headers=user)
    assert r.status_code == 200, r.text
    assert me(client, user)["avatarUrl"] is None


def test_avatar_rejects_what_is_not_a_small_image(client, user):
    def put(url):
        return client.put("/api/account/avatar", json={"dataUrl": url}, headers=user).status_code

    assert put("https://example.com/me.png") == 400            # not a data: URL
    assert put(data_url("image/svg+xml", b"<svg/>")) == 400      # type not allowed
    assert put("data:image/png;base64,@@not-base64@@") == 400
    assert put(data_url("image/png", JPEG)) == 400               # content is not what it claims
    assert put(data_url("image/png", PNG + b"\x00" * MAX_AVATAR_BYTES)) == 413
    assert me(client, user)["avatarUrl"] is None


def test_avatar_requires_login_and_is_per_user(client, user):
    assert client.put("/api/account/avatar", json={"dataUrl": data_url("image/png", PNG)}).status_code == 401
    client.put("/api/account/avatar", json={"dataUrl": data_url("image/png", PNG)}, headers=user)

    other = client.post("/api/auth/register", json={"email": "other-avatar@test.dev", "password": "pw-123456"})
    other_headers = {"Authorization": f"Bearer {other.json()['access']}"}
    assert me(client, other_headers)["avatarUrl"] is None


def test_profile_name_can_be_changed(client, user):
    r = client.patch("/api/account/profile", json={"name": "  Sam Rivers "}, headers=user)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Sam Rivers"
    assert r.json()["avatarInitials"] == "SR"
    assert me(client, user)["name"] == "Sam Rivers"

    assert client.patch("/api/account/profile", json={"name": "x"}, headers=user).status_code == 422
    # The language page sends only a locale; that must not fail or clear the name.
    assert client.patch("/api/account/profile", json={"locale": "nl"}, headers=user).status_code == 200
    assert me(client, user)["name"] == "Sam Rivers"
