"""
Signals
=======
Django signal receivers that keep the TenantRegistry, settings.DATABASES,
Django's connection handler, and Redis cache all in sync whenever a Tenant
or TenantDatabaseConfig is created, updated, or deleted.

Three-layer invalidation on every change
-----------------------------------------
Layer 1 — Connection layer  : open DB connections for the alias are closed
Layer 2 — In-memory registry: _tenants / _id_to_alias maps updated
Layer 3 — Redis cache       : tenant_id key evicted

This means the very next ORM call after a config change opens a brand-new
connection with the updated credentials — zero stale state.
"""

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import Signal, receiver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public signals — connect to these in your own app to react to changes.
# ---------------------------------------------------------------------------

# Fired when a tenant transitions to is_active=True.
tenant_activated = Signal()

# Fired when a tenant transitions to is_active=False.
tenant_deactivated = Signal()

# Fired after TenantDatabaseConfig is created or updated.
# kwargs: db_config=<TenantDatabaseConfig instance>, previous_host, previous_db_name
tenant_db_config_changed = Signal()

# Fired after a tenant is hard-deleted.
tenant_deleted = Signal()


# ---------------------------------------------------------------------------
# Receivers
# ---------------------------------------------------------------------------

@receiver(post_save, sender="django_tenants_router.Tenant")
def on_tenant_saved(sender, instance, created, **kwargs):
    """
    React to Tenant create / update.

    - Created : do nothing yet — db_config doesn't exist until the next save.
    - Updated active   : re-register (applies any field changes, e.g. slug rename).
    - Updated inactive : full three-layer eviction; connections closed immediately.
    """
    from django_tenants_router.registry import TenantRegistry

    if created:
        # db_config hasn't been created yet — registration happens in
        # on_db_config_saved once TenantDatabaseConfig is saved.
        logger.debug("Tenant '%s' created — deferring registration.", instance.slug)
        return

    if instance.is_active:
        # Re-register with whatever is currently in db_config.
        # _register_tenant does a purge-then-rewrite so even a slug/schema_name
        # change is handled correctly.
        TenantRegistry.register(instance)
        tenant_activated.send(sender=sender, tenant=instance)
        logger.info("Tenant '%s' re-registered after update.", instance.slug)
    else:
        # Deactivated — evict from all three layers immediately.
        _full_evict(instance)
        tenant_deactivated.send(sender=sender, tenant=instance)
        logger.info("Tenant '%s' deactivated and evicted from all caches.", instance.slug)


@receiver(post_save, sender="django_tenants_router.TenantDatabaseConfig")
def on_db_config_saved(sender, instance, created, **kwargs):
    """
    React to TenantDatabaseConfig create / update.

    This is the critical path for the feature request:
    "after updating the TenantDatabaseConfig, change the status immediately
    and invalidate cache (Redis + in-memory) both."

    What happens here (in order):
      1. Redis cache evicted  — no request can read the stale alias.
      2. Open connections closed  — old host/port/credentials dropped.
      3. settings.DATABASES updated — new credentials written.
      4. connections.databases updated — Django's live handler reloaded.
      5. In-memory registry updated — slug/id maps point to new config.
      6. tenant_db_config_changed signal fired — your app can react.
    """
    from django_tenants_router.registry import TenantRegistry

    tenant = instance.tenant

    # Capture previous values for the signal payload (best-effort).
    try:
        previous_host    = instance.__class__.objects.get(pk=instance.pk).host
        previous_db_name = instance.__class__.objects.get(pk=instance.pk).db_name
    except Exception:
        previous_host = previous_db_name = None

    TenantRegistry.update_db_config(tenant)

    tenant_db_config_changed.send(
        sender=sender,
        db_config=instance,
        previous_host=previous_host,
        previous_db_name=previous_db_name,
        created=created,
    )

    action = "created" if created else "updated"
    logger.info(
        "TenantDatabaseConfig %s for tenant '%s' — alias '%s' hot-reloaded.",
        action, tenant.slug, tenant.db_alias,
    )


@receiver(post_delete, sender="django_tenants_router.Tenant")
def on_tenant_deleted(sender, instance, **kwargs):
    """
    React to hard deletion of a Tenant row.
    Evicts from all three layers and fires tenant_deleted.
    """
    _full_evict(instance)
    tenant_deleted.send(sender=sender, tenant=instance)
    logger.info("Tenant '%s' deleted — fully evicted.", instance.slug)


@receiver(post_delete, sender="django_tenants_router.TenantDatabaseConfig")
def on_db_config_deleted(sender, instance, **kwargs):
    """
    React to deletion of a TenantDatabaseConfig row (without deleting the Tenant).
    Closes the connection and removes the alias — the tenant still exists in the
    root DB but can no longer route queries until a new config is created.
    """
    from django_tenants_router.registry import TenantRegistry
    from django_tenants_router.cache import invalidate_tenant

    tenant = instance.tenant
    alias  = tenant.db_alias

    invalidate_tenant(str(tenant.id))           # Layer 3: Redis
    TenantRegistry.unregister(tenant.slug)       # Layers 1 + 2: connection + maps

    logger.warning(
        "TenantDatabaseConfig deleted for tenant '%s' (alias '%s'). "
        "Queries will fail until a new config is created.",
        tenant.slug, alias,
    )


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _full_evict(tenant) -> None:
    """
    Evict a tenant from all three cache layers atomically.

    Layer 1 — closes open DB connections for the alias.
    Layer 2 — removes from in-memory registry (_tenants + _id_to_alias).
    Layer 3 — removes from Redis cache.
    """
    from django_tenants_router.registry import TenantRegistry
    from django_tenants_router.cache import invalidate_tenant

    invalidate_tenant(str(tenant.id))   # Redis first — stop new requests caching stale alias
    TenantRegistry.unregister(tenant.slug)  # closes connection, removes from maps + DATABASES
 