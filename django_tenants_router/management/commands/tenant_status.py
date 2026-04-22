"""
tenant_status
=============
Lists all registered tenants with their DB aliases, cache status, and
optionally pings each tenant database.

Usage::

    python manage.py tenant_status
    python manage.py tenant_status --ping-dbs
    python manage.py tenant_status --check-cache
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Display status of all registered tenants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ping-dbs",
            action="store_true",
            default=False,
            dest="ping_dbs",
            help="Attempt a SELECT 1 on each tenant DB to verify connectivity.",
        )
        parser.add_argument(
            "--check-cache",
            action="store_true",
            default=False,
            dest="check_cache",
            help="Check Redis cache health.",
        )

    def handle(self, *args, **options):
        from django_tenants_router.cache import cache_health_check
        from django_tenants_router.registry import TenantRegistry

        tenants = TenantRegistry.all_tenants()

        if not tenants:
            self.stdout.write(self.style.WARNING("No tenants registered."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{'TENANT':<30} {'SLUG':<20} {'DB ALIAS':<25} {'PLAN':<12} {'DB STATUS'}\n"))
        self.stdout.write("-" * 110)

        for tenant in tenants:
            alias = tenant.db_alias
            db_status = ""

            if options["ping_dbs"]:
                try:
                    from django.db import connections
                    with connections[alias].cursor() as cursor:
                        cursor.execute("SELECT 1")
                    db_status = self.style.SUCCESS("✓ OK")
                except Exception as exc:
                    db_status = self.style.ERROR(f"✗ {exc}")
            else:
                db_status = self.style.SQL_KEYWORD("(not checked)")

            self.stdout.write(
                f"{str(tenant.name):<30} {str(tenant.slug):<20} {alias:<25} {tenant.plan:<12} {db_status}"
            )

        self.stdout.write(f"\nTotal: {len(tenants)} tenant(s)\n")

        if options["check_cache"]:
            health = cache_health_check()
            status = health.get("status", "unknown")
            if status == "ok":
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Redis: OK (v{health.get('redis_version')}, uptime {health.get('uptime_seconds')}s)"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"Redis: {status} – {health.get('reason', '')}")
                )
