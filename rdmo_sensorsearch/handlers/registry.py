from rdmo_sensorsearch.handlers.gipp_instrument import GIPPInstrumentHandler
from rdmo_sensorsearch.handlers.o2a_item import O2ARegistryItemHandler
from rdmo_sensorsearch.handlers.o2a_mission import O2ARegistryMissionHandler
from rdmo_sensorsearch.handlers.sms_configuration import (
    SensorManagementSystemConfigurationHandler,
)
from rdmo_sensorsearch.handlers.sms_device import SensorManagementSystemDeviceHandler

HANDLER_REGISTRY = {
    "O2ARegistryItemHandler": O2ARegistryItemHandler,
    "O2ARegistryMissionHandler": O2ARegistryMissionHandler,
    "SensorManagementSystemDeviceHandler": SensorManagementSystemDeviceHandler,
    "SensorManagementSystemConfigurationHandler": SensorManagementSystemConfigurationHandler,
    "GIPPInstrumentHandler": GIPPInstrumentHandler,
}
