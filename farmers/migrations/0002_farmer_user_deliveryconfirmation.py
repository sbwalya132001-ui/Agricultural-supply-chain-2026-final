from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('farmers', '0001_initial'),
        ('logistics', '0005_routestop_road_geometry_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='farmer',
            name='user',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='farmer_profile',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name='DeliveryConfirmation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('received', 'Received'), ('issue', 'Report an issue')], max_length=20)),
                ('message', models.TextField(blank=True)),
                ('submitted_at', models.DateTimeField(auto_now=True)),
                ('route_stop', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='farmer_confirmation', to='logistics.routestop')),
            ],
            options={'ordering': ['-submitted_at']},
        ),
    ]