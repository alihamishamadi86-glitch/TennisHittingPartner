from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.integrations.storage import LocalStorage
from tests.test_profiles import PNG, upload_photo

MakeClient = Callable[..., Awaitable[AsyncClient]]
BASE = "http://localhost:3000/api"


async def test_upload_attach_and_serve_photo(
    make_client: MakeClient, storage: LocalStorage
) -> None:
    client = await make_client("client")
    object_name = await upload_photo(client)

    attached = await client.put("/me/photo", json={"object_name": object_name})

    assert attached.status_code == 200
    avatar = attached.json()["avatar_url"]
    assert avatar == f"{BASE}/dev-storage/files/{object_name}"
    served = await client.get(avatar.removeprefix(BASE))
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"


async def test_replacing_photo_deletes_previous_upload(
    make_client: MakeClient, storage: LocalStorage
) -> None:
    client = await make_client("client")
    first = await upload_photo(client)
    await client.put("/me/photo", json={"object_name": first})
    second = await upload_photo(client)
    await client.put("/me/photo", json={"object_name": second})

    assert await storage.stat(first) is None
    assert await storage.stat(second) is not None


@pytest.mark.parametrize(
    ("content_type", "size"), [("image/gif", 100), ("image/png", 6 * 1024 * 1024), ("image/png", 0)]
)
async def test_upload_url_rejects_bad_files(
    make_client: MakeClient, storage: LocalStorage, content_type: str, size: int
) -> None:
    client = await make_client("client")
    response = await client.post(
        "/me/photo/upload-url", json={"content_type": content_type, "size": size}
    )
    assert response.status_code == 422


async def test_cannot_attach_another_users_upload(
    make_client: MakeClient, storage: LocalStorage
) -> None:
    owner = await make_client("client")
    thief = await make_client("client")
    object_name = await upload_photo(owner)

    response = await thief.put("/me/photo", json={"object_name": object_name})
    assert response.status_code == 422


async def test_cannot_attach_missing_upload(make_client: MakeClient, storage: LocalStorage) -> None:
    client = await make_client("client")
    me = (await client.get("/me")).json()
    response = await client.put(
        "/me/photo", json={"object_name": f"profile-photos/{me['id']}/nope.png"}
    )
    assert response.status_code == 422


async def test_dev_upload_enforces_signed_content_type_and_token(
    make_client: MakeClient, storage: LocalStorage
) -> None:
    client = await make_client("client")
    target = (
        await client.post("/me/photo/upload-url", json={"content_type": "image/png", "size": 10})
    ).json()
    path = target["upload_url"].removeprefix(BASE)

    wrong_type = await client.put(path, content=PNG, headers={"Content-Type": "text/html"})
    tampered = await client.put(path + "x", content=PNG, headers={"Content-Type": "image/png"})

    assert wrong_type.status_code == 400
    assert tampered.status_code == 403


@pytest.mark.parametrize("name", ["../secret", "a/../../secret", "/etc/passwd", ""])
def test_local_storage_rejects_paths_outside_root(storage: LocalStorage, name: str) -> None:
    assert storage.path_for(name) is None


async def test_dev_files_route_blocks_encoded_traversal(
    storage: LocalStorage, api_client: AsyncClient, tmp_path
) -> None:
    (tmp_path / "secret.txt").write_text("top secret")
    response = await api_client.get("/dev-storage/files/%2E%2E%2Fsecret.txt")
    assert response.status_code == 404
