from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from accounts.decorators import ROLE_DEALER, ROLE_SUPPLIER
from accounts.models import UserProfile
from logistics.models import AgroDealer, Supplier


DISTRICT_SETUP = [
    {
        'district': 'Choma',
        'supplier_user': 'supplier_choma',
        'supplier_name': 'Choma District Supplier',
        'supplier_password': 'ChomaSupplier2026!',
        'dealer_user': 'dealer_choma',
        'dealer_name': 'Choma Agro-Dealer',
        'dealer_password': 'ChomaDealer2026!',
        'latitude': -16.806, 'longitude': 27.440,
    },
    {
        'district': 'Kalomo',
        'supplier_user': 'supplier_kalomo',
        'supplier_name': 'Kalomo District Supplier',
        'supplier_password': 'KalomoSupplier2026!',
        'dealer_user': 'dealer_kalomo',
        'dealer_name': 'Kalomo Agro-Dealer',
        'dealer_password': 'KalomoDealer2026!',
        'latitude': -17.047, 'longitude': 26.495,
    },
    {
        'district': 'Monze',
        'supplier_user': 'supplier_monze',
        'supplier_name': 'Monze District Supplier',
        'supplier_password': 'MonzeSupplier2026!',
        'dealer_user': 'dealer_monze',
        'dealer_name': 'Monze Agro-Dealer',
        'dealer_password': 'MonzeDealer2026!',
        'latitude': -16.281, 'longitude': 27.484,
    },
    {
        'district': 'Pemba',
        'supplier_user': 'supplier_pemba',
        'supplier_name': 'Pemba District Supplier',
        'supplier_password': 'PembaSupplier2026!',
        'dealer_user': 'dealer_pemba',
        'dealer_name': 'Pemba Agro-Dealer',
        'dealer_password': 'PembaDealer2026!',
        'latitude': -16.777, 'longitude': 27.910,
    },
]


class Command(BaseCommand):
    help = 'Create active supplier and agro-dealer accounts for each forecast district so allocation checks pass and map markers are populated.'

    def handle(self, *args, **options):
        supplier_group, _ = Group.objects.get_or_create(name=ROLE_SUPPLIER)
        dealer_group, _ = Group.objects.get_or_create(name=ROLE_DEALER)
        created_accounts = []

        for config in DISTRICT_SETUP:
            district = config['district']

            supplier_user, supplier_user_created = User.objects.get_or_create(
                username=config['supplier_user'],
                defaults={'email': f"{config['supplier_user']}@fisp.local", 'is_active': True},
            )
            if supplier_user_created or not supplier_user.has_usable_password():
                supplier_user.set_password(config['supplier_password'])
                supplier_user.save(update_fields=['password'])
            supplier_user.groups.clear()
            supplier_user.groups.add(supplier_group)
            profile, _ = UserProfile.objects.get_or_create(user=supplier_user, defaults={'district': district})
            profile.district = district
            profile.save(update_fields=['district'])

            supplier, supplier_created = Supplier.objects.get_or_create(
                name=config['supplier_name'],
                district=district,
                defaults={
                    'latitude': config['latitude'],
                    'longitude': config['longitude'],
                    'current_stock_kg': 5000,
                    'stock_fertilizer_d_kg': 1500,
                    'stock_fertilizer_urea_kg': 1500,
                    'stock_seed_maize_kg': 2000,
                    'stock_seed_other_kg': 500,
                    'stock_seed_soybeans_kg': 250,
                    'stock_seed_sunflower_kg': 250,
                    'stock_seed_popcorn_kg': 0,
                    'is_active': True,
                },
            )
            supplier.latitude = config['latitude']
            supplier.longitude = config['longitude']
            supplier.is_active = True
            supplier.current_stock_kg = 5000
            supplier.stock_fertilizer_d_kg = 1500
            supplier.stock_fertilizer_urea_kg = 1500
            supplier.stock_seed_maize_kg = 2000
            supplier.stock_seed_other_kg = 500
            supplier.stock_seed_soybeans_kg = 250
            supplier.stock_seed_sunflower_kg = 250
            supplier.stock_seed_popcorn_kg = 0
            supplier.save()

            dealer_user, dealer_user_created = User.objects.get_or_create(
                username=config['dealer_user'],
                defaults={'email': f"{config['dealer_user']}@fisp.local", 'is_active': True},
            )
            if dealer_user_created or not dealer_user.has_usable_password():
                dealer_user.set_password(config['dealer_password'])
                dealer_user.save(update_fields=['password'])
            dealer_user.groups.clear()
            dealer_user.groups.add(dealer_group)

            dealer, dealer_created = AgroDealer.objects.get_or_create(
                name=config['dealer_name'],
                district=district,
                defaults={
                    'user': dealer_user,
                    'latitude': config['latitude'] + 0.02,
                    'longitude': config['longitude'] + 0.01,
                    'stock_quantity_kg': 1200,
                    'stock_fertilizer_d_kg': 350,
                    'stock_fertilizer_urea_kg': 350,
                    'stock_seed_maize_kg': 500,
                    'stock_seed_other_kg': 100,
                    'stock_seed_soybeans_kg': 80,
                    'stock_seed_sunflower_kg': 80,
                    'stock_seed_popcorn_kg': 20,
                },
            )
            dealer.user = dealer_user
            dealer.latitude = config['latitude'] + 0.02
            dealer.longitude = config['longitude'] + 0.01
            dealer.stock_quantity_kg = 1200
            dealer.stock_fertilizer_d_kg = 350
            dealer.stock_fertilizer_urea_kg = 350
            dealer.stock_seed_maize_kg = 500
            dealer.stock_seed_other_kg = 100
            dealer.stock_seed_soybeans_kg = 80
            dealer.stock_seed_sunflower_kg = 80
            dealer.stock_seed_popcorn_kg = 20
            dealer.save()

            created_accounts.append({
                'district': district,
                'supplier_user': supplier_user.username,
                'supplier_password': config['supplier_password'],
                'dealer_user': dealer_user.username,
                'dealer_password': config['dealer_password'],
                'supplier_record': supplier.name,
                'dealer_record': dealer.name,
            })

        self.stdout.write(self.style.SUCCESS(f'Created/updated {len(created_accounts)} supplier/dealer districts.'))
        for account in created_accounts:
            self.stdout.write(
                f"{account['district']}: supplier={account['supplier_user']} / {account['supplier_password']} | "
                f"dealer={account['dealer_user']} / {account['dealer_password']}"
            )
