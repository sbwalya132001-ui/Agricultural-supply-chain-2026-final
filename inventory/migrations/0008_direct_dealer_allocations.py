import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def copy_dealer_allocations(apps, schema_editor):
    AgroDealerAllocation = apps.get_model('inventory', 'AgroDealerAllocation')
    DealerInputAllocation = apps.get_model('inventory', 'DealerInputAllocation')

    for row in AgroDealerAllocation.objects.select_related(
        'warehouse_allocation__forecast',
        'agro_dealer',
    ).iterator():
        source = row.warehouse_allocation
        DealerInputAllocation.objects.create(
            supplier_id=source.warehouse_id,
            forecast_id=source.forecast_id,
            input_type=source.input_type,
            agro_dealer_id=row.agro_dealer_id,
            quantity_kg=row.quantity_kg,
            allocation_run=row.allocation_run,
            created_at=row.created_at,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0007_dealerstockreceipt'),
        ('logistics', '0010_supplier_refactor'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DealerInputAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('input_type', models.CharField(choices=[('fertilizer_d', 'Fertilizer (D Compound)'), ('fertilizer_urea', 'Fertilizer (Urea)'), ('seed_maize', 'Seed (Maize)'), ('seed_other', 'Seed (Other)')], max_length=20)),
                ('quantity_kg', models.DecimalField(decimal_places=2, max_digits=10)),
                ('allocation_run', models.CharField(max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('forecast', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='dealer_allocations', to='forecasting.forecast')),
                ('supplier', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='dealer_allocations', to='logistics.supplier')),
                ('agro_dealer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='input_allocations', to='logistics.agrodealer')),
            ],
            options={'ordering': ['allocation_run', 'agro_dealer__district', 'agro_dealer__name']},
        ),
        migrations.AddConstraint(
            model_name='dealerinputallocation',
            constraint=models.UniqueConstraint(fields=('supplier', 'forecast', 'agro_dealer', 'allocation_run'), name='unique_direct_dealer_supplier_allocation'),
        ),
        migrations.RunPython(copy_dealer_allocations, migrations.RunPython.noop),
        migrations.RenameModel(old_name='WarehouseDispatch', new_name='SupplierDispatch'),
        migrations.RenameField(model_name='supplierdispatch', old_name='warehouse', new_name='supplier'),
        migrations.AlterField(
            model_name='supplierdispatch',
            name='supplier',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='dispatches', to='logistics.supplier'),
        ),
        migrations.AddField(
            model_name='supplierdispatch',
            name='allocation_run',
            field=models.CharField(blank=True, max_length=50, default=''),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='supplierdispatch',
            name='agro_dealer',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='supplier_dispatches', to='logistics.agrodealer'),
        ),
        migrations.AlterField(
            model_name='supplierdispatch',
            name='dispatched_by',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='supplier_dispatches', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='supplierdispatch',
            name='received_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='dealer_stock_receipts', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='dealerstockreceipt',
            name='dispatch',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='receipts', to='inventory.supplierdispatch'),
        ),
        migrations.DeleteModel(name='AgroDealerAllocation'),
        migrations.DeleteModel(name='WarehouseAllocation'),
    ]
