import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('logistics', '0009_routeplan_allocation_run_and_more'),
    ]

    operations = [
        migrations.RenameModel(old_name='Warehouse', new_name='Supplier'),
        migrations.RemoveField(model_name='supplier', name='storage_capacity_kg'),
        migrations.RenameModel(old_name='WarehouseDealerLeg', new_name='SupplierDealerRoute'),
        migrations.RenameField(model_name='supplierdealerroute', old_name='warehouse', new_name='supplier'),
        migrations.AlterModelOptions(
            name='supplierdealerroute',
            options={'ordering': ['supplier__district', 'sequence']},
        ),
        migrations.AlterUniqueTogether(
            name='supplierdealerroute',
            unique_together={('route', 'supplier', 'agro_dealer')},
        ),
    ]
