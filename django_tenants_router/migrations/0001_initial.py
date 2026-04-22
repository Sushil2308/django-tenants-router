import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("schema_name", models.CharField(help_text="Unique identifier used as the DB alias for this tenant.", max_length=100, unique=True)),
                ("plan", models.CharField(default="free", help_text="Subscription plan (e.g. free, pro, enterprise).", max_length=50)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={"db_table": "tenants_tenant", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="TenantDatabaseConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("engine", models.CharField(default="django.db.backends.postgresql", max_length=100)),
                ("host", models.CharField(max_length=255)),
                ("port", models.PositiveIntegerField(default=5432)),
                ("db_name", models.CharField(max_length=100)),
                ("db_user", models.CharField(max_length=100)),
                ("db_password", models.CharField(max_length=255)),
                ("options", models.JSONField(blank=True, default=dict, help_text="Extra OPTIONS passed to the Django DB config.")),
                ("conn_max_age", models.IntegerField(default=60, help_text="Persistent connection timeout in seconds.")),
                ("is_active", models.BooleanField(default=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="db_config",
                        to="django_tenants_router.tenant",
                    ),
                ),
            ],
            options={"db_table": "tenants_tenant_db_config"},
        ),
    ]
