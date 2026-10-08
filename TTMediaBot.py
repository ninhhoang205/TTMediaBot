import socket
import sys

# Prefer IPv4 resolution for fast and reliable network calls
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_first_getaddrinfo(*args, **kwargs):
    results = _orig_getaddrinfo(*args, **kwargs)
    ipv4 = [r for r in results if r[0] == socket.AF_INET]
    return ipv4 if ipv4 else results
socket.getaddrinfo = _ipv4_first_getaddrinfo

# Support UTF-8 encoding in Windows console for music titles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from typing import Optional

from os import path

from argparse import ArgumentParser

from bot import Bot, app_vars
from bot.config import save_default_file
from bot.sound_devices import SoundDeviceManager

parser = ArgumentParser()
parser.add_argument(
    "-c",
    "--config",
    help="Path to the configuration file",
    default=path.join(app_vars.directory, "config.json"),
)
parser.add_argument("-C", "--cache", help="Path to the cache file", default=None)
parser.add_argument("-l", "--log", help="Path to the log file", default=None)
parser.add_argument(
    "--devices", help="Show available devices and exit", action="store_true"
)
parser.add_argument(
    "--default-config",
    help='Save default config to "config_default.json" and exit',
    action="store_true",
)
parser.add_argument(
    "--cli",
    help="Run bot in command-line interface mode without GUI",
    action="store_true",
)
args = parser.parse_args()


def main(
    config: str = args.config,
    cache: Optional[str] = args.cache,
    log: Optional[str] = args.log,
    devices: bool = args.devices,
    default_config: bool = args.default_config,
    cli: bool = args.cli,
) -> None:
    if devices:
        bot = Bot(None, None, None)
        echo_sound_devices(bot.sound_device_manager)
        bot.close()
        sys.exit(0)
    elif default_config:
        save_default_file()
        print("Successfully dumped to config_default.json")
    elif cli:
        bot = Bot(config, cache, log)
        bot.initialize()
        try:
            bot.run()
        except KeyboardInterrupt:
            bot.close()
    else:
        from bot.gui import run_gui
        run_gui(config_path=config, cache_path=cache, log_path=log)


def echo_sound_devices(sound_device_manager: SoundDeviceManager):
    print("Output devices:")
    for i, device in enumerate(sound_device_manager.output_devices):
        print("\t{index}: {name}".format(index=i, name=device.name))
    print()
    print("Input devices:")
    for i, device in enumerate(sound_device_manager.input_devices):
        print("\t{index}: {name}".format(index=i, name=device.name))


if __name__ == "__main__":
    main()
