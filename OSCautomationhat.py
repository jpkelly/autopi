#!/usr/bin/python3
"""
Refactored OSCautomationhat.py

- Encapsulates behaviour in OSCAutomationHat class.
- Uses threading.Event for clean shutdown and joins threads.
- Uses threading.Lock to protect shared state (INPUTSTATE, ADCSTATE).
- Creates OSC clients once and reuses them; attempts backup on failure.
- Converts heartbeat to time-based interval instead of loop-count.
- Adds short sleeps in loops to avoid busy spinning.
- Uses logging.exception in except blocks to retain stack traces.
- Adds a main() function and an if __name__ == "__main__" guard.

Original behaviour is retained where reasonable; hardware calls
are still guarded by automationhat.is_automation_hat().
"""

import os
import socket
import argparse
import time
import threading
import logging
from signal import signal, SIGINT
from systemd import journal

from pythonosc import dispatcher as osc_dispatcher
from pythonosc import osc_server
from pythonosc import udp_client

import automationhat
time.sleep(0.1)  # short pause after ads1015 class creation recommended

import systemd_stopper

# Defaults (can be overridden via CLI)
DEFAULT_SERVER_ADDRESS = "0.0.0.0"
DEFAULT_SERVER_PORT = 7000
DEFAULT_PRIMARY_ADDRESS = "10.0.0.123"
DEFAULT_BACKUP_ADDRESS = "172.22.22.108"
DEFAULT_CLIENT_PORT = 8000
DEFAULT_HEARTBEAT_SECONDS = 150.0

HOSTNAME = socket.gethostname()

# Logging
log = logging.getLogger('OSC Automation Hat')
log.addHandler(journal.JournaldLogHandler())
log.setLevel(logging.INFO)


