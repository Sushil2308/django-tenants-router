"""
DRF Integration
===============
Optional Django REST Framework integration.
Provides TenantModelViewSet and TenantPermission.
Only imported if djangorestframework is installed.
"""

try:
    from rest_framework import permissions, viewsets
    from rest_framework.exceptions import NotFound, PermissionDenied

    from django_tenants_router.cache import (
        cache_tenant_db,
        cache_tenant_metadata,
        get_cached_tenant_db,
        get_cached_tenant_metadata,
    )
    from django_tenants_router.registry import TenantRegistry
    from django_tenants_router.router import set_tenant_db, clear_tenant_db

    class TenantPermission(permissions.BasePermission):
        """
        Ensures the requesting user's tenant_id matches the URL tenant.
        Attach to any viewset that needs per-tenant authorization.
        """

        message = "You do not have permission to access this tenant's data."

        def has_permission(self, request, view):
            request_tenant = getattr(request, "tenant_id", None)
            view_tenant = view.kwargs.get("tenant_id")
            if not request_tenant or not view_tenant:
                return True  # Let the viewset handle it.
            return str(request_tenant) == str(view_tenant)

    class TenantModelViewSet(viewsets.ModelViewSet):
        """
        A ModelViewSet subclass that automatically:
          - Resolves the tenant DB from the request (set by TenantMiddleware)
            or from a 'tenant_id' URL kwarg.
          - Scopes all querysets to the active tenant DB.
          - Injects tenant metadata into responses.

        Usage::

            class OrderViewSet(TenantModelViewSet):
                serializer_class = OrderSerializer
                queryset = Order.objects.all()
        """

        tenant_id_kwarg = "tenant_id"
        permission_classes = [permissions.IsAuthenticated, TenantPermission]

        def _resolve_tenant_db(self) -> str:
            """Resolve the DB alias to use for this request."""
            # 1. Middleware already set it.
            tenant_db = getattr(self.request, "tenant_db", None)
            if tenant_db:
                return tenant_db

            # 2. URL kwarg.
            tenant_id = self.kwargs.get(self.tenant_id_kwarg)
            if not tenant_id:
                tenant_id = self.request.query_params.get("tenant_id")
            if not tenant_id:
                raise PermissionDenied("tenant_id is required.")

            # 3. Cache → registry → 404.
            alias = get_cached_tenant_db(str(tenant_id)) or TenantRegistry.get_db_for_tenant_id(str(tenant_id))
            if not alias:
                raise NotFound(f"Tenant '{tenant_id}' not found.")

            cache_tenant_db(str(tenant_id), alias)
            return alias

        def get_queryset(self):
            db_alias = self._resolve_tenant_db()
            set_tenant_db(db_alias)
            qs = super().get_queryset()
            return qs.using(db_alias)

        def finalize_response(self, request, response, *args, **kwargs):
            response = super().finalize_response(request, response, *args, **kwargs)
            tenant_id = getattr(request, "tenant_id", None)
            if tenant_id and hasattr(response, "data") and isinstance(response.data, dict):
                meta = get_cached_tenant_metadata(str(tenant_id))
                if meta:
                    response.data["_tenant"] = {
                        "id": str(tenant_id),
                        "plan": meta.get("plan"),
                    }
            clear_tenant_db()
            return response

    class TenantReadOnlyViewSet(viewsets.ReadOnlyModelViewSet, TenantModelViewSet):
        """Read-only variant of TenantModelViewSet."""
        pass

except ImportError:
    # DRF is not installed – that is fine.
    pass
