import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_request_code_without_redis():
    """Testa que retorna erro quando Redis não está configurado (500) ou telefone inválido (404)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/auth/request-code", json={"phone": "123"})
        # Sem Redis configurado = 500, com Redis mas sem user = 404
        assert response.status_code in [404, 500]

@pytest.mark.asyncio
async def test_health_check():
    """Testa se a API inteira ta rodando"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_dashboard_requires_auth():
    """Testa que o dashboard rejeita requisições sem token JWT"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/dashboard/stats")
        assert response.status_code == 403  # Forbidden (no Bearer token)

@pytest.mark.asyncio
async def test_admin_page_served():
    """Testa se a página HTML do admin é servida corretamente"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/admin")
        assert response.status_code == 200
        assert "ZapReembolso" in response.text
