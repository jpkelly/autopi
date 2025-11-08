# OSC Automation Hat

A daemon to integrate an Automation HAT (Pimoroni) with an OSC (Open Sound Control) network. The service:

- Listens for incoming OSC commands to control relays, LEDs and outputs.
- Polls Automation HAT analog inputs (ADCs) and digital inputs and sends updates as OSC messages to one or two remote OSC hosts (primary and optional backup).
- Sends periodic heartbeat messages to indicate liveness.
- Logs to systemd journal.

This repository includes a refactored, production-friendly implementation in `OSCautomationhat.py` that:
- Encapsulates behavior in an `OSCAutomationHat` class.
- Uses `threading.Event` and `threading.Lock` to coordinate clean shutdowns and protect shared state.
- Avoids busy loops (uses `Event.wait()` with a configurable poll interval).
- Creates OSC clients once and retries using a backup host if the primary fails.
- Converts heartbeat to a time-based interval (seconds) rather than a loop counter.
- Sends structured log output to systemd journal.

Table of contents
- Features
- Requirements
- Installation
- Configuration and CLI
- Running
- Systemd service example
- Hardware and testing notes
- Troubleshooting
- Contributing
- License

## Features
- Threaded OSC server for inbound control messages (python-osc).
- Background ADC polling thread that sends changes to remote host(s).
- Main loop polls digital inputs and manages heartbeat.
- Clean shutdown: server shutdown + thread joins.
- Logging to systemd journal via `systemd.journal`.
- Dry-mode support: the script checks `automationhat.is_automation_hat()` and will avoid fatal hardware access if hardware is not present.

## Requirements
- Hardware
  - Raspberry Pi with an Automation HAT (Pimoroni) is supported — code checks for presence and runs in "dry" mode if not detected.
- Software / Python packages
  - Python 3.7+
  - python-osc
  - automationhat (Pimoroni Automation HAT package)
  - systemd-python (for journald integration) and systemd_stopper helper used by the original script
  - Optionally: pipenv/venv
- System
  - systemd if you want to run it as a daemon using a systemd unit (recommended).
- Access
  - Network connectivity to configured primary/backup OSC hosts.
  - If you want to allow remote-triggered reboots, the user running the script must be able to execute `sudo reboot` without an interactive password (careful about security implications).

Install Python deps (example):
```bash
python3 -m pip install python-osc automationhat systemd-python
```

If `systemd_stopper` is a local helper module in the repo, ensure it's accessible (in PATH or same directory).

## Installation
1. Clone the repository (or copy files into your project):
```bash
git clone https://github.com/jpkelly/autopi.git
cd autopi
```

2. Place `OSCautomationhat.py` (refactored script) at a suitable location, e.g. `/usr/local/bin/OSCautomationhat.py`, and make it executable:
```bash
sudo cp OSCautomationhat.py /usr/local/bin/OSCautomationhat.py
sudo chmod +x /usr/local/bin/OSCautomationhat.py
```

3. Install dependencies:
```bash
python3 -m pip install --upgrade pip
python3 -m pip install python-osc automationhat systemd-python
```

Adjust the packages to your environment (for offline boards, you may preinstall wheels or use apt packages where available).

## Configuration and CLI
The refactored script exposes CLI options. Run with `--help` to see usage.

Key options:
- `--server-ip` (default: `0.0.0.0`) — the IP address to bind the OSC server to.
- `--server-port` (default: `7000`) — the UDP port the OSC server listens on.
- `--primary` (default: `10.0.0.123`) — primary OSC destination IP for forwarded messages.
- `--backup` (default: `172.22.22.108`) — backup OSC destination IP used if primary fails.
- `--client-port` (default: `8000`) — port to send OSC messages to on remote hosts.
- `--heartbeat` (default: `150.0`) — heartbeat interval in seconds.
- `--poll-interval` (default: `0.1`) — polling interval for ADC and digital input loops (seconds).

Example:
```bash
/usr/local/bin/OSCautomationhat.py --server-ip 0.0.0.0 --server-port 7000 \
  --primary 10.0.0.123 --backup 172.22.22.108 --client-port 8000 \
  --heartbeat 150 --poll-interval 0.1
```

