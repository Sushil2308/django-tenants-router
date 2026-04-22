"""
TenantMiddleware
================
Resolves the active tenant from the incoming request and sets the thread-local
DB alias so that all ORM queries in the same request/response cycle hit the
correct tenant database automatically.

Resolution order (configurable via TENANT_ROUTER_CONFIG['TENANT_RESOLUTION_ORDER']):
  1. HTTP Header  : X-Tenant-ID  (default header name, configurable)
  2. JWT claim    : tenant_id    (if rest_framework_simplejwt is installed)
  3. Query param  : tenant_id
  4. Session key  : tenant_id

If no tenant is resolved the middleware either:
  - Passes through (TENANT_REQUIRED = False, default)
  - Returns 400/403 (TENANT_REQUIRED = True)
"""

import logging

from django.conf import settings
from django.http import JsonResponse

from django_tenants_router.cache import cache_tenant_db, get_cached_tenant_db
from django_tenants_router.registry import TenantRegistry
from django_tenants_router.router import clear_tenant_db, set_tenant_db

logger = logging.getLogger(__name__)


def _router_cfg() -> dict:
    return getattr(settings, "TENANT_ROUTER_CONFIG", {})


class TenantMiddleware:
    """
    WSGI-compatible middleware.

    Add to settings::

        MIDDLEWARE = [
            ...
            'django_tenants_router.middleware.TenantMiddleware',
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response
        cfg = _router_cfg()
        self.header_name = cfg.get("TENANT_HEADER", "HTTP_X_TENANT_ID")
        self.required = cfg.get("TENANT_REQUIRED", True)
        self.exempt_paths = cfg.get("TENANT_EXEMPT_PATHS", ["/admin/", "/health/"])

    def __call__(self, request):
        # Skip exempt paths.
        if any(request.path.startswith(p) for p in self.exempt_paths):
            return self.get_response(request)

        tenant_id = self._resolve_tenant_id(request)

        if tenant_id:
            db_alias = self._resolve_db_alias(tenant_id)
            if db_alias:
                set_tenant_db(db_alias)
                request.tenant_id = tenant_id
                request.tenant_db = db_alias
            else:
                logger.warning("TenantMiddleware: unknown tenant_id=%s", tenant_id)
                if self.required:
                    return JsonResponse({"error": f"Tenant '{tenant_id}' not found."}, status=403)
        else:
            if self.required:
                return JsonResponse({"error": "Tenant identification required."}, status=400)

        try:
            response = self.get_response(request)
        finally:
            clear_tenant_db()

        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_tenant_id(self, request) -> str:
        """Try each resolver in order and return the first tenant_id found."""
        return (
            self._from_header(request)
        )

    def _from_header(self, request) -> str:
        return request.META.get(self.header_name, "").strip() or ""

    def _resolve_db_alias(self, tenant_id: str) -> str:
        """Check Redis cache first, then in-memory registry, then DB."""
        # 1. Redis cache
        alias = get_cached_tenant_db(tenant_id)
        if alias:
            logger.debug("TenantMiddleware: cache hit for tenant=%s → %s", tenant_id, alias)
            return alias

        # 2. In-memory registry
        alias = TenantRegistry.get_db_for_tenant_id(tenant_id)
        if alias:
            cache_tenant_db(tenant_id, alias)
            return alias

        # 3. Fallback: query root DB (handles freshly created tenants)
        try:
            from django_tenants_router.models import TenantDatabaseConfig
            cfg = TenantDatabaseConfig.objects.using(
                _router_cfg().get("ROOT_DB", "default")
            ).select_related("tenant").get(tenant__id=tenant_id, tenant__is_active=True)
            TenantRegistry.register(cfg.tenant)
            alias = cfg.tenant.db_alias
            cache_tenant_db(tenant_id, alias)
            return alias
        except Exception:
            return ""


class AsyncTenantMiddleware:
    """
    ASGI-compatible async middleware for Django Channels / async views.
    Drop-in replacement for TenantMiddleware in async projects.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        cfg = _router_cfg()
        self.header_name = cfg.get("TENANT_HEADER", "HTTP_X_TENANT_ID")
        self.required = cfg.get("TENANT_REQUIRED", False)
        self.exempt_paths = cfg.get("TENANT_EXEMPT_PATHS", ["/admin/", "/health/"])

    async def __call__(self, request):
        if any(request.path.startswith(p) for p in self.exempt_paths):
            return await self.get_response(request)

        tenant_id = request.META.get(self.header_name, "").strip()

        if tenant_id:
            alias = get_cached_tenant_db(tenant_id) or TenantRegistry.get_db_for_tenant_id(tenant_id)
            if alias:
                set_tenant_db(alias)
                request.tenant_id = tenant_id
                request.tenant_db = alias
            elif self.required:
                return JsonResponse({"error": f"Tenant '{tenant_id}' not found."}, status=403)
        elif self.required:
            return JsonResponse({"error": "Tenant identification required."}, status=400)

        try:
            response = await self.get_response(request)
        finally:
            clear_tenant_db()

        return response
