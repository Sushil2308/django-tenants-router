"""
Test Utilities
==============
Helpers for writing tests in multi-tenant Django projects.
"""

import uuid
from contextlib import contextmanager
from unittest.mock import patch

from django.test import TestCase, RequestFactory

from django_tenants_router.router import clear_tenant_db, get_tenant_db, set_tenant_db


class TenantTestCase(TestCase):
    """
    Base test case for tenant-aware tests.

    Sets up an in-memory tenant registry so tests never need a real
    secondary database.  Override ``tenant_db_alias`` to point at a
    real test database when integration testing.

    Usage::

        class MyModelTest(TenantTestCase):
            tenant_db_alias = "test_tenant"

            def test_create_order(self):
                with self.tenant_context():
                    order = Order.objects.create(amount=100)
                    self.assertEqual(Order.objects.count(), 1)
    """

    tenant_db_alias: str = "default"
    tenant_id: str = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls.tenant_id is None:
            cls.tenant_id = str(uuid.uuid4())

    def setUp(self):
        super().setUp()
        clear_tenant_db()

    def tearDown(self):
        super().tearDown()
        clear_tenant_db()

    @contextmanager
    def tenant_context(self, db_alias: str = None, tenant_id: str = None):
        """
        Context manager that activates a tenant DB for the duration of the block.

        Usage::

            with self.tenant_context():
                Order.objects.create(...)
        """
        alias = db_alias or self.tenant_db_alias
        previous = get_tenant_db()
        set_tenant_db(alias)
        try:
            yield alias
        finally:
            set_tenant_db(previous)

    def assertQueryRunsOnTenantDB(self, queryset, expected_db: str = None):
        """Assert that a queryset is bound to the expected tenant DB."""
        expected = expected_db or self.tenant_db_alias
        self.assertEqual(
            queryset.db,
            expected,
            f"Expected queryset to use DB '{expected}', got '{queryset.db}'.",
        )

    def make_tenant_request(self, path: str = "/", method: str = "get", **kwargs):
        """
        Build a request with tenant headers pre-set.

        Usage::

            request = self.make_tenant_request("/api/orders/", tenant_id="uuid-here")
        """
        factory = RequestFactory()
        tid = kwargs.pop("tenant_id", self.tenant_id)
        request_method = getattr(factory, method.lower())
        request = request_method(path, HTTP_X_TENANT_ID=str(tid), **kwargs)
        request.tenant_id = str(tid)
        request.tenant_db = self.tenant_db_alias
        return request


class MockTenantMixin:
    """
    Mixin that patches TenantRegistry so tests don't need real DB rows.

    Usage::

        class MyTest(MockTenantMixin, TestCase):
            mock_tenants = {
                "uuid-1234": "tenant_acme",
                "uuid-5678": "tenant_globex",
            }
    """

    mock_tenants: dict = {}

    def setUp(self):
        super().setUp()
        self._patches = []

        def fake_get_db_for_id(tenant_id):
            return self.mock_tenants.get(str(tenant_id))

        p = patch(
            "django_tenants_router.registry.TenantRegistry.get_db_for_tenant_id",
            side_effect=fake_get_db_for_id,
        )
        p.start()
        self._patches.append(p)

        p2 = patch(
            "django_tenants_router.cache.get_cached_tenant_db",
            return_value=None,
        )
        p2.start()
        self._patches.append(p2)

    def tearDown(self):
        super().tearDown()
        for p in self._patches:
            p.stop()


@contextmanager
def override_tenant_db(db_alias: str):
    """
    Standalone context manager for use outside test classes.

    Usage::

        with override_tenant_db("tenant_acme"):
            ...
    """
    previous = get_tenant_db()
    set_tenant_db(db_alias)
    try:
        yield db_alias
    finally:
        set_tenant_db(previous)
