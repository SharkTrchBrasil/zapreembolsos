import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_lead_name_step(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_lead_email_valid(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_lead_email_invalid(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_main_menu_choose_gestor(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_main_menu_choose_funcionario(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_employee_onboarding_full_flow(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_company_onboarding_full_flow(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_company_cnpj_invalid(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_onboarding_timeout_reset(db_session, mock_wuzapi):
    pass

@pytest.mark.asyncio
async def test_vincular_valid_code(db_session, mock_wuzapi, sample_company):
    pass

@pytest.mark.asyncio
async def test_vincular_invalid_code(db_session, mock_wuzapi):
    pass
