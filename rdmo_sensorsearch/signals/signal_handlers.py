import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from rdmo.projects.models import Value

from rdmo_sensorsearch.signals.handler_post_save import handle_post_save
from rdmo_sensorsearch.signals.utils import _is_muted

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Value)
def post_save_project_values(sender, instance, **kwargs):
    if _is_muted():
        return
    if instance is None:
        return
    logger.debug("Triggering post_save_project_values")
    handle_post_save(instance)
