from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0002_warehouseallocation_agrodealerallocation'),
    ]

    operations = [
        migrations.CreateModel(
            name='WarehouseDispatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('input_type', models.CharField(choices=[('fertilizer_d', 'Fertilizer (D Compound)'), ('fertilizer_urea', 'Fertilizer (Urea)'), ('seed_maize', 'Seed (Maize)'), ('seed_other', 'Seed (Other)')], max_length=20)),
                ('quantity_kg', models.DecimalField(decimal_places=2, max_digits=10)),
                ('dispatched_at', models.DateTimeField(auto_now_add=True)),
                ('agro_dealer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='warehouse_dispatches', to='logistics.agrodealer')),
                ('dispatched_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='warehouse_dispatches', to=settings.AUTH_USER_MODEL)),
                ('warehouse', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='dispatches', to='logistics.supplier')),
            ],
            options={'ordering': ['-dispatched_at']},
        ),
    ]