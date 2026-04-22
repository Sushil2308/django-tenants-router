"""
Tests: Middleware
=================
Tests for TenantMiddleware request lifecycle, resolution order, and edge cases.
"""

from unittest.mock import MagicMock, patch

from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings

from django_tenants_router.middleware import TenantMiddleware
from django_tenants_router.router import clear_tenant_db, get_tenant_db


MOCK_SETTINGS = {
    "TENANT_ROUTER_CONFIG": {
        "ROOT_DB": "default",
        "TENANT_HEADER": "HTTP_X_TENANT_ID",
        "TENANT_REQUIRED": False,
        "TENANT_EXEMPT_PATHS": ["/admin/", "/health/"],
    },
    "DATABASES": {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
        "tenant_acme": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
    },
}


def _make_middleware(required=False, get_response=None):
    if get_response is None:
        get_response = MagicMock(return_value=MagicMock(status_code=200))
    with override_settings(**{**MOCK_SETTINGS, "TENANT_ROUTER_CONFIG": {**MOCK_SETTINGS["TENANT_ROUTER_CONFIG"], "TENANT_REQUIRED": required}}):
        return TenantMiddleware(get_response)


@override_settings(**MOCK_SETTINGS)
class TenantMiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.get_response = MagicMock(return_value=MagicMock(status_code=200))
        self.middleware = TenantMiddleware(self.get_response)

    def tearDown(self):
        clear_tenant_db()

    @patch("django_tenants_router.middleware.TenantRegistry")
    @patch("django_tenants_router.middleware.get_cached_tenant_db", return_value=None)
    def test_resolves_tenant_from_header(self, mock_cache, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = "tenant_acme"
        request = self.factory.get("/api/orders/", HTTP_X_TENANT_ID="uuid-1234")
        self.middleware(request)
        self.assertEqual(request.tenant_id, "uuid-1234")
        self.assertEqual(request.tenant_db, "tenant_acme")

    @patch("django_tenants_router.middleware.TenantRegistry")
    @patch("django_tenants_router.middleware.get_cached_tenant_db", return_value="tenant_acme")
    def test_uses_cache_when_available(self, mock_cache, mock_registry):
        request = self.factory.get("/api/orders/", HTTP_X_TENANT_ID="uuid-1234")
        self.middleware(request)
        # Registry should NOT be called when cache hits
        mock_registry.get_db_for_tenant_id.assert_not_called()

    def test_exempt_paths_skip_resolution(self):
        request = self.factory.get("/admin/tenants/")
        self.middleware(request)
        # No tenant set on exempt paths
        self.assertFalse(hasattr(request, "tenant_id"))

    def test_exempt_health_path(self):
        request = self.factory.get("/health/")
        response = self.middleware(request)
        self.get_response.assert_called_once_with(request)

    @patch("django_tenants_router.middleware.TenantRegistry")
    @patch("django_tenants_router.middleware.get_cached_tenant_db", return_value=None)
    def test_unknown_tenant_passes_through_when_not_required(self, mock_cache, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = None
        request = self.factory.get("/api/orders/", HTTP_X_TENANT_ID="ghost-id")
        response = self.middleware(request)
        # Should still call get_response (not block)
        self.get_response.assert_called_once()

    def test_missing_tenant_returns_400_when_required(self):
        with override_settings(**{
            **MOCK_SETTINGS,
            "TENANT_ROUTER_CONFIG": {**MOCK_SETTINGS["TENANT_ROUTER_CONFIG"], "TENANT_REQUIRED": True}
        }):
            mw = TenantMiddleware(self.get_response)
            request = self.factory.get("/api/orders/")
            response = mw(request)
            self.assertEqual(response.status_code, 400)

    @patch("django_tenants_router.middleware.TenantRegistry")
    @patch("django_tenants_router.middleware.get_cached_tenant_db", return_value=None)
    def test_unknown_tenant_returns_403_when_required(self, mock_cache, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = None
        with override_settings(**{
            **MOCK_SETTINGS,
            "TENANT_ROUTER_CONFIG": {**MOCK_SETTINGS["TENANT_ROUTER_CONFIG"], "TENANT_REQUIRED": True}
        }):
            mw = TenantMiddleware(self.get_response)
            request = self.factory.get("/api/orders/", HTTP_X_TENANT_ID="ghost-id")
            response = mw(request)
            self.assertEqual(response.status_code, 403)

    @patch("django_tenants_router.middleware.TenantRegistry")
    @patch("django_tenants_router.middleware.get_cached_tenant_db", return_value=None)
    def test_thread_local_cleared_after_request(self, mock_cache, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = "tenant_acme"
        request = self.factory.get("/api/orders/", HTTP_X_TENANT_ID="uuid-1234")
        self.middleware(request)
        # After the request, tenant DB should be cleared
        self.assertIsNone(get_tenant_db())

    @patch("django_tenants_router.middleware.TenantRegistry")
    @patch("django_tenants_router.middleware.get_cached_tenant_db", return_value=None)
    def test_thread_local_cleared_on_exception(self, mock_cache, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = "tenant_acme"
        self.get_response.side_effect = RuntimeError("view exploded")
        request = self.factory.get("/api/orders/", HTTP_X_TENANT_ID="uuid-1234")
        with self.assertRaises(RuntimeError):
            self.middleware(request)
        self.assertIsNone(get_tenant_db())

    @patch("django_tenants_router.middleware.TenantRegistry")
    @patch("django_tenants_router.middleware.get_cached_tenant_db", return_value=None)
    def test_resolves_from_query_param(self, mock_cache, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = "tenant_acme"
        request = self.factory.get("/api/orders/?tenant_id=uuid-9999")
        self.middleware(request)
        self.assertEqual(request.tenant_db, "tenant_acme")
