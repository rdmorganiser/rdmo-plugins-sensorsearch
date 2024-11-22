# SPDX-FileCopyrightText: 2023 Hannes Fuchs (GFZ) <hannes.fuchs@gfz-potsdam.de>
# SPDX-FileCopyrightText: 2023 Helmholtz Centre Potsdam - GFZ German Research Centre for Geosciences
#
# SPDX-License-Identifier: Apache-2.0

from django.apps import AppConfig


class SensorSearchConfig(AppConfig):
    name = "rdmo_sensorsearch"
    label = "rdmo_sensorsearch"
    verbose_name = "Sensor Search Option Set Plugin"

    def ready(self):
        from . import handlers  # noqa: F401
