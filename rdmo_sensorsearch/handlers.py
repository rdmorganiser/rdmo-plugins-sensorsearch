# SPDX-FileCopyrightText: 2023 - 2024 Hannes Fuchs (GFZ) <hannes.fuchs@gfz-potsdam.de>
# SPDX-FileCopyrightText: 2023 - 2024 Helmholtz Centre Potsdam - GFZ German Research Centre for Geosciences
#
# SPDX-License-Identifier: Apache-2.0

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

import jmespath
import requests

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value
from rdmo.questions.models import Question, QuestionSet

from .config import get_user_agent, load_config

logger = logging.getLogger(__name__)


class GenericSearchHandler:
    """
    Base class for handling post_saves.

    Derived classes are used to gather additional information from the
    implemented API provider and map them to attributes in a catalog using
    JMESPath.
    """

    def __init__(
        self,
        base_url=None,
        attribute_mapping={},
        **kwargs,
    ):
        """
        Initializes the GenericSearchHandler.

        Args:
            base_url (str, optional):           The base URL for API requests.
                                                Defaults to None.
            attribute_mapping (dict, optional): A dictionary mapping JamesPath
                                                expressions to attribute URIs.
                                                Defaults to an empty dictionary.
            **kwargs:                           Additional keyword arguments.

        """
        self.base_url = base_url
        self.attribute_mapping = attribute_mapping
        self.mapped_values = {}

    def get_default_id_prefix(self):
        """
        Return the default id_prefix of the handler.

        This should be the same as defined as default in the provider classes
        and can be set to use more than one instance of a provider.

        Raises a NotImplementedError, as this method needs to be implemented
        by subclasses.
        """
        raise NotImplementedError

    def _get(self, url):
        """
        Performs a GET request to the specified URL with custom user agent.

        Args:
            url (str): The URL to send the GET request to.

        Returns:
            dict: A dictionary containing the JSON response from the server, or
                  an empty dictionary if there is an error.

        """
        try:
            return requests.get(url, headers={"User-Agent": get_user_agent()}).json()
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s, %s", e, url)

        return {}

    def _map_jamespath_to_attribute_uri(self, data):
        """
        Maps values from the response data to attribute URIs using JamesPath
        expressions.

        The mapping is usually provided by the configuration file.

        Args:
            data (dict): The JSON response data.

        Returns:
            dict: A dictionary containing mapped values with attribute URIs as
                  keys.

        """
        mapped_values = {}
        for path, attribute_uri in self.attribute_mapping.items():
            mapped_values.update({f"{attribute_uri}": jmespath.search(path, data)})
        logger.debug("mapped_values %s", mapped_values)
        return mapped_values


class O2ARegistrySearchHandler(GenericSearchHandler):
    """
    Handles the O2A Registry to gather additional informations about a sensor.

    To fetch additional data from the O2A REGISTRY at least three API calls
    must be made:
    1. Basic information about the sensor
    2. Parameters of the sensor
    3. Units to add them to the parameters
    """

    def __init__(
        self,
        base_url="https://registry.o2a-data.de/rest/v2",
        attribute_mapping={},
        **kwargs,
    ):
        """
        Initializes the O2ARegistrySearchHandler.

        Args:
            base_url (str, optional):           The base URL for API requests
                                                to the O2A Registry. Defaults
                                                to 'https://registry.o2a-data.de/rest/v2'.
            attribute_mapping (dict, optional): A dictionary mapping JamesPath
                                                expressions to attribute URIs.
                                                Defaults to an empty dictionary.
            **kwargs: Additional keyword arguments.

        """
        super().__init__(base_url=base_url, attribute_mapping=attribute_mapping, **kwargs)

    def get_default_id_prefix(self):
        """Returns the default ID prefix for this handler, which is 'o2aregistry'."""
        return "o2aregistry"

    def handle(self, id_):
        """
        Handles post_save for a specific ID.

        Args:
            id_ (str): The (sensor) ID to to get additional information for.

        Returns:
            dict: A dictionary containing the mapped values from the O2A
                  REGISTRY response.

        """
        # basic date
        basic_data = self._get(f"{self.base_url}/items/{id_}")

        # parameters
        parameters_data = self._get(f"{self.base_url}/items/{id_}/parameters")

        # units
        units_data = self._get(f"{self.base_url}/units")

        # extend basic data with parameters
        data = basic_data
        data.update({"parameters": []})

        # That's a bit special in the case of O2A. It is not guaranteed that
        # the unit is provided. Therefore it must be looked up on another
        # endpoint (`units_data`).
        for parameter in parameters_data.get("records", []):
            parameter_name = parameter.get("name")
            parameter_unit = ""
            # get the unit, maybe lookup from units
            unit_data = parameter.get("unit")
            if unit_data and isinstance(unit_data, dict):
                parameter_unit = unit_data.get("code")
            else:
                for u in units_data.get("records", []):
                    if u.get("@uuid") and u.get("@uuid") == unit_data:
                        parameter_unit = u.get("code")
            #data.update({"parameters": data.get("parameters", []) + [{"name": parameter_name, "unit": parameter_unit}]})
            data.update({"parameters": [*data.get("parameters", []), {"name": parameter_name, "unit": parameter_unit}]})

        logger.debug("data: %s", data)

        return self._map_jamespath_to_attribute_uri(data)


