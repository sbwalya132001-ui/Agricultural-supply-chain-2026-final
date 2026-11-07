from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0009_alter_dealerinputallocation_input_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='farmerallocation',
            name='collection_status',
            field=models.CharField(choices=[('awaiting_collection', 'Awaiting collection'), ('collected', 'Collected')], default='awaiting_collection', max_length=20),
        ),
        migrations.AddField(
            model_name='farmerallocation',
            name='collected_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='farmerallocation',
            name='confirmed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='confirmed_farmer_collections', to=settings.AUTH_USER_MODEL),
        ),
    ]
