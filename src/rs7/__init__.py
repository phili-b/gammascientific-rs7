"""Control a Gamma Scientific SpectralLED RS-7 over its USB serial port."""
from .device import RS7, ChannelInfo, PeakType, RS7Error, Units

__all__ = ["RS7", "RS7Error", "ChannelInfo", "PeakType", "Units"]
__version__ = "0.1.0"
