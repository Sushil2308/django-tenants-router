"""
Signals
=======
Custom Django signals fired during tenant lifecycle events.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import Signal, receiver

# Fired after a tenant is activated or deactivated.
tenant_activated = Signal()
tenant_deactivated = Signal()

# Fired after a new tenant DB config is created/updated.
tenant_db_config_changed = Signal()


@receiver(post_save, sender="django_tenants_router.Tenant")
def on_tenant_saved(sender, instance, created, **kwargs):
    from django_tenants_router.registry import TenantRegistry

    if created:
        # Defer registration until db_config is created.
        return

    if instance.is_active:
        TenantRegistry.register(instance)
        tenant_activated.send(sender=sender, tenant=instance)
    else:
        TenantRegistry.unregister(instance.slug)
        from django_tenants_router.cache import invalidate_tenant
        invalidate_tenant(str(instance.id))
        tenant_deactivated.send(sender=sender, tenant=instance)


@receiver(post_save, sender="django_tenants_router.TenantDatabaseConfig")
def on_db_config_saved(sender, instance, **kwargs):
    from django_tenants_router.registry import TenantRegistry
    from django_tenants_router.cache import invalidate_tenant

    # Re-register so the new DB settings take effect immediately.
    TenantRegistry.register(instance.tenant)
    invalidate_tenant(str(instance.tenant.id))
    tenant_db_config_changed.send(sender=sender, db_config=instance)


@receiver(post_delete, sender="django_tenants_router.Tenant")
def on_tenant_deleted(sender, instance, **kwargs):
    from django_tenants_router.registry import TenantRegistry
    from django_tenants_router.cache import invalidate_tenant

    TenantRegistry.unregister(instance.slug)
    invalidate_tenant(str(instance.id))
