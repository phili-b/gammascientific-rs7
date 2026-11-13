"""Import colour-science once, without its warnings about optional SciPy / Matplotlib features we do not use."""

from __future__ import annotations

import warnings
from functools import cache
from types import ModuleType


@cache
def colour() -> ModuleType:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r'.*"(SciPy|Matplotlib)" related API features are not available')
        import colour as module
    return module
