from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import F


def preserve_existing_dispatch_stock(apps, schema_editor):
    """Existing dispatches already credited dealer stock before this migration."""
    WarehouseDispatch = apps.get_model('inventory', 'WarehouseDispatch')
    WarehouseDispatch.objects.filter(received_at__isnull=True).update(
        received_at=F('dispatched_at'),
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0005_farmerallocation_agro_dealer'),
    ]

    operations = [
        migrations.AddField(
            model_name='warehousedispatch',
            name='received_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='dealer_stock_receipts',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='warehousedispatch',
            name='received_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(preserve_existing_dispatch_stock, migrations.RunPython.noop),
    ]
