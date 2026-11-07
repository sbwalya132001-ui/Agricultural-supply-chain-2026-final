from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from accounts.decorators import (
    ROLE_DEALER,
    ROLE_DISTRICT,
    ROLE_MINISTRY,
    ROLE_SUPPLIER,
)


class Command(BaseCommand):
    help = 'Create the stakeholder groups used by the FISP role-based access policy.'

    def handle(self, *args, **options):
        role_names = (
            ROLE_MINISTRY,
            ROLE_DISTRICT,
            ROLE_SUPPLIER,
            ROLE_DEALER,
        )
        for role_name in role_names:
            group, created = Group.objects.get_or_create(name=role_name)
            status = 'created' if created else 'already exists'
            self.stdout.write(f'{role_name}: {status}')
        self.stdout.write(self.style.SUCCESS('Stakeholder roles are ready.'))
