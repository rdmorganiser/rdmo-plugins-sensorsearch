from django.apps import AppConfig


class SensorSearchConfig(AppConfig):
    name = "rdmo_sensorsearch"
    label = "rdmo_sensorsearch"
    verbose_name = "Sensor Search Option Set Plugin"

    def ready(self):
        from . import handlers  # noqa: F401
