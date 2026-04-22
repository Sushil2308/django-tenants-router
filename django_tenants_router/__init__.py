"""
django-tenants-router
=====================
A Django library for multi-tenant database routing with Redis caching.

Usage:
    INSTALLED_APPS = [
        ...
        'django_tenants_router',
    ]

    TENANT_ROUTER_CONFIG = {
        'ROOT_DB': 'default',
        'REDIS_URL': 'redis://localhost:6379/0',
        'CACHE_TTL': 300,
    }
"""

default_app_config = "django_tenants_router.apps.DjangoTenantsRouterConfig"

__version__ = "1.0.0"
__author__ = "django-tenants-router"
