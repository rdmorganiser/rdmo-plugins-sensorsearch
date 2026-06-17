# SPDX-FileCopyrightText: 2023 - 2024 Hannes Fuchs (GFZ) <hannes.fuchs@gfz-potsdam.de>
# SPDX-FileCopyrightText: 2023 - 2024 Helmholtz Centre Potsdam - GFZ German Research Centre for Geosciences
# SPDX-FileCopyrightText: 2025 - 2026 RDMO Community and individual contributors
# SPDX-License-Identifier: Apache-2.0

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    VERSION = __version__ = _version(__package__)
except PackageNotFoundError:
    VERSION = __version__ = "0.0.0+unknown"
