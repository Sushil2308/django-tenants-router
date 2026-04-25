import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings
from zoneinfo import available_timezones

class Tenant(models.Model):
    """
    Represents a tenant in the system.
    Stored in the root (default) database.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Optional metadata
    schema_name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Unique identifier used as the DB alias for this tenant.",
    )
    plan = models.CharField(
        max_length=50,
        default="free",
        help_text="Subscription plan (e.g. free, pro, enterprise).",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "django_tenants_router"
        db_table = "tenants_tenant"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"


    @property
    def db_alias(self):
        """Returns the Django DATABASES alias for this tenant."""
        return self.schema_name


class TenantDatabaseConfig(models.Model):
    """
    Stores database connection parameters for a tenant.
    Stored in the root database.
    These are loaded at startup and used to dynamically configure DATABASES.
    """

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="db_config",
    )
    engine = models.CharField(
        max_length=100,
        default="django.db.backends.postgresql",
    )
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=5432)
    db_name = models.CharField(max_length=100)
    db_user = models.CharField(max_length=100)
    db_password = models.CharField(max_length=255)
    options = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra OPTIONS passed to the Django DB config.",
    )
    conn_max_age = models.IntegerField(
        default=60,
        help_text="Persistent connection timeout in seconds (0 = close after each request).",
    )
    is_active = models.BooleanField(default=True)
    atomic_request = models.BooleanField(default=False)
    auto_commit = models.BooleanField(default=True)
    conn_health_check = models.BooleanField(default=True)
    time_zone = models.CharField(
        max_length=200,
        choices=[(tz, tz) for tz in sorted(available_timezones())],
        null=False,
        blank=False,
        default="UTC",
    )

    class Meta:
        app_label = "django_tenants_router"
        db_table = "tenants_tenant_db_config"

    def __str__(self):
        return f"DB config for {self.tenant.name}"

    def to_django_db_dict(self) -> dict:
        """
            Returns a Django DATABASES-compatible dict for this tenant.
            Note:
                For security reasons, database passwords must never be stored or transmitted in plain text.
                Encryption ensures that sensitive credentials remain protected from unauthorized access.
                Here, the password is decrypted at runtime using a secure key, which is mandatory for
                maintaining confidentiality and safeguarding tenant data.
        """
        db_password = self.db_password
        tenantConfig = getattr(settings, "TENANT_ROUTER_CONFIG", {})
        if not tenantConfig.get("ENCRYPTION_DECYPTION_KEY"):
            raise ValueError("Encryption key is required to enable security on databse password")
        
        from cryptography.fernet import Fernet
        try:
            cipher = Fernet(tenantConfig.get("ENCRYPTION_DECYPTION_KEY"))
            db_password = cipher.decrypt(self.db_password).decode()
        except:
            pass
        
        return {
            "ENGINE": self.engine,
            "NAME": self.db_name,
            "USER": self.db_user,
            "PASSWORD": db_password,
            "HOST": self.host,
            "PORT": str(self.port),
            "CONN_MAX_AGE": self.conn_max_age,
            "OPTIONS": self.options,
            "TEST": {"NAME": f"test_{self.db_name}"},
            "ATOMIC_REQUESTS": self.atomic_request,
            "AUTOCOMMIT": self.auto_commit,
            "TIME_ZONE": self.time_zone,
            "CONN_HEALTH_CHECKS": self.conn_health_check,
        }