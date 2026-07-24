import logging
import json
from typing import Optional, Any
from app.config import settings

logger = logging.getLogger("redis_service")

class RedisService:
    """
    Serviço centralizado de Redis para cache, rate limiting por telefone e deduplicação de mensagens.
    Funciona com fallback in-memory caso o Redis não esteja disponível.
    """
    def __init__(self):
        self._client = None
        self._connected = False
        self._fallback_cache: dict = {}  # Fallback in-memory

    async def connect(self):
        """Conecta ao Redis. Chamado no startup do app."""
        if not settings.REDIS_URL:
            logger.warning("REDIS_URL não configurada. Usando cache in-memory (não recomendado para produção).")
            return

        try:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                max_connections=20
            )
            # Testa a conexão
            await self._client.ping()
            self._connected = True
            logger.info("✅ Redis conectado com sucesso!")
        except Exception as e:
            logger.error(f"⚠️ Falha ao conectar ao Redis: {e}. Usando fallback in-memory.")
            self._client = None
            self._connected = False

    async def disconnect(self):
        """Desconecta do Redis. Chamado no shutdown do app."""
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    # ========================================================
    # DEDUPLICAÇÃO DE MENSAGENS DO WEBHOOK
    # Impede processamento duplicado da mesma mensagem
    # ========================================================
    async def is_message_duplicate(self, message_id: str, ttl_seconds: int = 60) -> bool:
        """
        Verifica se uma mensagem já foi processada usando SET NX (atomic).
        Retorna True se for duplicata, False se for nova.
        """
        if not self.is_connected:
            # Fallback in-memory (limitado, mas funcional)
            key = f"msg:{message_id}"
            if key in self._fallback_cache:
                return True
            self._fallback_cache[key] = True
            # Limpar cache antigo (evita memory leak)
            if len(self._fallback_cache) > 10000:
                # Remove os 5000 mais antigos
                keys_to_remove = list(self._fallback_cache.keys())[:5000]
                for k in keys_to_remove:
                    self._fallback_cache.pop(k, None)
            return False

        try:
            key = f"zr:msg:{message_id}"
            # SET NX retorna True se a chave foi criada (nova), False se já existia (duplicata)
            was_set = await self._client.set(key, "1", nx=True, ex=ttl_seconds)
            return not was_set  # Se não foi setada, é duplicata
        except Exception as e:
            logger.error(f"Redis error (is_message_duplicate): {e}")
            return False

    # ========================================================
    # RATE LIMITING POR TELEFONE
    # Limita mensagens por telefone individual (anti-spam/abuse)
    # ========================================================
    async def check_phone_rate_limit(self, phone: str, max_per_minute: int = 15) -> bool:
        """
        Verifica se o telefone está dentro do rate limit.
        Retorna True se PODE processar, False se está no limite.
        """
        if not self.is_connected:
            return True  # Sem Redis, libera (rate limit global do SlowAPI já protege)

        try:
            key = f"zr:rate:{phone}"
            count = await self._client.incr(key)
            if count == 1:
                await self._client.expire(key, 60)
            return count <= max_per_minute
        except Exception as e:
            logger.error(f"Redis error (check_phone_rate_limit): {e}")
            return True  # Em caso de erro, libera

    # ========================================================
    # CACHE DE PERMISSÕES RBAC
    # Evita queries repetidas ao banco para checar permissões
    # ========================================================
    async def get_cached_permission(self, phone: str, permission: str) -> Optional[bool]:
        """Retorna a permissão em cache, ou None se não estiver em cache."""
        if not self.is_connected:
            cache_key = f"perm:{phone}:{permission}"
            val = self._fallback_cache.get(cache_key)
            if val is not None:
                return val == "1"
            return None

        try:
            key = f"zr:perm:{phone}:{permission}"
            val = await self._client.get(key)
            if val is not None:
                return val == "1"
            return None
        except Exception as e:
            logger.error(f"Redis error (get_cached_permission): {e}")
            return None

    async def set_cached_permission(self, phone: str, permission: str, has_perm: bool, ttl_seconds: int = 300):
        """Cacheia o resultado de uma verificação de permissão por 5 minutos."""
        if not self.is_connected:
            cache_key = f"perm:{phone}:{permission}"
            self._fallback_cache[cache_key] = "1" if has_perm else "0"
            return

        try:
            key = f"zr:perm:{phone}:{permission}"
            await self._client.set(key, "1" if has_perm else "0", ex=ttl_seconds)
        except Exception as e:
            logger.error(f"Redis error (set_cached_permission): {e}")

    async def invalidate_user_permissions(self, phone: str):
        """Invalida todas as permissões cacheadas de um usuário (ex: após mudança de role)."""
        if not self.is_connected:
            keys_to_remove = [k for k in self._fallback_cache if k.startswith(f"perm:{phone}:")]
            for k in keys_to_remove:
                self._fallback_cache.pop(k, None)
            return

        try:
            pattern = f"zr:perm:{phone}:*"
            async for key in self._client.scan_iter(match=pattern, count=100):
                await self._client.delete(key)
        except Exception as e:
            logger.error(f"Redis error (invalidate_user_permissions): {e}")

    # ========================================================
    # CACHE GENÉRICO (key-value)
    # ========================================================
    async def get(self, key: str) -> Optional[str]:
        """Busca um valor do cache."""
        if not self.is_connected:
            return self._fallback_cache.get(key)
        try:
            return await self._client.get(f"zr:{key}")
        except Exception as e:
            logger.error(f"Redis error (get): {e}")
            return None

    async def set(self, key: str, value: str, ttl_seconds: int = 300):
        """Salva um valor no cache."""
        if not self.is_connected:
            self._fallback_cache[key] = value
            return
        try:
            await self._client.set(f"zr:{key}", value, ex=ttl_seconds)
        except Exception as e:
            logger.error(f"Redis error (set): {e}")

    async def delete(self, key: str):
        """Remove um valor do cache."""
        if not self.is_connected:
            self._fallback_cache.pop(key, None)
            return
        try:
            await self._client.delete(f"zr:{key}")
        except Exception as e:
            logger.error(f"Redis error (delete): {e}")

redis_service = RedisService()
