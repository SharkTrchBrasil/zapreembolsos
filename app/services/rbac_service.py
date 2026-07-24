from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from app.models import User, UserRoleModel, Role, RolePermission, Permission
from app.services.redis_service import redis_service

class RBACService:
    async def has_permission(self, db: AsyncSession, user_phone: str, permission_code: str) -> bool:
        """
        Verifica se o usuário possui a permissão requerida em pelo menos uma de suas roles.
        Usa cache Redis para evitar queries repetidas (TTL 5 minutos).
        """
        # 1. Tenta buscar do cache primeiro
        cached = await redis_service.get_cached_permission(user_phone, permission_code)
        if cached is not None:
            return cached

        # 2. Checa permissões concedidas por UserRole -> Role -> RolePermission -> Permission
        query = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRoleModel, UserRoleModel.role_id == Role.id)
            .where(UserRoleModel.user_phone == user_phone)
            .where(Permission.code == permission_code)
        )
        res = await db.execute(query)
        perm = res.scalars().first()
        has_perm = perm is not None

        # 3. Cacheia o resultado por 5 minutos
        await redis_service.set_cached_permission(user_phone, permission_code, has_perm, ttl_seconds=300)

        return has_perm

    async def get_user_scope_for_permission(self, db: AsyncSession, user_phone: str, permission_code: str) -> list[str]:
        """
        Retorna o escopo (DEPARTMENT ou COMPANY) para uma determinada permissão.
        Se retornar uma lista vazia, o usuário não tem a permissão.
        Se retornar ["COMPANY"], ele tem acesso global.
        Se retornar ["DEPARTMENT_ID_1", "DEPARTMENT_ID_2"], ele tem acesso apenas àqueles departamentos.
        """
        query = (
            select(UserRoleModel)
            .join(Role, Role.id == UserRoleModel.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(UserRoleModel.user_phone == user_phone)
            .where(Permission.code == permission_code)
        )
        res = await db.execute(query)
        user_roles = res.scalars().all()
        
        if not user_roles:
            return []
            
        scopes = []
        for ur in user_roles:
            if ur.scope == "COMPANY":
                return ["COMPANY"] # Acesso global anula acessos restritos
            if ur.scope == "DEPARTMENT" and ur.department_id:
                scopes.append(ur.department_id)
                
        return scopes

rbac_service = RBACService()
