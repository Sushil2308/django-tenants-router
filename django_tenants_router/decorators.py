"""
Decorators
==========
Handy view-level decorators for tenant context management.
"""

import functools

from django_tenants_router.registry import TenantRegistry
from django_tenants_router.router import tenant_db_context


def with_tenant(tenant_id_kwarg: str = "tenant_id"):
    """
    Function/view decorator that sets the tenant DB context from a URL kwarg.

    Usage::

        @with_tenant("tenant_id")
        def my_view(request, tenant_id):
            orders = Order.objects.all()  # runs on tenant DB
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tenant_id = kwargs.get(tenant_id_kwarg)
            if not tenant_id:
                return func(*args, **kwargs)
            db_alias = TenantRegistry.get_db_for_tenant_id(str(tenant_id))
            if not db_alias:
                from django.http import JsonResponse
                return JsonResponse({"error": f"Tenant '{tenant_id}' not found."}, status=404)
            with tenant_db_context(db_alias):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def with_tenant_slug(slug_kwarg: str = "tenant_slug"):
    """
    View decorator that sets the tenant DB context from a slug URL kwarg.

    Usage::

        @with_tenant_slug("tenant_slug")
        def my_view(request, tenant_slug):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            slug = kwargs.get(slug_kwarg)
            if not slug:
                return func(*args, **kwargs)
            db_alias = TenantRegistry.get_db_for_slug(slug)
            if not db_alias:
                from django.http import JsonResponse
                return JsonResponse({"error": f"Tenant '{slug}' not found."}, status=404)
            with tenant_db_context(db_alias):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def for_each_tenant(exclude_root: bool = True):
    """
    Decorator for management-style functions that should run once per tenant.

    Usage::

        @for_each_tenant()
        def sync_data(db_alias: str):
            MyModel.objects.using(db_alias).update(synced=True)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            results = {}
            for alias in TenantRegistry.all_tenant_aliases():
                with tenant_db_context(alias):
                    results[alias] = func(*args, db_alias=alias, **kwargs)
            return results
        return wrapper
    return decorator
