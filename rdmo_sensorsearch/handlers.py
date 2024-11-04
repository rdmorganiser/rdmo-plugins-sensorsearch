import jmespath
import logging
import requests

from django.conf import settings
from django.dispatch import receiver
from django.db.models.signals import post_save

from rdmo.projects.models import Value
from rdmo.domain.models import Attribute

from .config import load_config, get_user_agent


logger = logging.getLogger(__name__)

class GenericSearchHandler():
    def __init__(
        self,
        base_url=None,
        attribute_mapping={},
        **kwargs,
    ):
        self.base_url = base_url
        self.attribute_mapping = attribute_mapping
        self.mapped_values = {}

    def get_default_id_prefix(self):
        raise NotImplementedError

    def _get(self, url):
        try:
            return requests.get(url, headers={"User-Agent": get_user_agent()}).json()
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s", e)
        
        return {}

    def _map_jamespath_to_attribute_uri(self, data):
        mapped_values = {}
        for path, attribute_uri in self.attribute_mapping.items():
            mapped_values.update({f'{attribute_uri}': jmespath.search(path, data)})
        logger.debug('mapped_values %s', mapped_values)
        return mapped_values




class O2ARegistrySearchHandler(GenericSearchHandler):
    def __init__(
        self,
        base_url='https://registry.o2a-data.de/rest/v2',
        attribute_mapping={},
        **kwargs,
    ):
        super().__init__(base_url=base_url, attribute_mapping=attribute_mapping, **kwargs)

    def get_default_id_prefix(self):
        return 'o2aregistry'

    def handle(self, id_):
        # basic date
        basic_data = self._get(f'{self.base_url}/items/{id_}')

        # parameters
        parameters_data = self._get(f'{self.base_url}/items/{id_}/parameters')

        # units
        units_data = self._get(f'{self.base_url}/units')

        # extend basic data with parameters
        data = basic_data
        data.update({'parameters': []})

        for parameter in parameters_data.get('records', []):
            parameter_name = parameter.get('name')
            parameter_unit = ''
            # get the unit, maybe lookup from units
            unit_data = parameter.get('unit')
            if unit_data and isinstance(unit_data, dict):
                parameter_unit = unit_data.get('code')
            else:
                for u in units_data.get('records', []):
                    if u.get('@uuid') and u.get('@uuid') == unit_data:
                        parameter_unit = u.get('code')
            data.update({'parameters': data.get('parameters', []) + [{'name': parameter_name, 'unit': parameter_unit }]})

        logger.debug('data: %s', data)

        return self._map_jamespath_to_attribute_uri(data)


class SensorManagentSystemHandler(GenericSearchHandler):

    def get_default_id_prefix(self):
        return 'sms'

    def handle(self, id_):
        data = self._get(f'{self.base_url}/devices/{id_}?include=device_properties')

        logger.debug('data: %s', data)

        return self._map_jamespath_to_attribute_uri(data)

class GeophysicalInstrumentPoolPotsdamHandler(GenericSearchHandler):
    def __init__(
        self,
        base_url='https://gipp.gfz-potsdam.de/instruments/rest',
        attribute_mapping={},
        **kwargs,
    ):
        super().__init__(base_url=base_url, attribute_mapping=attribute_mapping, **kwargs)

    def get_default_id_prefix(self):
        return 'gfzgipp'

    def handle(self, id_):
        data = self._get(f'{self.base_url}/{id_}.json')

        logger.debug('data: %s', data)

        return self._map_jamespath_to_attribute_uri(data)


@receiver(post_save, sender=Value)
def post_save_project_values(sender, **kwargs):
    logger.debug('Call of post_save_project_values')
    instance = kwargs.get("instance", None)
    logger.debug(f'Instance: {instance}')
    logger.debug(f'Catalog URI: {instance.project.catalog.uri}')
    
    # Noting to do without instance or an instance without an external id
    if instance is None or instance.external_id is None:
        return

    configuration = load_config()

    # Without configuration we have no mapping and can not do anything
    if configuration is None:
        return

    logger.debug(f'Config: %s', configuration)
    id_prefix = None
    external_id = None
    if len(instance.external_id.split(':')) == 2:
        id_prefix, external_id = instance.external_id.split(':')

    if id_prefix is None or external_id is None:
        return
    
    handlers_configuration = configuration.get('handlers', {})
    for handler, config in handlers_configuration.items():
        catalog_configs = config.get('catalogs')
        backends = config.get('backends')
        
        try:
            # get handler class by name
            HandlerClass = globals()[handler]
            logger.debug('Current handler class: %s (%s)', handler, HandlerClass)
        except KeyError:
            logger.error('The handler %s does not exist. Check yor configuration.', handler)
            continue

        if catalog_configs is None:
            logger.error('No catalog mappings configured for handler %s. Add mappings to use this handler.', handler)
            continue

        # this should return only one
        matching_catalog_configs = [cc for cc in catalog_configs if cc['catalog_uri'] == instance.project.catalog.uri and cc['auto_complete_field_uri'] == instance.attribute.uri]
        
        if not matching_catalog_configs:
            logger.info('not matching catalog config found')
            return

        if matching_catalog_configs:
            logger.debug('found mapping for %s: %s', handler, matching_catalog_configs)
        
        handler_object = None
        # use default configuration 
        if backends is None and id_prefix == HandlerClass().get_default_id_prefix():
            logger.info('Using defaults for handler %s', handler)
            handler_object = HandlerClass(attribute_mapping=matching_catalog_configs[0].get('attribute_mapping'))
        elif backends:
            # find matching backend
            matching_backends = [b for b in backends if b['id_prefix'] == id_prefix]
            logger.debug('Matching backends: %s', matching_backends)
            if matching_backends and matching_backends[0].get('base_url'):
                handler_object = HandlerClass(base_url=matching_backends[0].get('base_url'), attribute_mapping=matching_catalog_configs[0].get('attribute_mapping'))
            elif matching_backends:
                handler_object = HandlerClass(attribute_mapping=matching_catalog_configs[0].get('attribute_mapping'))

        if handler_object is None:
            logger.info('No matching handler configured')
            continue

        for attribute_uri, attribute_value in handler_object.handle(id_=external_id).items():
            if attribute_value is not None:
                attribute_object = Attribute.objects.get(uri=attribute_uri)
                if isinstance(attribute_value, list):
                    for i, value in enumerate(attribute_value):
                        # TODO: check if attribute is collection
                        obj, created = Value.objects.update_or_create(
                            project=instance.project,
                            attribute=attribute_object,
                            set_prefix=instance.set_index,
                            set_collection=True,
                            set_index=i,
                            defaults={
                                'project': instance.project,
                                'attribute': attribute_object,
                                'text': value,
                            }
                        )
                else:
                    obj, created = Value.objects.update_or_create(
                        project=instance.project,
                        attribute=attribute_object,
                        set_index=instance.set_index,
                        defaults={
                            'project': instance.project,
                            'attribute': attribute_object,
                            'text': attribute_value,
                        }
                    )