class SensorManagentSystemHandler(GenericSearchHandler):
    """
    Handles the Sensor Management System (SMS) to gather sensor information.

    This handler fetches device information, including properties, from the
    SMS API.
    """

    def get_default_id_prefix(self):
        """Returns the default ID prefix for this handler, which is 'sms'."""
        return "sms"

    def handle(self, id_):
        """
        Handles post_save for a specific device ID in the SMS.

        Args:
            id_ (str): The ID of the device to get information for .

        Returns:
            dict: A dictionary containing the mapped values from the SMS API
                  response.
        """
        data = self._get(f"{self.base_url}/devices/{id_}?include=device_properties")

        logger.debug("data: %s", data)

        return self._map_jamespath_to_attribute_uri(data)


class GeophysicalInstrumentPoolPotsdamHandler(GenericSearchHandler):
    """
    Handles for the Geophysical Instrument Pool Potsdam (GIPP).

    This handler retrieves instrument information from the GIPP REST API.
    """

    def __init__(
        self,
        base_url="https://gipp.gfz-potsdam.de/instruments/rest",
        attribute_mapping={},
        **kwargs,
    ):
        """
        Initializes the GeophysicalInstrumentPoolPotsdamHandler.

        Args:
            base_url (str, optional):           The base URL for API requests
                                                to GIPP. Defaults to
                                                'https://gipp.gfz-potsdam.de/instruments/rest'.
            attribute_mapping (dict, optional): A dictionary mapping JamesPath
                                                expressions to attribute URIs.
                                                Defaults to an empty dictionary.
            **kwargs:                           Additional keyword arguments.

        """
        super().__init__(base_url=base_url, attribute_mapping=attribute_mapping, **kwargs)

    def get_default_id_prefix(self):
        """Returns the default ID prefix for this handler, which is 'gfzgipp'."""
        return "gfzgipp"

    def handle(self, id_):
        """
        Handles post_save for a specific instrument ID in GIPP.

        Args:
            id_ (str): The ID of the instrument to get information for.

        Returns:
            dict: A dictionary containing the mapped values from the GIPP API
                  response.

        """
        data = self._get(f"{self.base_url}/{id_}.json")

        logger.debug("data: %s", data)

        return self._map_jamespath_to_attribute_uri(data)


