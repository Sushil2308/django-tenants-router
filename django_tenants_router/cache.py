"""
TenantCache
===========
Redis-backed cache for tenant DB lookups.
Falls back gracefully if Redis is unavailable.
"""

import json
import logging
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import redis as redis_lib

    _REDIS_LIB_AVAILABLE = True
except ImportError:
    redis_lib = None
    _REDIS_LIB_AVAILABLE = False

_REDIS_CLIENT = None
_REDIS_AVAILABLE = False


def _get_redis():
    global _REDIS_CLIENT, _REDIS_AVAILABLE
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT if _REDIS_AVAILABLE else None

    cfg = getattr(settings, "TENANT_ROUTER_CONFIG", {})
    redis_url = cfg.get("REDIS_URL")
    if not redis_url or not _REDIS_LIB_AVAILABLE:
        return None

    try:
        _REDIS_CLIENT = redis_lib.Redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=1
        )
        _REDIS_CLIENT.ping()
        _REDIS_AVAILABLE = True
        logger.info("TenantCache: Redis connected at %s", redis_url)
    except Exception as exc:
        logger.warning("TenantCache: Redis unavailable – %s. Falling back to DB.", exc)
        _REDIS_AVAILABLE = False

    return _REDIS_CLIENT if _REDIS_AVAILABLE else None


def _ttl() -> int:
    cfg = getattr(settings, "TENANT_ROUTER_CONFIG", {})
    return cfg.get("CACHE_TTL", 300)


def _make_key(suffix: str) -> str:
    prefix = getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("CACHE_KEY_PREFIX", "tenants")
    return f"{prefix}:{suffix}"


# ---------------------------------------------------------------------------
# Public cache API
# ---------------------------------------------------------------------------


def cache_tenant_db(tenant_id: str, db_alias: str) -> None:
    """Store the tenant_id → db_alias mapping in Redis."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(_make_key(f"id:{tenant_id}"), _ttl(), db_alias)
    except Exception as exc:
        logger.debug("TenantCache.set failed: %s", exc)


def get_cached_tenant_db(tenant_id: str) -> Optional[str]:
    """Retrieve a cached db_alias for a tenant_id. Returns None on miss or error."""
    r = _get_redis()
    if r is None:
        return None
    try:
        return r.get(_make_key(f"id:{tenant_id}"))
    except Exception as exc:
        logger.debug("TenantCache.get failed: %s", exc)
        return None


def invalidate_tenant(tenant_id: str) -> None:
    """Evict a tenant from the cache (call after updating TenantDatabaseConfig)."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(_make_key(f"id:{tenant_id}"))
        logger.debug("TenantCache: invalidated tenant %s", tenant_id)
    except Exception as exc:
        logger.debug("TenantCache.delete failed: %s", exc)


def cache_tenant_metadata(tenant_id: str, metadata: dict) -> None:
    """Cache arbitrary tenant metadata (plan, name, etc.)."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(_make_key(f"meta:{tenant_id}"), _ttl(), json.dumps(metadata))
    except Exception as exc:
        logger.debug("TenantCache.set_meta failed: %s", exc)


def get_cached_tenant_metadata(tenant_id: str) -> Optional[dict]:
    """Retrieve cached tenant metadata dict."""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(_make_key(f"meta:{tenant_id}"))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("TenantCache.get_meta failed: %s", exc)
        return None


def flush_all_tenant_cache() -> int:
    """Delete all tenant cache keys. Returns number of keys deleted."""
    r = _get_redis()
    if r is None:
        return 0
    prefix = getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("CACHE_KEY_PREFIX", "tenants")
    try:
        keys = r.keys(f"{prefix}:*")
        if keys:
            return r.delete(*keys)
        return 0
    except Exception as exc:
        logger.debug("TenantCache.flush failed: %s", exc)
        return 0


def cache_health_check() -> dict:
    """Return a dict with Redis health info."""
    r = _get_redis()
    if r is None:
        return {"status": "unavailable", "reason": "Redis not configured or unreachable."}
    try:
        r.ping()
        info = r.info("server")
        return {
            "status": "ok",
            "redis_version": info.get("redis_version"),
            "uptime_seconds": info.get("uptime_in_seconds"),
        }
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
