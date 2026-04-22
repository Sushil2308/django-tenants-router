"""
Tests: Cache
============
Tests for the Redis cache layer with mocked Redis client.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings


SETTINGS_WITH_REDIS = {
    "TENANT_ROUTER_CONFIG": {
        "ROOT_DB": "default",
        "REDIS_URL": "redis://localhost:6379/0",
        "CACHE_TTL": 300,
        "CACHE_KEY_PREFIX": "tenants",
    }
}

SETTINGS_NO_REDIS = {
    "TENANT_ROUTER_CONFIG": {
        "ROOT_DB": "default",
    }
}


def _reset_cache_module():
    """Reset module-level Redis state between tests."""
    import django_tenants_router.cache as cache_mod
    cache_mod._REDIS_CLIENT = None
    cache_mod._REDIS_AVAILABLE = False


def _inject_mock_client(mock_client):
    """Directly inject a mock Redis client into the cache module."""
    import django_tenants_router.cache as cache_mod
    cache_mod._REDIS_CLIENT = mock_client
    cache_mod._REDIS_AVAILABLE = True


class CacheWithRedisTest(TestCase):
    def setUp(self):
        _reset_cache_module()

    def tearDown(self):
        _reset_cache_module()

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_cache_tenant_db(self):
        mock_client = MagicMock()
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import cache_tenant_db
        cache_tenant_db("uuid-1234", "tenant_acme")
        mock_client.setex.assert_called_once_with("tenants:id:uuid-1234", 300, "tenant_acme")

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_get_cached_tenant_db(self):
        mock_client = MagicMock()
        mock_client.get.return_value = "tenant_acme"
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import get_cached_tenant_db
        result = get_cached_tenant_db("uuid-1234")
        self.assertEqual(result, "tenant_acme")
        mock_client.get.assert_called_once_with("tenants:id:uuid-1234")

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_get_returns_none_on_miss(self):
        mock_client = MagicMock()
        mock_client.get.return_value = None
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import get_cached_tenant_db
        result = get_cached_tenant_db("ghost-id")
        self.assertIsNone(result)

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_invalidate_tenant(self):
        mock_client = MagicMock()
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import invalidate_tenant
        invalidate_tenant("uuid-1234")
        mock_client.delete.assert_called_once_with("tenants:id:uuid-1234")

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_cache_and_get_metadata(self):
        meta = {"plan": "pro", "name": "ACME"}
        mock_client = MagicMock()
        mock_client.get.return_value = json.dumps(meta)
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import cache_tenant_metadata, get_cached_tenant_metadata
        cache_tenant_metadata("uuid-1234", meta)
        result = get_cached_tenant_metadata("uuid-1234")
        self.assertEqual(result, meta)

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_flush_all_tenant_cache(self):
        mock_client = MagicMock()
        mock_client.keys.return_value = ["tenants:id:1", "tenants:id:2"]
        mock_client.delete.return_value = 2
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import flush_all_tenant_cache
        count = flush_all_tenant_cache()
        self.assertEqual(count, 2)

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_health_check_ok(self):
        mock_client = MagicMock()
        mock_client.info.return_value = {"redis_version": "7.0.0", "uptime_in_seconds": 3600}
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import cache_health_check
        result = cache_health_check()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["redis_version"], "7.0.0")


class CacheWithoutRedisTest(TestCase):
    def setUp(self):
        _reset_cache_module()

    def tearDown(self):
        _reset_cache_module()

    @override_settings(**SETTINGS_NO_REDIS)
    def test_cache_is_noop_without_redis_url(self):
        from django_tenants_router.cache import cache_tenant_db, get_cached_tenant_db
        cache_tenant_db("uuid-1234", "tenant_acme")
        result = get_cached_tenant_db("uuid-1234")
        self.assertIsNone(result)

    @override_settings(**SETTINGS_NO_REDIS)
    def test_invalidate_is_noop_without_redis(self):
        from django_tenants_router.cache import invalidate_tenant
        invalidate_tenant("uuid-1234")

    @override_settings(**SETTINGS_NO_REDIS)
    def test_health_check_unavailable(self):
        from django_tenants_router.cache import cache_health_check
        result = cache_health_check()
        self.assertEqual(result["status"], "unavailable")

    @override_settings(**SETTINGS_WITH_REDIS)
    def test_cache_falls_back_gracefully_on_redis_error(self):
        """If Redis is injected but then fails on a get, operations return None silently."""
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("connection reset")
        _inject_mock_client(mock_client)

        from django_tenants_router.cache import get_cached_tenant_db
        result = get_cached_tenant_db("uuid-1234")
        self.assertIsNone(result)
