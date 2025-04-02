from rdmo_sensorsearch.handlers.handler_gfz_gipp import GeophysicalInstrumentPoolPotsdamHandler
from rdmo_sensorsearch.handlers.handler_o2a_registry import O2ARegistrySearchHandler
from rdmo_sensorsearch.handlers.handler_sms import SensorManagementSystemHandler

HANDLER_REGISTRY = {
    "O2ARegistrySearchHandler": O2ARegistrySearchHandler,
    "SensorManagementSystemHandler": SensorManagementSystemHandler,
    "GeophysicalInstrumentPoolPotsdamHandler": GeophysicalInstrumentPoolPotsdamHandler,
}
