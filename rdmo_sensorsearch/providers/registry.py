from rdmo_sensorsearch.providers.provider_gfz_gipp import GeophysicalInstrumentPoolPotsdamProvider
from rdmo_sensorsearch.providers.provider_o2a_registry import O2ARegistrySearchProvider
from rdmo_sensorsearch.providers.provider_sms import SensorManagementSystemProvider
from rdmo_sensorsearch.providers.provider_sms_configurations import (
    SensorManagementSystemConfigurationsProvider,
)

# dict of known sensor data provider
PROVIDER_REGISTRY = {
            "O2ARegistrySearchProvider": O2ARegistrySearchProvider,
            "SensorManagementSystemProvider": SensorManagementSystemProvider,
            "SensorManagementSystemConfigurationsProvider": SensorManagementSystemConfigurationsProvider,
            "GeophysicalInstrumentPoolPotsdamProvider": GeophysicalInstrumentPoolPotsdamProvider,
        }
