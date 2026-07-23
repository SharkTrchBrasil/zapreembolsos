from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

if settings.REDIS_URL:
    limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
else:
    limiter = Limiter(key_func=get_remote_address)
