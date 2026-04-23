from django.contrib import admin
from django.utils.html import format_html

from django_tenants_router.models import Tenant, TenantDatabaseConfig


class TenantDatabaseConfigInline(admin.StackedInline):
    model = TenantDatabaseConfig
    extra = 0
    fields = (
        "engine",
        "host",
        "port",
        "db_name",
        "db_user",
        "db_password",
        "conn_max_age",
        "is_active",
        "options",
        "atomic_request",
        "auto_commit",
        "conn_health_check",
        "time_zone",
    )


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "schema_name",
        "plan",
        "is_active",
        "db_status_badge",
        "created_at",
    )
    list_filter = ("is_active", "plan")
    search_fields = ("name", "slug", "schema_name")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [TenantDatabaseConfigInline]

    def db_status_badge(self, obj):
        from django.db import connections

        try:
            with connections[obj.db_alias].cursor() as cursor:
                cursor.execute("SELECT 1")
            return format_html('<span style="color:green;font-weight:bold;">✓ Connected</span>')
        except Exception:
            return format_html('<span style="color:red;font-weight:bold;">✗ Unreachable</span>')

    db_status_badge.short_description = "DB Status"

    actions = ["deactivate_tenants", "activate_tenants", "flush_tenant_cache"]

    @admin.action(description="Deactivate selected tenants")
    def deactivate_tenants(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Activate selected tenants")
    def activate_tenants(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Flush Redis cache for selected tenants")
    def flush_tenant_cache(self, request, queryset):
        from django_tenants_router.cache import invalidate_tenant

        for tenant in queryset:
            invalidate_tenant(str(tenant.id))
        self.message_user(request, f"Cache flushed for {queryset.count()} tenant(s).")
