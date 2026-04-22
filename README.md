# django-tenants-router

A production-ready Django library for **multi-tenant database routing** with a Redis caching layer, automatic tenant resolution middleware, and developer-friendly test utilities.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Configuration Reference](#configuration-reference)
5. [How It Works](#how-it-works)
6. [Management Commands](#management-commands)
7. [Middleware](#middleware)
8. [Context Managers & Decorators](#context-managers--decorators)
9. [DRF Integration](#drf-integration)
10. [Redis Caching](#redis-caching)
11. [Testing](#testing)
12. [Admin Interface](#admin-interface)
13. [CI/CD & Scripts](#cicd--scripts)
14. [Security Notes](#security-notes)

---

## Architecture Overview

```
                          ┌───────────────────────────────┐
                          │         ROOT DATABASE          │
                          │  (default DB / "router DB")   │
                          │                                │
                          │  • tenants_tenant              │
                          │  • tenants_tenant_db_config    │
                          └──────────────┬────────────────┘
                                         │  reads at startup
                                         ▼
                          ┌───────────────────────────────┐
                          │       TenantRegistry           │
                          │   (in-memory: id → alias)     │
                          └──────────────┬────────────────┘
                                         │
               ┌─────────────────────────┼─────────────────────────┐
               │                         │                         │
               ▼                         ▼                         ▼
        ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
        │  Tenant A   │          │  Tenant B   │          │  Tenant C   │
        │  (acme_db)  │          │ (globex_db) │          │  (init_db)  │
        └─────────────┘          └─────────────┘          └─────────────┘

           Redis cache layer sits in front of registry lookups (optional).
```

- **Root DB** stores only tenant configuration — no business data.
- **Tenant DBs** store all application data. They are isolated from each other.
- **Redis** caches `tenant_id → db_alias` lookups for sub-millisecond routing.
- **TenantMiddleware** resolves the tenant on every request and sets a thread-local DB alias.
- **TenantDatabaseRouter** routes all ORM calls to the correct DB automatically.

---

## Installation

```bash
pip install django-tenants-router

# With Redis support (recommended):
pip install "django-tenants-router[redis]"

# With DRF integration:
pip install "django-tenants-router[drf]"

# Everything:
pip install "django-tenants-router[all]"
```

---

## Quick Start

### 1. Add to `INSTALLED_APPS`

```python
INSTALLED_APPS = [
    ...
    "django_tenants_router",
]
```

### 2. Configure settings

```python
DATABASES = {
    "default": {  # Root DB — stores tenant configs only
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "root_db",
        "USER": "postgres",
        "PASSWORD": "secret",
        "HOST": "localhost",
        "PORT": "5432",
    }
    # Tenant DBs are added dynamically at startup from TenantDatabaseConfig rows.
}

DATABASE_ROUTERS = ["django_tenants_router.router.TenantDatabaseRouter"]

MIDDLEWARE = [
    ...
    "django_tenants_router.middleware.TenantMiddleware",
]

TENANT_ROUTER_CONFIG = {
    "ROOT_DB": "default",
    "REDIS_URL": "redis://localhost:6379/0",
    "CACHE_TTL": 300,                          # seconds
    "CACHE_KEY_PREFIX": "tenants",
    "TENANT_HEADER": "HTTP_X_TENANT_ID",       # HTTP header (Django META format)
    "TENANT_REQUIRED": False,                  # True → return 400/403 if no tenant
    "TENANT_EXEMPT_PATHS": ["/admin/", "/health/"],
    "COMMON_APPS": ("admin", "auth", "contenttypes", "sessions") # Add the applications which you want migrate as common
}
```

### 3. Run root DB migrations

```bash
python manage.py migrate          # migrates root DB (default) only
```

### 4. Create your first tenant

```bash
python manage.py create_tenant \
    --name "ACME Corp" \
    --slug acme \
    --db-host localhost \
    --db-name acme_db \
    --db-user acme_user \
    --db-password secret \
    --run-migrations
```

### 5. Make API calls with tenant ID in header

```http
GET /api/orders/
X-Tenant-ID: <tenant-uuid>
```

All ORM calls in that request now automatically hit the ACME tenant database.

---

## Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `ROOT_DB` | `"default"` | Django DB alias for the root / router database. |
| `REDIS_URL` | `None` | Redis connection URL. Omit to disable caching. |
| `CACHE_TTL` | `300` | Cache TTL in seconds. |
| `CACHE_KEY_PREFIX` | `"tenants"` | Redis key namespace. |
| `TENANT_HEADER` | `"HTTP_X_TENANT_ID"` | Django META header name (HTTP_* format). |
| `TENANT_REQUIRED` | `False` | Reject requests with no resolvable tenant. |
| `TENANT_EXEMPT_PATHS` | `["/admin/", "/health/"]` | Paths that bypass tenant resolution. |
| `ENCRYPTION_DECYPTION_KEY` | `Generated Key` | Pass you Fernet Key to Encrypt/Decrypt Tenants DB Passwords
| `COMMON_APPS`|  `("admin", "auth", "contenttypes", "sessions")` | Here you need to define the app names which will use as a common to migrate in both root db and tenant db as well
---

## How It Works

### Startup

1. `DjangoTenantsRouterConfig.ready()` fires.
2. `TenantRegistry.load_from_db()` reads all active `Tenant` + `TenantDatabaseConfig` rows from the root DB.
3. Each tenant's DB config is injected into `settings.DATABASES` and Django's connection handler.

### Per-request flow

```
Request arrives
     │
     ▼
TenantMiddleware
     │  resolves tenant_id from: header → JWT → query param → session
     │
     ├─ Redis hit?  →  db_alias  ─────────────────────────────────┐
     ├─ Registry hit?  →  db_alias + write to Redis  ─────────────┤
     └─ DB fallback  →  db_alias + register + cache  ─────────────┤
                                                                   │
                                                        set_tenant_db(db_alias)
                                                                   │
                                                               view runs
                                                                   │
                                                     ORM → TenantDatabaseRouter
                                                     routes to correct tenant DB
                                                                   │
                                                        response returned
                                                                   │
                                                         clear_tenant_db()
```

---

## Management Commands

### `migrate` (standard)

Migrates only the root DB (due to `allow_migrate` rules in the router):

```bash
python manage.py migrate
```

### `migrate_tenant`

Migrates a single tenant database:

```bash
python manage.py migrate_tenant --tenant-db acme
python manage.py migrate_tenant --tenant-db acme --app orders
python manage.py migrate_tenant --tenant-db acme --fake-initial
```

### `migrate_all_tenants`

Migrates every registered tenant database (skips root DB):

```bash
python manage.py migrate_all_tenants
python manage.py migrate_all_tenants --parallel --workers 8
python manage.py migrate_all_tenants --exclude acme staging --app orders
```

### `create_tenant`

Interactive or flag-driven tenant creation:

```bash
python manage.py create_tenant
python manage.py create_tenant \
    --name "Globex Corp" --slug globex \
    --db-host db.globex.internal --db-name globex \
    --db-user globex_user --db-password s3cr3t \
    --run-migrations
```

### `tenant_status`

List all registered tenants and optionally verify connectivity:

```bash
python manage.py tenant_status
python manage.py tenant_status --ping-dbs --check-cache
```

---

## Middleware

Add to `MIDDLEWARE`:

```python
# Sync (WSGI)
"django_tenants_router.middleware.TenantMiddleware"

# Async (ASGI / Channels)
"django_tenants_router.middleware.AsyncTenantMiddleware"
```

After the middleware runs, `request.tenant_id` and `request.tenant_db` are available in your views.

---

## Context Managers & Decorators

### Manual context switching

```python
from django_tenants_router.router import tenant_db_context, tenant_context_by_id

# By alias
with tenant_db_context("tenant_acme"):
    orders = Order.objects.all()

# By tenant UUID
with tenant_context_by_id(tenant_id):
    orders = Order.objects.all()
```

### View decorators

```python
from django_tenants_router.decorators import with_tenant, with_tenant_slug

# Routes by URL kwarg
@with_tenant("tenant_id")
def order_list(request, tenant_id):
    return JsonResponse({"orders": list(Order.objects.values())})

# Routes by slug
@with_tenant_slug("tenant_slug")
def dashboard(request, tenant_slug):
    ...

# Run a function for every tenant
from django_tenants_router.decorators import for_each_tenant

@for_each_tenant()
def send_daily_report(db_alias):
    users = User.objects.using(db_alias).filter(active=True)
    ...
```

---

## DRF Integration

```python
from django_tenants_router.drf import TenantModelViewSet, TenantPermission

class OrderViewSet(TenantModelViewSet):
    serializer_class = OrderSerializer
    queryset = Order.objects.all()
    # All queryset operations are automatically scoped to the tenant DB.
    # Response includes _tenant metadata (id, plan).
```

URL pattern:

```python
router.register(r"tenants/(?P<tenant_id>[^/.]+)/orders", OrderViewSet)
```

---

## Redis Caching

```python
from django_tenants_router.cache import (
    cache_tenant_db,
    get_cached_tenant_db,
    invalidate_tenant,
    cache_tenant_metadata,
    cache_health_check,
    flush_all_tenant_cache,
)

# Warm the cache manually
cache_tenant_db("uuid-1234", "tenant_acme")

# Lookup
alias = get_cached_tenant_db("uuid-1234")

# Invalidate after config change
invalidate_tenant("uuid-1234")

# Health check
print(cache_health_check())
# {'status': 'ok', 'redis_version': '7.0.0', 'uptime_seconds': 86400}
```

If Redis is unavailable, all cache operations silently no-op. The library **always falls back** to the in-memory registry or root DB.

---

## Testing

### `TenantTestCase`

```python
from django_tenants_router.test_utils import TenantTestCase

class OrderTest(TenantTestCase):
    tenant_db_alias = "tenant_acme"

    def test_create_order(self):
        with self.tenant_context():
            order = Order.objects.create(amount=100)
            self.assertEqual(Order.objects.count(), 1)

    def test_queryset_on_correct_db(self):
        qs = Order.objects.using(self.tenant_db_alias).all()
        self.assertQueryRunsOnTenantDB(qs)
```

### `MockTenantMixin`

Patch the registry so tests never need real DB rows:

```python
from django_tenants_router.test_utils import MockTenantMixin

class MyTest(MockTenantMixin, TestCase):
    mock_tenants = {
        "uuid-111": "tenant_alpha",
        "uuid-222": "tenant_beta",
    }

    def test_something(self):
        from django_tenants_router.registry import TenantRegistry
        alias = TenantRegistry.get_db_for_tenant_id("uuid-111")
        self.assertEqual(alias, "tenant_alpha")
```

### `override_tenant_db`

```python
from django_tenants_router.test_utils import override_tenant_db

with override_tenant_db("tenant_acme"):
    # ORM calls go to tenant_acme
    ...
```

### Running the test suite

```bash
pip install -e ".[dev]"
pytest
pytest --cov=django_tenants_router --cov-report=term-missing
```

---

## Admin Interface

The Django admin includes:
- **Tenant list** with live DB connectivity badge.
- **Inline DB config editor** on the Tenant change page.
- **Bulk actions**: activate, deactivate, flush Redis cache.

---

## CI/CD & Scripts

```bash
# In your Dockerfile or entrypoint:
python manage.py migrate                        # root DB
python scripts/migrate_all_tenants.py --parallel --workers 4
```

Or via the management command:

```bash
python manage.py migrate_all_tenants --parallel --workers 4
```

---

## Security Notes

- **Passwords in DB**:
  - *Step 1*
        ```bash
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode())
    ```
  - *Step 2*
    ```bash
    TENANT_ROUTER_CONFIG = {
        "ENCRYPTION_DECYPTION_KEY": "bkey.....="
    }
    ```
- **Cross-tenant isolation**: The router blocks cross-tenant ORM relations at the `allow_relation` level.
- **TENANT_REQUIRED**: Set to `True` in production APIs so unauthenticated callers cannot accidentally hit the default DB.
- **Redis eviction policy**: Set `maxmemory-policy allkeys-lru` in Redis so cache keys are evicted gracefully under memory pressure.

---

## License

MIT