@receiver(post_save, sender=Value)
def post_save_project_values(sender, **kwargs):
    """
    Handles the post-save signal for Value objects.

    This function is triggered whenever a new Value object is saved. It
    retrieves information from the Value object and uses it to query external
    APIs for related data. The retrieved data is then used to create or update
    additional Value objects associated with the same Project.

    At first it checks if there is an instance with an external_id. The
    external_id can be set by an option set provider. Only then the
    configuration is loaded. Only when the configuration contains a mapping for
    the catalog where the Value belongs to, the resource intensive API calls
    are made.

    Also note, that the external_id must have the format `prefix:id`. The
    prefix is used to identify the correct handler to use. It is also used to
    use the same handler with different backends. The id part is used to query
    the specific backend.

    The result of the handler request is then mapped to attributes to update or
    save Values. The attribute mapping is provided by a TOML configuration
    file.

    Args:
        sender (object): The sender of the signal, in this case, the Value model.
        **kwargs (dict): Keyword arguments passed by the signal, including the
                         newly saved Value object instance.

    Returns:
        None
    """

    logger.debug("Call of post_save_project_values")
    instance = kwargs.get("instance", None)
    logger.debug(f"Instance: {instance}")
    logger.debug(f"Catalog URI: {instance.project.catalog.uri}")

    # Noting to do without instance or an instance without an external id
    if instance is None or instance.external_id is None:
        return

    configuration = load_config()

    # Without configuration we have no mapping and can not do anything
    if configuration is None:
        return

    logger.debug("Config: %s", configuration)
    # Only with an id_prefix and an id it is possible to lookup the correct
    # handler and get additional information of a sensor
    id_prefix = None
    external_id = None
    if len(instance.external_id.split(":")) == 2:
        id_prefix, external_id = instance.external_id.split(":")

    if id_prefix is None or external_id is None:
        return

    # Go through configured handlers and try to find a matching one
    # Also get the catalog configuration to lookup a mapping from API to
    # attributes via JMESPath
    handlers_configuration = configuration.get("handlers", {})
    for handler, config in handlers_configuration.items():
        catalog_configs = config.get("catalogs")
        backends = config.get("backends")

        try:
            # get handler class by name
            HandlerClass = globals()[handler]
            logger.debug("Current handler class: %s (%s)", handler, HandlerClass)
        except KeyError:
            logger.error("The handler %s does not exist. Check yor configuration.", handler)
            continue

        if catalog_configs is None:
            logger.error("No catalog mappings configured for handler %s. Add mappings to use this handler.", handler)
            continue

        # Lookup the catalog configuration with mapping
        # This should return only one, but it is possible to configure more
        # than one with the same uri in TOML
        matching_catalog_configs = [
            cc
            for cc in catalog_configs
            if cc["catalog_uri"] == instance.project.catalog.uri
            and cc["auto_complete_field_uri"] == instance.attribute.uri
        ]

        if not matching_catalog_configs:
            logger.info("not matching catalog config found")
            return

        if matching_catalog_configs:
            logger.debug("found mapping for %s: %s", handler, matching_catalog_configs)

        # Create an instance of the matching handler object and initialize it
        # withe the attribute mapping of the matching catalog
        handler_object = None
        # Use defaults if backends is not specified
        if backends is None and id_prefix == HandlerClass().get_default_id_prefix():
            logger.info("Using defaults for handler %s", handler)
            handler_object = HandlerClass(attribute_mapping=matching_catalog_configs[0].get("attribute_mapping"))
        elif backends:
            # find matching backend
            matching_backends = [b for b in backends if b["id_prefix"] == id_prefix]
            logger.debug("Matching backends: %s", matching_backends)
            if matching_backends and matching_backends[0].get("base_url"):
                handler_object = HandlerClass(
                    base_url=matching_backends[0].get("base_url"),
                    attribute_mapping=matching_catalog_configs[0].get("attribute_mapping"),
                )
            elif matching_backends:
                handler_object = HandlerClass(attribute_mapping=matching_catalog_configs[0].get("attribute_mapping"))

        # If no handler object could be initialized, do nothing
        if handler_object is None:
            logger.info("No matching handler configured")
            continue

        # Update or create Values objects based on the response of the handler
        # which includes attribute mapping
        for attribute_uri, attribute_value in handler_object.handle(id_=external_id).items():
            if attribute_value is not None:
                attribute_object = Attribute.objects.get(uri=attribute_uri)
                if isinstance(attribute_value, list):
                    # get question count, which are collection and match our
                    # attribute and catalog
                    question_match_count = Question.objects.filter(
                        is_collection=True,
                        attribute=attribute_object,
                        pages__sections__catalogs__id__exact=instance.project.catalog.id,
                    ).count()
                    # get questionset count, which are collection and match our
                    # attribute and catalog
                    question_set_match_count = QuestionSet.objects.filter(
                        is_collection=True,
                        pages__sections__catalogs__id__exact=instance.project.catalog.id,
                        questions__attribute__in=[attribute_object],
                    ).count()

                    # matches a question which is a collection
                    if question_match_count == 1 and question_set_match_count == 0:
                        for i, value in enumerate(attribute_value):
                            _, _ = Value.objects.update_or_create(
                                project=instance.project,
                                attribute=attribute_object,
                                set_collection=True,
                                set_index=instance.set_index,
                                collection_index=i,
                                defaults={
                                    "project": instance.project,
                                    "attribute": attribute_object,
                                    "text": value,
                                },
                            )
                    # nested question in questionset
                    elif question_match_count == 0 and question_set_match_count > 0:
                        for i, value in enumerate(attribute_value):
                            _, _ = Value.objects.update_or_create(
                                project=instance.project,
                                attribute=attribute_object,
                                set_prefix=instance.set_index,
                                set_collection=True,
                                set_index=i,
                                defaults={
                                    "project": instance.project,
                                    "attribute": attribute_object,
                                    "text": value,
                                },
                            )
                    else:
                        logger.warning(
                            "Got a list of values, but no matching Question or QuestionSet with is_collection flag. "
                            "Questions: %s, QuestionSets: %s, Attribute: %s",
                            question_match_count,
                            question_set_match_count,
                            attribute_object,
                        )
                else:
                    obj, created = Value.objects.update_or_create(
                        project=instance.project,
                        attribute=attribute_object,
                        set_index=instance.set_index,
                        defaults={
                            "project": instance.project,
                            "attribute": attribute_object,
                            "text": attribute_value,
                        },
                    )
