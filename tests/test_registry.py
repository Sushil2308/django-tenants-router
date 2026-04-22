"""
Tests: Registry
===============
Tests for TenantRegistry – in-memory tenant map and DB registration.
"""

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings


MOCK_SETTINGS = {
    "TENANT_ROUTER_CONFIG": {"ROOT_DB": "default"},
    "DATABASES": {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
    },
}


def _make_tenant(slug="acme", tenant_id="uuid-1234", db_alias="tenant_acme"):
    tenant = MagicMock()
    tenant.slug = slug
    tenant.id = tenant_id
    tenant.db_alias = db_alias
    tenant.is_active = True

    db_config = MagicMock()
    db_config.to_django_db_dict.return_value = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
    tenant.db_config = db_config
    return tenant


@override_settings(**MOCK_SETTINGS)
class RegistryTest(TestCase):
    def setUp(self):
        # Import fresh registry instance
        from django_tenants_router.registry import _TenantRegistry
        self.registry = _TenantRegistry()

    def test_register_tenant(self):
        tenant = _make_tenant()
        self.registry._register_tenant(tenant)

        self.assertIn("acme", self.registry._tenants)
        self.assertEqual(self.registry._id_to_alias["uuid-1234"], "tenant_acme")

    def test_get_db_for_tenant_id(self):
        tenant = _make_tenant()
        self.registry._register_tenant(tenant)

        alias = self.registry.get_db_for_tenant_id("uuid-1234")
        self.assertEqual(alias, "tenant_acme")

    def test_get_db_for_unknown_id_returns_none(self):
        alias = self.registry.get_db_for_tenant_id("not-real")
        self.assertIsNone(alias)

    def test_get_db_for_slug(self):
        tenant = _make_tenant()
        self.registry._register_tenant(tenant)

        alias = self.registry.get_db_for_slug("acme")
        self.assertEqual(alias, "tenant_acme")

    def test_get_db_for_unknown_slug_returns_none(self):
        self.assertIsNone(self.registry.get_db_for_slug("ghost"))

    def test_get_tenant_by_id(self):
        tenant = _make_tenant()
        self.registry._register_tenant(tenant)

        result = self.registry.get_tenant_by_id("uuid-1234")
        self.assertEqual(result.slug, "acme")

    def test_unregister_tenant(self):
        tenant = _make_tenant()
        self.registry._register_tenant(tenant)
        self.registry.unregister("acme")

        self.assertNotIn("acme", self.registry._tenants)
        self.assertNotIn("uuid-1234", self.registry._id_to_alias)

    def test_all_tenant_aliases(self):
        t1 = _make_tenant("acme", "id-1", "tenant_acme")
        t2 = _make_tenant("globex", "id-2", "tenant_globex")
        self.registry._register_tenant(t1)
        self.registry._register_tenant(t2)

        aliases = self.registry.all_tenant_aliases()
        self.assertIn("tenant_acme", aliases)
        self.assertIn("tenant_globex", aliases)

    def test_all_tenants(self):
        t1 = _make_tenant("acme", "id-1", "tenant_acme")
        self.registry._register_tenant(t1)

        tenants = self.registry.all_tenants()
        self.assertEqual(len(tenants), 1)
        self.assertEqual(tenants[0].slug, "acme")

    def test_register_updates_django_databases(self):
        tenant = _make_tenant()
        self.registry._register_tenant(tenant)

        self.assertIn("tenant_acme", settings.DATABASES)

    def test_tenant_missing_db_config_is_skipped(self):
        tenant = MagicMock()
        tenant.slug = "broken"
        tenant.id = "id-broken"
        del tenant.db_config  # Simulate missing related object

        # Should not raise
        self.registry._register_tenant(tenant)
        self.assertNotIn("broken", self.registry._tenants)

    def test_refresh_clears_and_reloads(self):
        tenant = _make_tenant()
        self.registry._register_tenant(tenant)
        self.assertEqual(len(self.registry.all_tenants()), 1)

        with patch.object(self.registry, "load_from_db") as mock_load:
            self.registry.refresh()
            self.assertEqual(len(self.registry.all_tenants()), 0)
            mock_load.assert_called_once_with(force=True)

    def test_load_from_db_graceful_on_missing_table(self):
        """load_from_db should not raise if the table doesn't exist yet."""
        with patch(
            "django_tenants_router.models.Tenant.objects.using",
            side_effect=Exception("no such table"),
        ):
            # Should log a warning and return without raising.
            self.registry.load_from_db(force=True)
