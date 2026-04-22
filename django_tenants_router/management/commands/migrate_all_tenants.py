"""
migrate_all_tenants
===================
Runs Django migrations across ALL active tenant databases (skips root DB).

Usage::

    python manage.py migrate_all_tenants
    python manage.py migrate_all_tenants --parallel
    python manage.py migrate_all_tenants --exclude acme_corp staging_db
    python manage.py migrate_all_tenants --app orders
"""

import concurrent.futures
import traceback

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


def _migrate_one(alias: str, app_label: str, fake: bool, fake_initial: bool, verbosity: int) -> tuple:
    """Run migration for a single alias. Returns (alias, success, error_msg)."""
    try:
        kwargs = {
            "database": alias,
            "fake": fake,
            "fake_initial": fake_initial,
            "verbosity": verbosity,
            "interactive": False,
        }
        if app_label:
            call_command("migrate", app_label, **kwargs)
        else:
            call_command("migrate", **kwargs)
        return alias, True, None
    except Exception as exc:
        return alias, False, traceback.format_exc()


class Command(BaseCommand):
    help = "Run Django migrations for every active tenant database (skips root DB)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            dest="app_label",
            default=None,
            help="Migrate only a specific app for all tenants.",
        )
        parser.add_argument(
            "--exclude",
            nargs="+",
            dest="exclude",
            default=[],
            help="DB aliases to skip.",
        )
        parser.add_argument(
            "--parallel",
            action="store_true",
            default=False,
            help="Run migrations in parallel using a thread pool.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=4,
            dest="workers",
            help="Number of parallel workers (default: 4). Used with --parallel.",
        )
        parser.add_argument(
            "--fake",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--fake-initial",
            action="store_true",
            default=False,
            dest="fake_initial",
        )

    def handle(self, *args, **options):
        from django_tenants_router.registry import TenantRegistry

        root_db = getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("ROOT_DB", "default")
        excludes = set(options["exclude"]) | {root_db}

        aliases = [a for a in TenantRegistry.all_tenant_aliases() if a not in excludes]

        if not aliases:
            self.stdout.write(self.style.WARNING("No tenant databases found to migrate."))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nMigrating {len(aliases)} tenant database(s)...\n"
            )
        )

        parallel = options["parallel"]
        workers = options["workers"]
        app_label = options["app_label"]
        fake = options["fake"]
        fake_initial = options["fake_initial"]
        verbosity = options["verbosity"]

        results = []

        if parallel:
            self.stdout.write(f"  Running in parallel with {workers} worker(s).\n")
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_migrate_one, alias, app_label, fake, fake_initial, verbosity): alias
                    for alias in aliases
                }
                for future in concurrent.futures.as_completed(futures):
                    results.append(future.result())
        else:
            for alias in aliases:
                self.stdout.write(f"  → {alias}")
                results.append(_migrate_one(alias, app_label, fake, fake_initial, verbosity))

        # Summary
        successes = [r for r in results if r[1]]
        failures = [r for r in results if not r[1]]

        self.stdout.write(
            self.style.SUCCESS(f"\n✓ {len(successes)} tenant(s) migrated successfully.")
        )

        if failures:
            self.stdout.write(
                self.style.ERROR(f"\n✗ {len(failures)} tenant(s) failed:\n")
            )
            for alias, _, err in failures:
                self.stdout.write(self.style.ERROR(f"  [{alias}]\n{err}\n"))
