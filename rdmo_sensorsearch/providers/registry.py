from rdmo_sensorsearch.providers.gipp_instrument import GIPPInstrumentProvider
from rdmo_sensorsearch.providers.o2a_item import O2ARegistryItemProvider
from rdmo_sensorsearch.providers.o2a_mission import O2ARegistryMissionProvider
from rdmo_sensorsearch.providers.sms_configuration import (
    SensorManagementSystemConfigurationProvider,
)
from rdmo_sensorsearch.providers.sms_device import SensorManagementSystemDeviceProvider

# Backend provider classes addressable from the TOML configuration.
PROVIDER_REGISTRY = {
    "O2ARegistryItemProvider": O2ARegistryItemProvider,
    "O2ARegistryMissionProvider": O2ARegistryMissionProvider,
    "SensorManagementSystemDeviceProvider": SensorManagementSystemDeviceProvider,
    "SensorManagementSystemConfigurationProvider": SensorManagementSystemConfigurationProvider,
    "GIPPInstrumentProvider": GIPPInstrumentProvider,
}
