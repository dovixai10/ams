from django.core.management.base import BaseCommand

from pms.models import PermissionDefinition
from pms.permission_catalog import PERMISSION_DEFINITIONS
from pms.services import ensure_default_roles

from employees.models import Office


class Command(BaseCommand):
    help = 'Seed PMS permission catalog and default roles per office'

    def handle(self, *args, **options):
        created = 0
        for key, module, name, description in PERMISSION_DEFINITIONS:
            _, was_created = PermissionDefinition.objects.update_or_create(
                key=key,
                defaults={'module': module, 'name': name, 'description': description},
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Permission catalog synced ({created} new).'))

        for office in Office.objects.filter(status=Office.Status.APPROVED):
            ensure_default_roles(office)
        self.stdout.write(self.style.SUCCESS('Default roles ensured for approved offices.'))
