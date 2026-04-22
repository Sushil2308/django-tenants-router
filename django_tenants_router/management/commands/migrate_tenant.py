"""
migrate_tenant
==============
Runs Django migrations for a specific tenant database.

Usage::

    python manage.py migrate_tenant --tenant-db acme_corp
    python manage.py migrate_tenant --tenant-db acme_corp --app myapp
    python manage.py migrate_tenant --tenant-db acme_corp --fake-initial
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run Django migrations for a specific tenant database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-db",
            required=True,
            dest="tenant_db",
            help="The Django DATABASES alias of the tenant to migrate.",
        )
        parser.add_argument(
            "--app",
            dest="app_label",
            default=None,
            help="Optional: migrate only a specific app.",
        )
        parser.add_argument(
            "--fake",
            action="store_true",
            default=False,
            help="Mark migrations as run without running them.",
        )
        parser.add_argument(
            "--fake-initial",
            action="store_true",
            default=False,
            dest="fake_initial",
            help="Fake the initial migration if tables already exist.",
        )
        parser.add_argument(
            "--run-syncdb",
            action="store_true",
            default=False,
            dest="run_syncdb",
            help="Create tables for apps without migrations.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        tenant_db = options["tenant_db"]
        root_db = getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("ROOT_DB", "default")

        if tenant_db == root_db:
            raise CommandError(
                f"'{tenant_db}' is the root database. "
                "Use the standard `migrate` command for the root DB."
            )

        if tenant_db not in settings.DATABASES:
            raise CommandError(
                f"Database alias '{tenant_db}' is not in settings.DATABASES. "
                "Make sure the tenant exists and is active."
            )

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nMigrating tenant DB: {tenant_db}\n"))

        kwargs = {
            "database": tenant_db,
            "fake": options["fake"],
            "fake_initial": options["fake_initial"],
            "run_syncdb": options["run_syncdb"],
            "verbosity": options["verbosity"],
            "interactive": False,
        }

        if options["app_label"]:
            call_command("migrate", options["app_label"], **kwargs)
        else:
            call_command("migrate", **kwargs)

        self.stdout.write(
            self.style.SUCCESS(f"\n✓ Migrations complete for '{tenant_db}'.\n")
        )
