"""
TenantRegistry
==============
Singleton that keeps an in-memory map of  tenant_slug → db_alias
and dynamically registers tenant databases into Django's DATABASES setting.
"""

import logging
from typing import Dict, Optional

from django.conf import settings
from django.db import connections

logger = logging.getLogger(__name__)


class _TenantRegistry:
    """Internal singleton – use the module-level `TenantRegistry` instance."""

    def __init__(self):
        # slug -> Tenant model instance
        self._tenants: Dict[str, object] = {}
        # uuid (str) -> db_alias
        self._id_to_alias: Dict[str, str] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def load_from_db(self, force: bool = False) -> None:
        """
        Load all active tenants from the root DB and register their
        database configs into Django's DATABASES setting.
        Called once at app startup from apps.py::ready().
        """
        if self._loaded and not force:
            return

        try:
            from django_tenants_router.models import Tenant
            tenants = list(Tenant.objects.using(self._root_db).filter(is_active=True).select_related("db_config"))
        except Exception as exc:
            # Table may not exist yet (first migration).
            logger.warning("TenantRegistry: could not load tenants – %s", exc)
            self._loaded = True
            return

        for tenant in tenants:
            self._register_tenant(tenant)

        self._loaded = True
        logger.info("TenantRegistry: loaded %d tenant(s).", len(self._tenants))

    def _register_tenant(self, tenant) -> None:
        """Add a single tenant to the registry and to Django DATABASES."""
        try:
            db_config = tenant.db_config
        except Exception:
            logger.warning("Tenant %s has no db_config, skipping.", tenant.slug)
            return

        alias = tenant.db_alias
        settings.DATABASES[alias] = db_config.to_django_db_dict()
        # Ensure Django's connection handler knows about this alias.
        connections.databases[alias] = settings.DATABASES[alias]

        self._tenants[tenant.slug] = tenant
        self._id_to_alias[str(tenant.id)] = alias

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_db_for_tenant_id(self, tenant_id: str) -> Optional[str]:
        """Return the db alias for a given tenant UUID string, or None."""
        return self._id_to_alias.get(str(tenant_id))

    def get_db_for_slug(self, slug: str) -> Optional[str]:
        """Return the db alias for a given tenant slug, or None."""
        tenant = self._tenants.get(slug)
        return tenant.db_alias if tenant else None

    def get_tenant_by_id(self, tenant_id: str):
        """Return the Tenant instance for a given UUID string, or None."""
        alias = self._id_to_alias.get(str(tenant_id))
        if not alias:
            return None
        return next((t for t in self._tenants.values() if t.db_alias == alias), None)

    def all_tenant_aliases(self) -> list:
        """Return a list of all registered tenant db aliases (excludes root DB)."""
        return list(self._id_to_alias.values())

    def all_tenants(self) -> list:
        """Return all registered Tenant instances."""
        return list(self._tenants.values())

    def register(self, tenant) -> None:
        """Dynamically register a new tenant at runtime (e.g. after creation)."""
        self._register_tenant(tenant)
        logger.info("TenantRegistry: dynamically registered tenant '%s'.", tenant.slug)

    def unregister(self, slug: str) -> None:
        """Remove a tenant from the registry (does NOT drop the DB)."""
        tenant = self._tenants.pop(slug, None)
        if tenant:
            self._id_to_alias.pop(str(tenant.id), None)
            logger.info("TenantRegistry: unregistered tenant '%s'.", slug)

    def refresh(self) -> None:
        """Force-reload all tenants from the root DB."""
        self._tenants.clear()
        self._id_to_alias.clear()
        self._loaded = False
        self.load_from_db(force=True)

    @property
    def _root_db(self) -> str:
        return getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("ROOT_DB", "default")


TenantRegistry = _TenantRegistry()
