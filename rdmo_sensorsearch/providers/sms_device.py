import logging
from html import escape

from rdmo_sensorsearch.auth import get_sms_auth_token
from rdmo_sensorsearch.contracts import BackendFailure, DeviceSearch
from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider

logger = logging.getLogger(__name__)


class SensorManagementSystemDeviceProvider(BaseRemoteSearchProvider):
    """
    Searches a Sensor Management System (SMS) API for devices and returns
    options for selection.

    This provider queries an SMS API endpoint for devices matching a given
    search term. It then constructs option objects containing the device's
    long name (if available), short name, serial number (if available), and
    unique ID from the SMS.

    Attributes:
        id_prefix (str):    Configured prefix for generated option IDs. This
                            prefix can be used by handlers (post_save) to query
                            more data when using different instances.
        text_prefix (str):  Configured backend and entity label, for example
                            "KIT Sensor".
        max_hits (int):     Maximum number of search results to return,
                            supplied explicitly from parsed configuration.
        base_url (str):     SMS search API endpoint supplied at construction.
    """

    uses_auth_token = True

    option_id = "{id_prefix}:{id}"
    option_text = "{prefix}({id}): {name}{serial}"

    def __init__(self, *, backend: DeviceSearch, id_prefix: str, text_prefix: str, base_url: str, max_hits: int):
        super().__init__(id_prefix=id_prefix, text_prefix=text_prefix, base_url=base_url, max_hits=max_hits)
        self.backend = backend

    def get_options(self, project, search=None, user=None, site=None):
        """
        Retrieves options based on the provided search term from the SMS.

        Args:
            project (Project):      The RDMO project object.
            search (str, optional): Search term to query the O2A Registry.
                                    Defaults to None.
            user (User, optional):  Current user object. Not used in this
                                    implementation.
            site (Site, optional):  Site object. Not used in this
                                    implementation.

        Returns:
            list: A list of option dictionaries containing "id" and "text".
        """

        if search is None:
            return []

        response = self.backend.search_devices(
            search,
            limit=self.max_hits,
            auth_token=getattr(self, "auth_token", None) or get_sms_auth_token(user=user),
        )
        if isinstance(response, BackendFailure):
            logger.debug("SMS search failed: %s", response.errors)
            return []
        records = response.value

        optionset = []

        for device in records:
            optionset.append(
                {
                    "id": self.option_id.format(id_prefix=self.id_prefix, id=device.identifier),
                    "text": self._format_device_text(device.identifier, device.attributes),
                    "help": self._format_device_help(device.attributes),
                }
            )
        return optionset

    def _format_device_text(self, device_id: str, attrs: dict) -> str:
        name = attrs.get("long_name") or attrs.get("short_name", "")
        serial = f" (s/n: {attrs['serial_number']})" if attrs.get("serial_number") else ""
        return self.option_text.format(prefix=self.text_prefix, id=device_id, name=name, serial=serial)

    def _format_device_help(self, attrs: dict) -> str:
        parts = [
            self._format_status(attrs),
            self._format_visibility(attrs),
            self._format_permission_groups(attrs),
        ]
        return " | ".join(escape(part) for part in parts if part)

    def _format_status(self, attrs: dict) -> str | None:
        return self._as_text(attrs.get("status_name") or attrs.get("status"))

    def _format_visibility(self, attrs: dict) -> str | None:
        if attrs.get("is_public") is True:
            return "Public"
        if attrs.get("is_internal") is True:
            return "Internal"
        if attrs.get("is_public") is False or attrs.get("is_internal") is False:
            return "Private"
        return None

    def _format_permission_groups(self, attrs: dict) -> str | None:
        groups = (
            attrs.get("permission_group_names")
            or attrs.get("permission_groups")
            or attrs.get("group_names")
            or attrs.get("cfg_permission_group")
        )
        if groups is None:
            return None
        if isinstance(groups, str):
            return groups
        if isinstance(groups, list):
            group_names = []
            for group in groups:
                if isinstance(group, str):
                    group_names.append(group)
                elif isinstance(group, dict):
                    name = group.get("name") or group.get("label")
                    if name:
                        group_names.append(str(name))
            return ", ".join(group_names) or None
        return None

    def _as_text(self, value) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None
