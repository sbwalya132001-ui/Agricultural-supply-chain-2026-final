#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fisp_system.settings')
django.setup()

from farmers.models import Farmer, FarmerInputUsage
from decimal import Decimal
from datetime import datetime

# Create sample farmers
districts = ['Lilongwe', 'Mchinji', 'Blantyre']
for i, district in enumerate(districts):
    for j in range(3):
        farmer_num = i*3+j+1
        farmer, created = Farmer.objects.get_or_create(
            national_id=f"ID{farmer_num:04d}",
            defaults={
                'first_name': f'John',
                'last_name': f'Farmer{farmer_num}',
                'district': district,
                'farm_size_hectares': Decimal('2.5'),
                'primary_crop': 'maize'
            }
        )
        if created:
            print(f"Created farmer: {farmer.first_name} {farmer.last_name} in {district}")

print(f"Total farmers: {Farmer.objects.count()}")

# Create historical usage data for multiple seasons
SEASONS = ['2017/2018', '2018/2019', '2019/2020', '2020/2021', 
           '2021/2022', '2022/2023', '2023/2024', '2024/2025']
INPUT_TYPES = [input_type for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES]

created_count = 0
farmers = list(Farmer.objects.all())

for farmer in farmers:
    for input_type in INPUT_TYPES:
        for season in SEASONS:
            # Generate realistic usage data with slight variation
            base_qty = 100 + (hash(f"{farmer.id}{input_type}") % 100)
            usage_qty = base_qty + (SEASONS.index(season) * 5)  # Add slight upward trend
            
            usage, created = FarmerInputUsage.objects.get_or_create(
                farmer=farmer,
                input_type=input_type,
                season=season,
                defaults={'quantity_kg': Decimal(str(usage_qty))}
            )
            if created:
                created_count += 1

print(f"Created {created_count} FarmerInputUsage records")
print("Test data created successfully!")
