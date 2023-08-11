import logging
import requests

from django.conf import settings
from django.dispatch import receiver
from django.db.models.signals import post_save

from rdmo.projects.models import Value
from rdmo.domain.models import Attribute

# https://registry.o2a-data.de/rest/v2/items/4835?with=collections
BASE_URL = 'https://registry.o2a-data.de/rest/v2/items/{id_}?with=collections'

SIMPLE_CONFIG = [
        {
            'catalog_uri': 'http://rdmo-dev.local/terms/questions/sensor-awi-test',
            'auto_complete_field_attribute_uri': 'http://rdmo-dev.local/terms/domain/sensor/awi/search',
            'attribute_mapping': {
                'http://rdmo-dev.local/terms/domain/sensor/awi/type-name': 'longName',
                'http://rdmo-dev.local/terms/domain/sensor/awi/name': 'shortName',
                'http://rdmo-dev.local/terms/domain/sensor/awi/serial': 'serialNumber',
            }
        },
        {
            'catalog_uri': 'https://rdmo-sandbox.gfz-potsdam.de/terms/questions/moses',
            'auto_complete_field_attribute_uri': 'http://rdmo.nfdi.de/terms/domain/dataset/instrument/uri',
            'attribute_mapping': {
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/name': 'longName',
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/type': 'deviceType',
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/manufacturer': 'manufacturer',
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/type/name': 'model',
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/type/serial_number': 'serialNumber',
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/type/pid': 'citation',
                # TODO: URN
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/parameters/name': 'parametersName',
                'http://rdmo.nfdi.de/terms/domain/dataset/instrument/parameters/unit': 'parametersUnit'
            }
        }
]


logger = logging.getLogger(__name__)

def get_config_by_catalog_uri(catalog_uri):
    for item in SIMPLE_CONFIG:
        if item.get('catalog_uri') == catalog_uri:
            return item
    return None

def handle_awio2a(id_):
    base_url = f'https://registry.o2a-data.de/rest/v2/items/{id_}'
    # TODO error handling
    response = requests.get(base_url)
    json_data = response.json()
    json_data.update(
            {
                'deviceType': json_data.get('type', {}).get('generalName'),
                }
            )
    # get parameters
    response = requests.get(base_url + '/parameters')
    parameters_data = response.json()
    parameters_names = []
    parameters_units = []
    units = requests.get('https://registry.o2a-data.de/rest/v2/units').json()
    for parameter in parameters_data.get('records', []):
        parameters_names.append(parameter.get('name'))
        unit = parameter.get('unit')
        if unit and isinstance(unit, dict):
            parameters_units.append(unit.get('code'))
        else:
            for u in units.get('records', []):
                if u.get('@uuid') and u.get('@uuid') == unit:
                    parameters_units.append(u.get('code'))
                    

        
    json_data.update({
        'parametersName': parameters_names,
        'parametersUnit': parameters_units,
    }
    )
    #     parameters_text.append(parameter.get('name'))
    # json_data.update(
    #         {
    #             'parameters_text': parameters_text,
    #             }
    #         )
    return json_data

def handle_sms(id_, inst):
    if inst == 'gfzsms':
        base_url = 'https://sensors.gfz-potsdam.de/backend/api/v1'
    elif inst == 'kitsms':
        base_url = 'https://sms.atmohub.kit.edu/backend/rdm/svm-api/v1'
    elif inst == 'ufzsms':
        base_url = 'https://web.app.ufz.de/sms/backend/api/v1'
    else:
        return {}

    response = requests.get(base_url + f'/devices/{id_}?include=device_properties')
    json_data_response = response.json()
    json_data = json_data_response.get('data', {})
    json_data.update(
            {
                'longName': json_data.get('attributes', {}).get('long_name'),
                'shortName': json_data.get('attributes', {}).get('short_name'),
                'manufacturer': json_data.get('attributes', {}).get('manufacturer_name'),
                'model': json_data.get('attributes', {}).get('model'),
                'serialNumber': json_data.get('attributes', {}).get('serial_number'),
                'citation': json_data.get('attributes', {}).get('persistent_identifier'),
            }
    )
    parameters_names = []
    parameters_units = []
    for attribute in json_data_response.get('included'):
        parameters_names.append(attribute.get('attributes').get('property_name'))
        parameters_units.append(attribute.get('attributes').get('unit_name'))

    json_data.update({
        'parametersName': parameters_names,
        'parametersUnit': parameters_units,
    })

    return json_data