class OSCAutomationHat:
    def __init__(self,
                 server_address=DEFAULT_SERVER_ADDRESS,
                 server_port=DEFAULT_SERVER_PORT,
                 primary_address=DEFAULT_PRIMARY_ADDRESS,
                 backup_address=DEFAULT_BACKUP_ADDRESS,
                 client_port=DEFAULT_CLIENT_PORT,
                 heartbeat_seconds=DEFAULT_HEARTBEAT_SECONDS,
                 poll_interval=0.1):
        self.server_address = server_address
        self.server_port = server_port
        self.primary_address = primary_address
        self.backup_address = backup_address
        self.client_port = client_port
        self.heartbeat_seconds = float(heartbeat_seconds)
        self.poll_interval = float(poll_interval)

        # Shared states protected by lock
        self._state_lock = threading.Lock()
        self.input_state = [0, 0, 0]
        self.adc_state = [0, 0, 0]
        self._last_heartbeat = time.time()

        # Thread control
        self.stop_event = threading.Event()
        self.adc_thread = None
        self.server = None
        self.server_thread = None

        # OSC clients (created once)
        self.primary_client = udp_client.SimpleUDPClient(self.primary_address, self.client_port)
        self.backup_client = udp_client.SimpleUDPClient(self.backup_address, self.client_port)

        # Dispatcher
        self.dispatcher = osc_dispatcher.Dispatcher()
        # Use wildcard patterns and a common extractor for index
        self.dispatcher.map("/relay/*", self.relay_handler)
        self.dispatcher.map("/led/*", self.led_handler)
        self.dispatcher.map("/output/*", self.output_handler)
        self.dispatcher.map("/restart/*", self.restart_handler)

        # Setup hardware initial state if present
        if automationhat.is_automation_hat():
            automationhat.enable_auto_lights(True)  # Set to False for better ADC performance
            automationhat.light.power.write(1)
            automationhat.light.comms.write(0)
            automationhat.light.warn.write(0)
            log.info("Automation Hat library version: " + automationhat.__version__)
        else:
            log.info("automationhat library reports no Automation HAT present; running in dry mode")

    # Utility to safely extract index from an OSC address like "/relay/1"
    def _extract_index(self, address):
        try:
            parts = [p for p in address.split("/") if p != ""]
            # expected format: ["relay", "1"] or ["HOST", "DI1"] etc.
            if len(parts) >= 2:
                idx = int(parts[1])
                return idx
        except Exception:
            log.exception("Failed to extract index from address: %s", address)
        return None

    # Send helper: try primary then fallback to backup
    def _send_message(self, path, value):
        try:
            self.primary_client.send_message(path, value)
            return True
        except Exception:
            log.exception("Sending to primary %s failed, attempting backup", self.primary_address)
            try:
                self.backup_client.send_message(path, value)
                return True
            except Exception:
                log.exception("Sending to backup %s failed", self.backup_address)
                return False

    # Handlers
    def relay_handler(self, address, *args):
        log.info("relay handler called for %s args=%s", address, args)
        idx = self._extract_index(address)
        if idx is None:
            return
        try:
            relaystate = int(args[0])
        except Exception:
            log.exception("Invalid relay state: %s", args)
            return
        if automationhat.is_automation_hat():
            try:
                automationhat.light.comms.write(1)
                if 0 <= idx < len(automationhat.relay):
                    automationhat.relay[idx].write(relaystate)
                else:
                    log.error("Relay index out of range: %s", idx)
            except Exception:
                log.exception("Error writing relay %s", idx)

    def led_handler(self, address, *args):
        log.info("led handler called for %s args=%s", address, args)
        idx = self._extract_index(address)
        if idx is None:
            return
        try:
            ledstate = int(args[0])
        except Exception:
            log.exception("Invalid LED state: %s", args)
            return
        if automationhat.is_automation_hat():
            try:
                if idx == 0:
                    automationhat.light.power.write(ledstate)
                elif idx == 1:
                    automationhat.light.comms.write(ledstate)
                elif idx == 2:
                    automationhat.light.warn.write(ledstate)
                else:
                    log.error("LED index out of range: %s", idx)
            except Exception:
                log.exception("Error writing LED %s", idx)

    def output_handler(self, address, *args):
        log.info("output handler called for %s args=%s", address, args)
        idx = self._extract_index(address)
        if idx is None:
            return
        try:
            outputstate = int(args[0])
        except Exception:
            log.exception("Invalid output state: %s", args)
            return
        if automationhat.is_automation_hat():
            try:
                if 0 <= idx < len(automationhat.output):
                    automationhat.output[idx].write(outputstate)
                else:
                    log.error("Output index out of range: %s", idx)
            except Exception:
                log.exception("Error writing output %s", idx)

    def restart_handler(self, address, *args):
        log.info("restart handler called for %s args=%s", address, args)
        idx = self._extract_index(address)
        if idx is None:
            return
        try:
            restartstate = int(args[0])
        except Exception:
            log.exception("Invalid restart state: %s", args)
            return
        # Only action at index 0 triggers reboot per original behaviour
        if idx == 0 and restartstate == 1:
            log.info("Reboot triggered via OSC restart/0")
            try:
                os.system('sudo reboot')
            except Exception:
                log.exception("Failed to execute reboot command")

    # ADC checking thread
    def _adc_loop(self):
        log.info("ADC thread started, sending ADC changes to %s and %s", self.primary_address, self.backup_address)
        while not self.stop_event.is_set():
            for i in range(3):
                try:
                    adc_value = automationhat.analog[i].read() if automationhat.is_automation_hat() else 0
                except Exception:
                    log.exception("Error reading ADC %s", i)
                    adc_value = 0
                with self._state_lock:
                    if self.adc_state[i] != adc_value:
                        self.adc_state[i] = adc_value
                        path = f"/{HOSTNAME}/A{i+1}"
                        log.info("ADC change, sending %s = %s", path, adc_value)
                        try:
                            # Send numeric value (float/int) rather than string
                            if not self._send_message(path, adc_value):
                                # light warn if both failed
                                if automationhat.is_automation_hat():
                                    automationhat.light.warn.write(1)
                        except Exception:
                            log.exception("Failed sending ADC message for %s", path)
                if self.stop_event.wait(self.poll_interval):
                    break
            # small sleep to avoid busy loop if not broken above
            # (stop_event.wait already includes sleep)
        log.info("ADC thread exiting")

    # Main loop: check digital inputs and heartbeat
    def _main_loop(self):
        log.info("Main loop started")
        last_inputs = [None, None, None]
        while not self.stop_event.is_set():
            # check digital inputs
            for i in range(3):
                try:
                    input_value = automationhat.input[i].read() if automationhat.is_automation_hat() else 0
                except Exception:
                    log.exception("Error reading input %s", i)
                    input_value = 0
                with self._state_lock:
                    if self.input_state[i] != input_value:
                        self.input_state[i] = input_value
                        self._last_heartbeat = time.time()  # reset heartbeat timer on activity
                        path = f"/{HOSTNAME}/DI{i+1}"
                        log.info("Input change %s = %s", path, input_value)
                        try:
                            if not self._send_message(path, int(input_value)):
                                if automationhat.is_automation_hat():
                                    automationhat.light.warn.write(1)
                        except Exception:
                            log.exception("Failed to send DI message for %s", path)
            # heartbeat (time-based)
            now = time.time()
            if (now - self._last_heartbeat) >= self.heartbeat_seconds:
                path = f"/{HOSTNAME}/heartbeat"
                try:
                    log.info("Sending heartbeat %s", path)
                    if not self._send_message(path, [1]):  # send a list/int as before
                        if automationhat.is_automation_hat():
                            automationhat.light.warn.write(1)
                except Exception:
                    log.exception("Failed to send heartbeat")
                self._last_heartbeat = now
            # avoid busy loop
            self.stop_event.wait(self.poll_interval)
        log.info("Main loop exiting")

    # Setup and start server and threads
    def start(self):
        # start ADC thread
        self.adc_thread = threading.Thread(target=self._adc_loop, name="ADCThread", daemon=True)
        self.adc_thread.start()

        # start OSC server
        self.server = osc_server.ThreadingOSCUDPServer((self.server_address, self.server_port), self.dispatcher)
        log.info("Starting OSC server on %s:%s", self.server_address, self.server_port)
        self.server_thread = threading.Thread(target=self.server.serve_forever, name="OSCServerThread", daemon=True)
        self.server_thread.start()

        # start main loop in current thread or a new thread? we'll start it in a new thread
        self.main_thread = threading.Thread(target=self._main_loop, name="MainLoopThread", daemon=True)
        self.main_thread.start()

    def shutdown(self, timeout=5.0):
        log.info("Shutdown requested")
        # Signal loops to stop
        self.stop_event.set()

        # Shutdown OSC server
        try:
            if self.server:
                log.info("Shutting down OSC server")
                self.server.shutdown()
                # allow serve_forever to exit
                self.server.server_close()
        except Exception:
            log.exception("Error shutting down OSC server")

        # Join threads
        threads = [getattr(self, 'adc_thread', None),
                   getattr(self, 'main_thread', None),
                   getattr(self, 'server_thread', None)]
        for t in threads:
            if t and t.is_alive():
                t.join(timeout)

        # Turn off lights (if present)
        if automationhat.is_automation_hat():
            try:
                automationhat.light.power.write(0)
            except Exception:
                log.exception("Error turning off power light")

        log.info("Shutdown complete")


