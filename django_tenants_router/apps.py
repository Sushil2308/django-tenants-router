from django.apps import AppConfig


class DjangoTenantsRouterConfig(AppConfig):
    name = "django_tenants_router"
    verbose_name = "Django Tenants Router"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django_tenants_router import signals  # noqa: F401
        from django_tenants_router.registry import TenantRegistry

        TenantRegistry.load_from_db()
