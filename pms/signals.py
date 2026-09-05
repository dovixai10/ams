from django.db.models.signals import post_save
from django.dispatch import receiver

from employees.models import Office

from .services import ensure_default_roles


@receiver(post_save, sender=Office)
def create_default_pms_roles(sender, instance, created, **kwargs):
    if instance.status == Office.Status.APPROVED:
        ensure_default_roles(instance)
