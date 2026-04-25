"""
TenantDatabaseRouter
====================
Django database router that:
  - Routes all django_tenants_router app models to the root DB.
  - Routes all other models to the active tenant DB (set via context or thread-local).
  - Prevents cross-tenant relations.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_thread_local = threading.local()


# ---------------------------------------------------------------------------
# Public helpers – use these in views / middleware
# ---------------------------------------------------------------------------


def set_tenant_db(db_alias: Optional[str]) -> None:
    """
    Set the active tenant DB alias for the current thread.
    Call this in middleware or at the start of a request.
    """
    _thread_local.tenant_db = db_alias


def get_tenant_db() -> Optional[str]:
    """Return the currently active tenant DB alias for this thread."""
    return getattr(_thread_local, "tenant_db", None)


def clear_tenant_db() -> None:
    """Clear the active tenant DB alias for the current thread."""
    _thread_local.tenant_db = None


@contextmanager
def tenant_db_context(db_alias: str):
    """
    Context manager that temporarily sets the active tenant DB.

    Usage::

        with tenant_db_context("tenant_acme"):
            MyModel.objects.all()  # runs on tenant_acme DB
    """
    previous = get_tenant_db()
    set_tenant_db(db_alias)
    try:
        yield db_alias
    finally:
        set_tenant_db(previous)


@contextmanager
def tenant_context_by_id(tenant_id: str):
    """
    Context manager that sets the active tenant DB by tenant UUID.

    Usage::

        with tenant_context_by_id(request.tenant_id):
            Order.objects.filter(user=user)
    """
    from django_tenants_router.registry import TenantRegistry

    db_alias = TenantRegistry.get_db_for_tenant_id(tenant_id)
    if not db_alias:
        raise ValueError(f"No database found for tenant_id={tenant_id!r}")
    with tenant_db_context(db_alias):
        yield db_alias


# ---------------------------------------------------------------------------
# The Router
# ---------------------------------------------------------------------------

ROUTER_APP_LABEL = "django_tenants_router"
COMMON_APPS = getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("COMMON_APPS" ,[])


class TenantDatabaseRouter:
    """
    A router that:
    - Sends ``django_tenants_router`` models to the ROOT_DB.
    - Sends everything else to the active tenant DB.
    - Blocks cross-tenant relations.
    """

    @property
    def _root_db(self) -> str:
        return getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("ROOT_DB", "default")

    def _is_router_model(self, model) -> bool:
        return model._meta.app_label == ROUTER_APP_LABEL

    def db_for_read(self, model, **hints):
        if self._is_router_model(model):
            return self._root_db
        tenant_db = get_tenant_db()
        if tenant_db:
            return tenant_db
        return None  # Django falls back to default

    def db_for_write(self, model, **hints):
        if self._is_router_model(model):
            return self._root_db
        tenant_db = get_tenant_db()
        if tenant_db:
            return tenant_db
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations only within the same logical database.
        Prevent cross-tenant relations.
        """
        # Both are router models – always allowed.
        if self._is_router_model(type(obj1)) and self._is_router_model(type(obj2)):
            return True
        # One is a router model, other is not – allow (FK to Tenant from tenant DBs).
        if self._is_router_model(type(obj1)) or self._is_router_model(type(obj2)):
            return True
        # Tenant models: only allow if same DB.
        db1 = obj1._state.db
        db2 = obj2._state.db
        if db1 and db2 and db1 != db2:
            logger.warning(
                "Cross-tenant relation blocked: %s (db=%s) <-> %s (db=%s)",
                type(obj1).__name__,
                db1,
                type(obj2).__name__,
                db2,
            )
            return False
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        - Router app models  → only on root DB.
        - Everything else    → only on tenant DBs (not root).
        """
        root = self._root_db
        if app_label in COMMON_APPS:
            return True
        if app_label == ROUTER_APP_LABEL:
            return db == root
        # For all other apps, allow only on non-root DBs.
        return db != root
 