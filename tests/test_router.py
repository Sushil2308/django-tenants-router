"""
Tests: Router
=============
Tests for TenantDatabaseRouter and thread-local context helpers.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from django_tenants_router.router import (
    TenantDatabaseRouter,
    clear_tenant_db,
    get_tenant_db,
    set_tenant_db,
    tenant_db_context,
    tenant_context_by_id,
)


MOCK_SETTINGS = {
    "TENANT_ROUTER_CONFIG": {"ROOT_DB": "default"},
    "COMMON_APPS": ("admin", "auth", "contenttypes", "sessions"),
    "DATABASES": {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
        "tenant_acme": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
    },
}


class ThreadLocalTest(TestCase):
    def tearDown(self):
        clear_tenant_db()

    def test_set_and_get(self):
        set_tenant_db("tenant_acme")
        self.assertEqual(get_tenant_db(), "tenant_acme")

    def test_clear(self):
        set_tenant_db("tenant_acme")
        clear_tenant_db()
        self.assertIsNone(get_tenant_db())

    def test_set_none(self):
        set_tenant_db(None)
        self.assertIsNone(get_tenant_db())


class TenantDbContextTest(TestCase):
    def tearDown(self):
        clear_tenant_db()

    def test_context_sets_and_restores(self):
        set_tenant_db("outer_db")
        with tenant_db_context("inner_db"):
            self.assertEqual(get_tenant_db(), "inner_db")
        self.assertEqual(get_tenant_db(), "outer_db")

    def test_context_restores_on_exception(self):
        set_tenant_db("outer_db")
        try:
            with tenant_db_context("inner_db"):
                raise ValueError("boom")
        except ValueError:
            pass
        self.assertEqual(get_tenant_db(), "outer_db")

    def test_context_yields_alias(self):
        with tenant_db_context("tenant_acme") as alias:
            self.assertEqual(alias, "tenant_acme")

    def test_nested_contexts(self):
        with tenant_db_context("db_a"):
            self.assertEqual(get_tenant_db(), "db_a")
            with tenant_db_context("db_b"):
                self.assertEqual(get_tenant_db(), "db_b")
            self.assertEqual(get_tenant_db(), "db_a")


class TenantContextByIdTest(TestCase):
    def tearDown(self):
        clear_tenant_db()

    @patch("django_tenants_router.registry.TenantRegistry.get_db_for_tenant_id", return_value="tenant_acme")
    def test_resolves_alias_from_id(self, mock_method):
        with tenant_context_by_id("uuid-1234") as alias:
            self.assertEqual(alias, "tenant_acme")
            self.assertEqual(get_tenant_db(), "tenant_acme")

    @patch("django_tenants_router.registry.TenantRegistry.get_db_for_tenant_id", return_value=None)
    def test_raises_on_unknown_tenant(self, mock_method):
        with self.assertRaises(ValueError):
            with tenant_context_by_id("bad-uuid"):
                pass


@override_settings(**MOCK_SETTINGS)
class RouterTest(TestCase):
    def setUp(self):
        self.router = TenantDatabaseRouter()
        clear_tenant_db()

    def tearDown(self):
        clear_tenant_db()

    # --- db_for_read ---

    def test_router_model_reads_root_db(self):
        model = MagicMock()
        model._meta.app_label = "django_tenants_router"
        result = self.router.db_for_read(model)
        self.assertEqual(result, "default")

    def test_tenant_model_reads_active_tenant_db(self):
        set_tenant_db("tenant_acme")
        model = MagicMock()
        model._meta.app_label = "myapp"
        result = self.router.db_for_read(model)
        self.assertEqual(result, "tenant_acme")

    def test_tenant_model_returns_none_when_no_tenant(self):
        model = MagicMock()
        model._meta.app_label = "myapp"
        result = self.router.db_for_read(model)
        self.assertIsNone(result)

    # --- db_for_write ---

    def test_router_model_writes_root_db(self):
        model = MagicMock()
        model._meta.app_label = "django_tenants_router"
        result = self.router.db_for_write(model)
        self.assertEqual(result, "default")

    def test_tenant_model_writes_active_db(self):
        set_tenant_db("tenant_acme")
        model = MagicMock()
        model._meta.app_label = "orders"
        result = self.router.db_for_write(model)
        self.assertEqual(result, "tenant_acme")

    # --- allow_relation ---

    def _make_obj(self, app_label, db):
        """Build a mock model instance with _meta.app_label and _state.db."""
        obj = MagicMock()
        # type(obj) needs _meta so _is_router_model(type(obj)) works
        type(obj)._meta = MagicMock()
        type(obj)._meta.app_label = app_label
        obj._state = MagicMock()
        obj._state.db = db
        return obj

    def test_same_db_relation_allowed(self):
        obj1 = self._make_obj("orders", "tenant_acme")
        obj2 = self._make_obj("orders", "tenant_acme")
        self.assertTrue(self.router.allow_relation(obj1, obj2))

    def test_cross_tenant_relation_blocked(self):
        obj1 = self._make_obj("orders", "tenant_acme")
        obj2 = self._make_obj("orders", "tenant_globex")
        self.assertFalse(self.router.allow_relation(obj1, obj2))

    def test_router_model_relation_always_allowed(self):
        obj1 = self._make_obj("django_tenants_router", "default")
        obj2 = self._make_obj("django_tenants_router", "default")
        self.assertTrue(self.router.allow_relation(obj1, obj2))

    # --- allow_migrate ---

    def test_router_app_migrates_on_root_only(self):
        self.assertTrue(self.router.allow_migrate("default", "django_tenants_router"))
        self.assertFalse(self.router.allow_migrate("tenant_acme", "django_tenants_router"))

    def test_other_apps_dont_migrate_on_root(self):
        self.assertFalse(self.router.allow_migrate("default", "orders"))

    def test_other_apps_migrate_on_tenant_db(self):
        self.assertTrue(self.router.allow_migrate("tenant_acme", "orders"))
