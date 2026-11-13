"""Share the RS-7's serial port over TCP, so a PC can use it while the unit sits on another machine.

Run this on the machine the RS-7 is plugged into (e.g. a Raspberry Pi):

    python3 serial_bridge.py --port /dev/ttyUSB0 --listen 5000

Then on your PC use the pyserial URL instead of a COM port:

    RS7("socket://192.168.1.50:5000")        # or pick it in the GUI config file

There is no authentication: only use this on a trusted network.
"""
import argparse
import socket
import threading

import serial


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--listen", type=int, default=5000)
    a = ap.parse_args()

    ser = serial.Serial(a.port, a.baud, timeout=0.05)
    server = socket.create_server(("", a.listen))
    print(f"{a.port} shared on TCP port {a.listen}")
    while True:
        conn, addr = server.accept()
        print("client", addr)
        stop = threading.Event()

        def to_client():
            while not stop.is_set():
                data = ser.read(1024)
                if data:
                    try:
                        conn.sendall(data)
                    except OSError:
                        return

        threading.Thread(target=to_client, daemon=True).start()
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                ser.write(data)
        except OSError:
            pass
        finally:
            stop.set()
            conn.close()
            print("client gone")


if __name__ == "__main__":
    main()
