import logging

from rdmo_sensorsearch.auth import get_sms_auth_token
from rdmo_sensorsearch.contracts import BackendFailure, ConfigurationSearch
from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider

logger = logging.getLogger(__name__)


class SensorManagementSystemConfigurationProvider(BaseRemoteSearchProvider):
    """
    Searches a Sensor Management System (SMS) API for configurations.

    The SMS API exposes configurations as first-class resources. This provider
    searches them by label and returns one option per matching configuration.
    """

    uses_auth_token = True

    option_id = "{id_prefix}:{id}"
    option_text = "{prefix}({id}): {label}{project}{pid}"

    def __init__(self, *, backend: ConfigurationSearch, **kwargs):
        super().__init__(**kwargs)
        self.backend = backend

    def get_options(self, project, search=None, user=None, site=None):
        if search is None:
            return []

        response = self.backend.search_configurations(
            search,
            limit=self.max_hits,
            auth_token=getattr(self, "auth_token", None) or get_sms_auth_token(user=user),
        )
        if isinstance(response, BackendFailure):
            logger.debug("SMS search failed: %s", response.errors)
            return []
        records = response.value

        return [
            {
                "id": self.option_id.format(id_prefix=self.id_prefix, id=configuration.identifier),
                "text": self._format_configuration_text(configuration.identifier, configuration.attributes),
            }
            for configuration in records
        ]

    def _format_configuration_text(self, configuration_id: str, attrs: dict) -> str:
        project = f" [{attrs['project']}]" if attrs.get("project") else ""
        persistent_identifier = attrs.get("persistent_identifier")
        pid = f" ({persistent_identifier})" if persistent_identifier else ""
        return self.option_text.format(
            prefix=self.text_prefix,
            id=configuration_id,
            label=attrs.get("label", ""),
            project=project,
            pid=pid,
        )
