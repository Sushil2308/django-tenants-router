"""
TenantRegistry
==============
Singleton that keeps an in-memory map of tenant_slug → db_alias and
dynamically registers / updates / removes tenant databases from
Django's DATABASES setting AND its connection handler.

On every config change the registry does a full four-layer purge:

  Layer 1 — Redis cache         : tenant_id key evicted
  Layer 2 — Thread-local wrappers: DatabaseWrapper objects deleted from
             connections._connections so Django creates a fresh wrapper
             on next access (this is the layer the admin was missing)
  Layer 3 — connections.settings : alias removed from the live settings dict
  Layer 4 — settings.DATABASES  : alias removed from the global config

Then the new config is written into layers 3 and 4, and Django will
create a brand-new DatabaseWrapper (layer 2) on the next ORM call.
"""

import logging
import threading
from typing import Dict, Optional

from django.conf import settings
from django.db import connections

logger = logging.getLogger(__name__)

_registry_lock = threading.Lock()


class _TenantRegistry:

    def __init__(self):
        self._tenants: Dict[str, object] = {}
        self._id_to_alias: Dict[str, str] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def load_from_db(self, force: bool = False) -> None:
        if self._loaded and not force:
            return

        try:
            from django_tenants_router.models import Tenant
            tenants = list(
                Tenant.objects
                .using(self._root_db)
                .filter(is_active=True)
                .select_related("db_config")
            )
        except Exception as exc:
            logger.warning("TenantRegistry: could not load tenants – %s", exc)
            self._loaded = True
            return

        for tenant in tenants:
            try:
                self._register_tenant(tenant)
            except:
                logger.warning("TenantRegistry: skipped %s tenant.", tenant.db_alias)
                pass

        self._loaded = True
        logger.info("TenantRegistry: loaded %d tenant(s).", len(self._tenants))

    # ------------------------------------------------------------------
    # Core purge — four layers
    # ------------------------------------------------------------------

    @staticmethod
    def _purge_connection(alias: str) -> None:
        """
        Fully evict an alias so the next ORM call creates a brand-new
        connection with the current credentials.

        Layer 1 (Redis) is handled by the caller before _purge_connection
        is invoked, so we handle layers 2-4 here:

        Layer 2 — Close and delete the thread-local DatabaseWrapper.
                   connections._connections is a Local() (thread-local);
                   delattr removes it from the *current* thread.
                   Other threads will hit AttributeError on next access
                   and create_connection() will be called fresh for them too.

        Layer 3 — Remove from connections.settings (the live dict that
                   ConnectionHandler.__getitem__ reads from).

        Layer 4 — Remove from settings.DATABASES (global config).
        """
        # Layer 2a: close the live connection gracefully
        try:
            if hasattr(connections._connections, alias):
                connections[alias].close()
                logger.debug("TenantRegistry: closed connection for '%s'.", alias)
        except Exception as exc:
            logger.warning(
                "TenantRegistry: could not close connection for '%s' – %s", alias, exc
            )

        # Layer 2b: delete the cached DatabaseWrapper from the thread-local store.
        # This is the critical step — without it Django returns the stale wrapper
        # from _connections even after settings.DATABASES is updated.
        try:
            if hasattr(connections._connections, alias):
                delattr(connections._connections, alias)
                logger.debug(
                    "TenantRegistry: deleted thread-local DatabaseWrapper for '%s'.", alias
                )
        except Exception as exc:
            logger.warning(
                "TenantRegistry: could not delete _connections.%s – %s", alias, exc
            )

        # Layer 3: remove from the live settings dict (connections.settings)
        try:
            if alias in connections.settings:
                del connections.settings[alias]
        except Exception as exc:
            logger.warning(
                "TenantRegistry: could not remove '%s' from connections.settings – %s",
                alias, exc,
            )

        # Layer 4: remove from global settings.DATABASES
        settings.DATABASES.pop(alias, None)

    # ------------------------------------------------------------------
    # Register / update
    # ------------------------------------------------------------------

    def _register_tenant(self, tenant) -> None:
        """
        Add or fully replace a tenant's DB config across all four layers.
        Always purges first so stale connections and credentials are never reused.
        """
        try:
            db_config = tenant.db_config
        except Exception:
            logger.warning("Tenant '%s' has no db_config — skipping.", tenant.slug)
            return

        alias = tenant.db_alias
        new_db_dict = db_config.to_django_db_dict()

        with _registry_lock:
            # Purge layers 2-4 (layer 1 / Redis is the caller's responsibility)
            self._purge_connection(alias)

            # Write fresh config into layers 3 and 4.
            # Layer 4 — global settings
            settings.DATABASES[alias] = new_db_dict
            # Layer 3 — live ConnectionHandler settings dict
            connections.settings[alias] = new_db_dict

            # Layer 2 will be populated automatically by Django's
            # ConnectionHandler.__getitem__ on the next ORM access.

            # Update in-memory maps
            self._tenants[tenant.slug] = tenant
            self._id_to_alias[str(tenant.id)] = alias

        logger.info(
            "TenantRegistry: registered alias='%s' host=%s db=%s.",
            alias,
            getattr(db_config, "host", "?"),
            getattr(db_config, "db_name", "?"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_db_for_tenant_id(self, tenant_id: str) -> Optional[str]:
        return self._id_to_alias.get(str(tenant_id))

    def get_db_for_slug(self, slug: str) -> Optional[str]:
        tenant = self._tenants.get(slug)
        return tenant.db_alias if tenant else None

    def get_tenant_by_id(self, tenant_id: str):
        alias = self._id_to_alias.get(str(tenant_id))
        if not alias:
            return None
        return next((t for t in self._tenants.values() if t.db_alias == alias), None)

    def all_tenant_aliases(self) -> list:
        return list(self._id_to_alias.values())

    def all_tenants(self) -> list:
        return list(self._tenants.values())

    def register(self, tenant) -> None:
        """Register or re-register a tenant at runtime."""
        self._register_tenant(tenant)

    def unregister(self, slug: str) -> None:
        """
        Remove a tenant from the registry and close its DB connections.
        Does NOT drop the PostgreSQL database.
        """
        with _registry_lock:
            tenant = self._tenants.pop(slug, None)
            if not tenant:
                return
            alias = tenant.db_alias
            self._id_to_alias.pop(str(tenant.id), None)
            self._purge_connection(alias)

        logger.info("TenantRegistry: unregistered alias='%s' (slug='%s').", alias, slug)

    def update_db_config(self, tenant) -> None:
        """
        Hot-reload a changed TenantDatabaseConfig with zero downtime.

        Invalidation order (must be preserved):
          1. Redis evicted first  — prevents new requests from caching
                                    the stale alias during the update.
          2. Thread-local wrapper deleted — forces Django to create a new
                                    DatabaseWrapper with fresh credentials.
          3. settings.DATABASES updated — new host/port/credentials written.
          4. In-memory registry updated — slug/id maps point to new config.

        After this call the very next ORM query for this tenant opens a
        brand-new connection using the updated credentials — even in the
        same process without a server restart.
        """
        from django_tenants_router.cache import invalidate_tenant

        tenant_id = str(tenant.id)
        alias = tenant.db_alias

        logger.info(
            "TenantRegistry: applying config change for alias='%s' tenant_id=%s.",
            alias, tenant_id,
        )

        # Step 1 — Redis (must be before _register_tenant to close race window)
        invalidate_tenant(tenant_id)

        # Steps 2-4 — purge thread-local + settings + re-register
        self._register_tenant(tenant)

        logger.info(
            "TenantRegistry: config change applied — alias='%s' is live immediately.",
            alias,
        )

    def refresh(self) -> None:
        """Force-reload all tenants from the root DB."""
        with _registry_lock:
            for alias in list(self._id_to_alias.values()):
                self._purge_connection(alias)
            self._tenants.clear()
            self._id_to_alias.clear()
            self._loaded = False
        self.load_from_db(force=True)

    @property
    def _root_db(self) -> str:
        return getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("ROOT_DB", "default")


TenantRegistry = _TenantRegistry()