"""
create_tenant
=============
Interactive command to create a new tenant and its database configuration.

Usage::

    python manage.py create_tenant
    python manage.py create_tenant --name "ACME Corp" --slug acme --db-host localhost --db-name acme_db --db-user acme_user --db-password secret --run-migrations
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create a new tenant and optionally run migrations on their database."

    def add_arguments(self, parser):
        parser.add_argument("--name", dest="name", default=None)
        parser.add_argument("--slug", dest="slug", default=None)
        parser.add_argument("--schema-name", dest="schema_name", default=None, help="DB alias (defaults to slug).")
        parser.add_argument("--db-engine", dest="db_engine", default="django.db.backends.postgresql")
        parser.add_argument("--db-host", dest="db_host", default=None)
        parser.add_argument("--db-port", dest="db_port", type=int, default=5432)
        parser.add_argument("--db-name", dest="db_name", default=None)
        parser.add_argument("--db-user", dest="db_user", default=None)
        parser.add_argument("--db-password", dest="db_password", default=None)
        parser.add_argument("--plan", dest="plan", default="free")
        parser.add_argument(
            "--run-migrations",
            action="store_true",
            default=False,
            dest="run_migrations",
            help="Run migrations on the new tenant DB after creation.",
        )

    def _prompt(self, prompt: str, default: str = "") -> str:
        val = input(f"{prompt} [{default}]: ").strip()
        return val or default

    def handle(self, *args, **options):
        from django.conf import settings
        from django_tenants_router.models import Tenant, TenantDatabaseConfig
        from django_tenants_router.registry import TenantRegistry

        root_db = getattr(settings, "TENANT_ROUTER_CONFIG", {}).get("ROOT_DB", "default")

        name = options["name"] or self._prompt("Tenant name")
        slug = options["slug"] or self._prompt("Tenant slug (URL-safe)", name.lower().replace(" ", "_"))
        schema_name = options["schema_name"] or self._prompt("DB alias (schema_name)", slug)

        db_host = options["db_host"] or self._prompt("DB host", "localhost")
        db_port = options["db_port"]
        db_name = options["db_name"] or self._prompt("DB name", slug)
        db_user = options["db_user"] or self._prompt("DB user", "postgres")
        db_password = options["db_password"] or self._prompt("DB password")
        db_engine = options["db_engine"]

        tenantConfig = getattr(settings, "TENANT_ROUTER_CONFIG", {})
        if tenantConfig.get("ENCRYPTION_DECYPTION_DB_PASSWORD", False):
            from cryptography.fernet import Fernet
            key = tenantConfig.get("ENCRYPTION_DECYPTION_KEY")
            if key:
                cipher = Fernet(key)
                db_password = cipher.encrypt(db_password.encode()).decode()
        
        # Create Tenant in root DB
        tenant = Tenant.objects.using(root_db).create(
            name=name,
            slug=slug,
            schema_name=schema_name,
            plan=options["plan"],
            is_active=True,
        )

        TenantDatabaseConfig.objects.using(root_db).create(
            tenant=tenant,
            engine=db_engine,
            host=db_host,
            port=db_port,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
        )

        # Register dynamically
        TenantRegistry.register(tenant)

        self.stdout.write(self.style.SUCCESS(f"\n✓ Tenant '{name}' created (id={tenant.id})."))

        if options["run_migrations"]:
            self.stdout.write(f"\nRunning migrations on '{schema_name}'...")
            call_command("migrate_tenant", tenant_db=schema_name, verbosity=options["verbosity"])