The script sends ADC updates to `/HOSTNAME/A{N}` and digital inputs to `/HOSTNAME/DI{N}`. Heartbeat is `/HOSTNAME/heartbeat`.

Inbound OSC addresses (handled by server):
- `/relay/<n>` — toggle relay `n` (0..2)
- `/led/<n>` — write to LED `n` (0..2)
- `/output/<n>` — write to output `n` (0..2)
- `/restart/<n>` — restart commands; only `/restart/0 1` triggers a `sudo reboot` (original behavior)

The handlers expect the numeric state in the message's first argument (e.g., 0 or 1).

## Running as a service (systemd)
Example systemd unit you can use to run the daemon:

```ini
[Unit]
Description=OSC Automation Hat daemon
After=network.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/usr/local/bin
ExecStart=/usr/bin/python3 /usr/local/bin/OSCautomationhat.py --server-ip 0.0.0.0 --server-port 7000 --primary 10.0.0.123 --backup 172.22.22.108
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Install and enable:
```bash
sudo cp deploy/osc-automationhat.service /etc/systemd/system/osc-automationhat.service
sudo systemctl daemon-reload
sudo systemctl enable --now osc-automationhat.service
sudo journalctl -u osc-automationhat -f
```

Adjust `User` and paths as needed. If `sudo reboot` from the script is required, ensure `User` has the appropriate sudo privileges (edit `/etc/sudoers` with `visudo` if necessary and be very careful).

## Hardware and testing notes
- The script checks `automationhat.is_automation_hat()` before performing hardware writes/reads. When developing on a non-HAT machine, the script runs in "dry" mode (no hardware access), allowing testing of OSC message handling and logging.
- To test hardware code without physical HAT, mock `automationhat` in unit tests or use dependency injection.

## Troubleshooting
- No messages appear on remote host:
  - Verify network connectivity and firewall rules between the Pi and remote host.
  - Check `journalctl -u osc-automationhat` for logged errors.
  - Try sending an OSC message manually to the server to confirm inbound handling (use `python-osc` client).
- Script exits unexpectedly:
  - Check logs: `journalctl -xe` or `journalctl -u osc-automationhat`.
  - Ensure required Python packages are installed and compatible versions are used.
- Reboot not working:
  - If `/restart/0 1` is not triggering reboot, ensure the service user can run `sudo reboot` non-interactively.
- LED writhes or brightness instead of on/off:
  - The original code used fractional values (e.g. `light.comms.write(0.1)` to flash); the refactored script preserves behavior for handler writes but uses integer states for inbound commands. If you need different LED flashing semantics, modify the LED handler accordingly.

## Development / Code structure
- `OSCautomationhat.py` (refactored) contains:
  - `OSCAutomationHat` class — owns:
    - OSC server and dispatcher (python-osc)
    - ADC polling thread
    - Main loop thread that checks digital inputs and sends heartbeat
    - `threading.Event` for stop requests and `threading.Lock` to protect `input_state` and `adc_state`.
  - CLI argument parsing and `main()` entry point with an `if __name__ == "__main__":` guard.
  - Logging is performed with `logging` to the systemd journal.

Key design goals:
- Avoid busy-waiting loops by using `Event.wait(timeout)`.
- Perform a single OSC client creation per remote host and reuse it.
- Clean shutdown: set stop event, shutdown server, join threads, and turn off lights.

## Testing
- Unit tests should mock `automationhat` and `udp_client.SimpleUDPClient` to verify:
  - ADC changes are detected and messages are sent.
  - Digital input changes send the expected OSC messages.
  - Handlers parse indices and only affect expected outputs.
  - Shutdown path sets event and joins threads.
- Manual tests:
  - Start the daemon and use an OSC client tool to send messages to the server port and verify hardware or logs reflect the changes.
  - Run a UDP capture (tcpdump) or a small python-osc server to observe outgoing OSC messages.

## Contributing
Contributions welcome. Please:
- Open issues to discuss proposed changes.
- Create small, focused PRs and include tests where appropriate.
- Follow the existing code style and keep hardware-dependent code guarded for dry-mode testability.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
