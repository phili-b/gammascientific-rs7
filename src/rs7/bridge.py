"""Share an RS-7's serial port over TCP, so another machine can use it as ``socket://host:port``.

There is no authentication: only use this on a trusted network.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable

import serial

from .device import DEFAULT_BAUDRATE


def serve(port: str, listen: int = 5000, baudrate: int = DEFAULT_BAUDRATE, log: Callable[[str], None] = print) -> None:
    """Forward bytes between ``port`` and one TCP client at a time, until interrupted."""
    ser = serial.Serial(port, baudrate, timeout=0.05)
    server = socket.create_server(("", listen))
    log(f"{port} shared on TCP port {listen}")
    try:
        while True:
            conn, addr = server.accept()
            log(f"client {addr[0]} connected")
            _forward(ser, conn)
            log(f"client {addr[0]} disconnected")
    finally:
        server.close()
        ser.close()


def _forward(ser: serial.Serial, conn: socket.socket) -> None:
    stop = threading.Event()

    def unit_to_client():
        while not stop.is_set():
            data = ser.read(1024)
            if data:
                try:
                    conn.sendall(data)
                except OSError:
                    return

    threading.Thread(target=unit_to_client, daemon=True).start()
    try:
        while data := conn.recv(1024):
            ser.write(data)
    except OSError:
        pass
    finally:
        stop.set()
        conn.close()
