"""
Tests: Decorators & Test Utilities
===================================
"""

from unittest.mock import MagicMock, patch

from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from django_tenants_router.decorators import with_tenant, with_tenant_slug, for_each_tenant
from django_tenants_router.router import clear_tenant_db, get_tenant_db
from django_tenants_router.test_utils import (
    MockTenantMixin,
    TenantTestCase,
    override_tenant_db,
)


class WithTenantDecoratorTest(TestCase):
    def tearDown(self):
        clear_tenant_db()

    @patch("django_tenants_router.decorators.TenantRegistry")
    def test_sets_tenant_db_from_kwarg(self, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = "tenant_acme"

        @with_tenant("tenant_id")
        def my_view(request, tenant_id):
            return get_tenant_db()

        result = my_view(MagicMock(), tenant_id="uuid-1234")
        self.assertEqual(result, "tenant_acme")

    @patch("django_tenants_router.decorators.TenantRegistry")
    def test_returns_404_for_unknown_tenant(self, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = None

        @with_tenant("tenant_id")
        def my_view(request, tenant_id):
            return "should not reach here"

        response = my_view(MagicMock(), tenant_id="ghost-uuid")
        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 404)

    @patch("django_tenants_router.decorators.TenantRegistry")
    def test_restores_context_after_call(self, mock_registry):
        mock_registry.get_db_for_tenant_id.return_value = "tenant_acme"

        @with_tenant("tenant_id")
        def my_view(request, tenant_id):
            pass

        my_view(MagicMock(), tenant_id="uuid-1234")
        self.assertIsNone(get_tenant_db())

    def test_skips_if_no_kwarg(self):
        @with_tenant("tenant_id")
        def my_view(request):
            return "ok"

        result = my_view(MagicMock())
        self.assertEqual(result, "ok")


class WithTenantSlugDecoratorTest(TestCase):
    def tearDown(self):
        clear_tenant_db()

    @patch("django_tenants_router.decorators.TenantRegistry")
    def test_sets_tenant_db_from_slug(self, mock_registry):
        mock_registry.get_db_for_slug.return_value = "tenant_acme"

        @with_tenant_slug("tenant_slug")
        def my_view(request, tenant_slug):
            return get_tenant_db()

        result = my_view(MagicMock(), tenant_slug="acme")
        self.assertEqual(result, "tenant_acme")

    @patch("django_tenants_router.decorators.TenantRegistry")
    def test_returns_404_for_unknown_slug(self, mock_registry):
        mock_registry.get_db_for_slug.return_value = None

        @with_tenant_slug("tenant_slug")
        def my_view(request, tenant_slug):
            return "should not reach"

        response = my_view(MagicMock(), tenant_slug="ghost")
        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 404)


class ForEachTenantDecoratorTest(TestCase):
    def tearDown(self):
        clear_tenant_db()

    @patch("django_tenants_router.decorators.TenantRegistry")
    def test_runs_once_per_tenant(self, mock_registry):
        mock_registry.all_tenant_aliases.return_value = ["tenant_a", "tenant_b"]
        called_with = []

        @for_each_tenant()
        def sync(db_alias):
            called_with.append(db_alias)

        sync()
        self.assertIn("tenant_a", called_with)
        self.assertIn("tenant_b", called_with)

    @patch("django_tenants_router.decorators.TenantRegistry")
    def test_collects_results(self, mock_registry):
        mock_registry.all_tenant_aliases.return_value = ["db_a", "db_b"]

        @for_each_tenant()
        def count(db_alias):
            return 42

        results = count()
        self.assertEqual(results["db_a"], 42)
        self.assertEqual(results["db_b"], 42)


class OverrideTenantDbContextTest(TestCase):
    def tearDown(self):
        clear_tenant_db()

    def test_sets_and_restores(self):
        with override_tenant_db("tenant_acme"):
            self.assertEqual(get_tenant_db(), "tenant_acme")
        self.assertIsNone(get_tenant_db())

    def test_restores_on_exception(self):
        try:
            with override_tenant_db("tenant_acme"):
                raise RuntimeError("test")
        except RuntimeError:
            pass
        self.assertIsNone(get_tenant_db())


class TenantTestCaseTest(TenantTestCase):
    tenant_db_alias = "default"

    def test_tenant_context_sets_db(self):
        with self.tenant_context():
            self.assertEqual(get_tenant_db(), "default")

    def test_tenant_context_restores_after(self):
        with self.tenant_context():
            pass
        self.assertIsNone(get_tenant_db())

    def test_make_tenant_request(self):
        request = self.make_tenant_request("/api/orders/")
        self.assertEqual(request.tenant_id, str(self.tenant_id))
        self.assertEqual(request.tenant_db, "default")

    def test_assert_queryset_db(self):
        from django_tenants_router.models import Tenant
        qs = Tenant.objects.using("default").all()
        self.assertQueryRunsOnTenantDB(qs, expected_db="default")


class MockTenantMixinTest(MockTenantMixin, TestCase):
    mock_tenants = {
        "uuid-111": "tenant_alpha",
        "uuid-222": "tenant_beta",
    }

    def test_mock_resolves_alias(self):
        from django_tenants_router.registry import TenantRegistry
        alias = TenantRegistry.get_db_for_tenant_id("uuid-111")
        self.assertEqual(alias, "tenant_alpha")

    def test_mock_returns_none_for_unknown(self):
        from django_tenants_router.registry import TenantRegistry
        alias = TenantRegistry.get_db_for_tenant_id("not-registered")
        self.assertIsNone(alias)

    def test_cache_returns_none(self):
        from django_tenants_router.cache import get_cached_tenant_db
        result = get_cached_tenant_db("uuid-111")
        self.assertIsNone(result)
