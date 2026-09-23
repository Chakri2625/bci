"""Interactive UART diagnostic utility.

Example:
    python test_uart.py --port COM3 --command action cmd|TEST

The default command is intentionally empty so the operator must choose what
the receiver should receive; no potentially destructive action is assumed.
"""

import argparse
import sys

from uart_transmitter import UARTTransmitter


def main():
    parser = argparse.ArgumentParser(description="Test the dashboard UART link")
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--terminator", default="\\n", help=r"Use \\n, \\r\\n, or empty string")
    parser.add_argument("--command", help="Exact command to send; prompted when omitted")
    parser.add_argument("--no-ack", action="store_true")
    args = parser.parse_args()

    command = args.command
    if command is None:
        command = input("Command to send (for example, action cmd|TEST): ").strip()
    if not command:
        print("UART TEST FAILED\n\nReason:\nNo command supplied")
        return 1

    transmitter = UARTTransmitter(
        enabled=True,
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        ack_enabled=not args.no_ack,
        terminator=args.terminator.encode().decode("unicode_escape"),
    )
    print("================================")
    print("UART TEST")
    print("================================")
    print(f"Port      : {args.port}")
    print(f"Baud rate : {args.baudrate}")
    print(f"Timeout   : {args.timeout} sec")
    print("\nOpening serial port...")
    if not transmitter.connect():
        print(f"\nUART TEST FAILED\n\nReason:\nUnable to open {args.port}")
        transmitter.shutdown()
        return 1
    print("CONNECTED\n")
    response = transmitter.send_raw(command)
    if not args.no_ack and response is None:
        print("\nUART TEST FAILED\n\nReason:\nACK timeout or serial error")
        transmitter.shutdown()
        return 1
    print("\nUART TEST PASSED")
    transmitter.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