def parse_cli_args():
    parser = argparse.ArgumentParser(description="OSC Automation Hat daemon (refactored)")
    parser.add_argument("--server-ip", default=DEFAULT_SERVER_ADDRESS, help="The IP the OSC server listens on")
    parser.add_argument("--server-port", type=int, default=DEFAULT_SERVER_PORT, help="The port the OSC server listens on")
    parser.add_argument("--primary", default=DEFAULT_PRIMARY_ADDRESS, help="Primary OSC destination IP")
    parser.add_argument("--backup", default=DEFAULT_BACKUP_ADDRESS, help="Backup OSC destination IP")
    parser.add_argument("--client-port", type=int, default=DEFAULT_CLIENT_PORT, help="Port to send OSC messages to")
    parser.add_argument("--heartbeat", type=float, default=DEFAULT_HEARTBEAT_SECONDS, help="Heartbeat interval in seconds")
    parser.add_argument("--poll-interval", type=float, default=0.1, help="Polling interval seconds (main and ADC loops)")
    return parser.parse_args()

def main():
    args = parse_cli_args()

    app = OSCAutomationHat(
        server_address=args.server_ip,
        server_port=args.server_port,
        primary_address=args.primary,
        backup_address=args.backup,
        client_port=args.client_port,
        heartbeat_seconds=args.heartbeat,
        poll_interval=args.poll_interval,
    )

    # Setup SIGINT handler to request shutdown
    def _sigint_handler(sig, frame):
        log.info("SIGINT received, initiating shutdown")
        app.shutdown()
    signal(SIGINT, _sigint_handler)

    # Install systemd stopper to allow systemd to request stop
    stopper = systemd_stopper.install('USR1', 'HUP')
    try:
        app.start()
        log.info("OSC Automation Hat daemon started")
        # Run until systemd stopper indicates stop
        while stopper.run and not app.stop_event.is_set():
            time.sleep(0.5)
    except Exception:
        log.exception("Unhandled exception in main")
    finally:
        app.shutdown()
        log.info("Exiting main")

if __name__ == "__main__":
    main()
