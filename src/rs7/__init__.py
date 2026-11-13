"""Control a Gamma Scientific SpectralLED RS-7 over its USB serial port."""

from .device import RS7, ChannelInfo, PeakType, PortNotFoundError, RS7Error, Units, find_port, find_ports

__all__ = ["RS7", "ChannelInfo", "PeakType", "PortNotFoundError", "RS7Error", "Units", "find_port", "find_ports"]
__version__ = "0.3.0"
