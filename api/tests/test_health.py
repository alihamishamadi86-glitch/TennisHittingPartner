from httpx import AsyncClient


async def test_liveness(api_client: AsyncClient) -> None:
    response = await api_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_checks_database(api_client: AsyncClient) -> None:
    response = await api_client.get("/readyz")
    assert response.status_code == 200
