from rdmo_sensorsearch.providers.provider_gfz_gipp import GeophysicalInstrumentPoolPotsdamProvider
from rdmo_sensorsearch.providers.provider_o2a_registry import O2ARegistrySearchProvider
from rdmo_sensorsearch.providers.provider_o2a_registry_missions import O2ARegistryMissionsProvider
from rdmo_sensorsearch.providers.provider_sms import SensorManagementSystemProvider
from rdmo_sensorsearch.providers.provider_sms_configurations import (
    SensorManagementSystemConfigurationsProvider,
)

# dict of known sensor data provider
PROVIDER_REGISTRY = {
    "O2ARegistrySearchProvider": O2ARegistrySearchProvider,
    "O2ARegistryMissionsProvider": O2ARegistryMissionsProvider,
    "SensorManagementSystemProvider": SensorManagementSystemProvider,
    "SensorManagementSystemConfigurationsProvider": SensorManagementSystemConfigurationsProvider,
    "GeophysicalInstrumentPoolPotsdamProvider": GeophysicalInstrumentPoolPotsdamProvider,
}
