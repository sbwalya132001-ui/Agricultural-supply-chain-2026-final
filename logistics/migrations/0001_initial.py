from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('farmers', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RoutePlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='FISP delivery route', max_length=100)),
                ('start_latitude', models.FloatField(blank=True, null=True)),
                ('start_longitude', models.FloatField(blank=True, null=True)),
                ('total_distance_km', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='RouteStop',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sequence', models.PositiveIntegerField()),
                ('distance_from_previous_km', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('allocated_quantity_kg', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('farmer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='route_stops', to='farmers.farmer')),
                ('route', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stops', to='logistics.routeplan')),
            ],
            options={'ordering': ['sequence'], 'unique_together': {('route', 'sequence')}},
        ),
    ]