def handle_gipp(id_):
    request_url = f'https://gipp.gfz-potsdam.de/instruments/rest/{id_}.json'
    response = requests.get(request_url)
    json_data = response.json()
    json_data.update(
            {
                'longName': json_data.get('Instrument', {}).get('code'),
                'shortName': json_data.get('Instrumentcategory', {}).get('name'),
                'manufacturer': json_data.get('Instrumentcategory', {}).get('manufacturer'),
                'model': '',
                'serialNumber': json_data.get('Instrument', {}).get('serialNo'),
            }
    )
    return json_data


@receiver(post_save, sender=Value)
def post_save_project_values(sender, **kwargs):
    logger.debug('Call of post_save_project_values')
    # print('Call of post_save_project_values')
    instance = kwargs.get("instance", None)
    logger.debug(f'Instance: {instance}')
    #if instance:
    #    logger.debug('--- START: Instance attributes ---')
    #    for attr in dir(instance):
    #        try:
    #            if not attr.startswith('__'):
    #                value = getattr(instance, attr)
    #                if isinstance(value, (list, tuple)):
    #                    print(f"{attr}: {value} ({type(value).__name__})")
    #                else:
    #                    print(f"{attr}: {value}")
    #        except AttributeError:
    #            # Ignore attributes that can't be accessed due to some internal Python mechanism
    #            pass
    #    logger.debug('--- END: Instance attributes ---')
    logger.debug(f'Catalog URI: {instance.project.catalog.uri}')
    if instance:
        config = get_config_by_catalog_uri(instance.project.catalog.uri)
    else:
        config = None
    logger.debug(f'Config: {config}')
    #if instance and instance.attribute.uri == 'http://rdmo-dev.local/terms/domain/sensor/awi/search':
    if instance and config and config.get('auto_complete_field_attribute_uri') == instance.attribute.uri:
        # TODO: check if in a set/collection
        logger.debug(f'Attribute of instance: {instance.attribute.uri}')
        logger.debug(f'Attribute of type: {type(instance.attribute)}')
        logger.debug(f'External ID: {instance.external_id}')
        if instance.external_id:
            logger.debug(instance.external_id)
            handler = None
            id_ = None
            if len(instance.external_id.split(':')) == 2:
                handler, id_ = instance.external_id.split(':')
            if handler == 'awio2a':
                json_data = handle_awio2a(id_)
            elif handler.endswith('sms'):
                json_data = handle_sms(id_, handler)
            elif handler == 'gfzgipp':
                json_data = handle_gipp(id_)
            else:
                return
            #request_url = BASE_URL.format(id_=instance.external_id)
            ## print(f'Request URL {request_url}')
            ## TODO: proper error handling
            #response = requests.get(request_url)
            #json_data = response.json()
            logger.debug(f'response: {json_data}')
            # go through attributes (hopefully predefined in questions)
            for attribute, source_attribute in config.get('attribute_mapping', {}).items():
                # print(f'attribute {attribute}, source_attribute {source_attribute}')
                # check for key error
                #attribute_value = json_data['records'][0]['metadata'][source_attribute]
                attribute_value = json_data.get(source_attribute)
                if attribute_value:
                    attribute_object = Attribute.objects.get(uri=attribute)
                    if isinstance(attribute_value, list):
                        for i, value in enumerate(attribute_value):
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
                # print(f'created: {created}, object: {obj}')


