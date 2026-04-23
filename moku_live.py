"""Live voltage plot vanaf een Moku:Go via de Oscilloscope-API.

Gebruik:
    python moku_live.py                       # gebruikt default adres
    python moku_live.py --address "[fe80::...%0]"
    python moku_live.py --address 192.168.x.x --timebase 2e-3
    python moku_live.py --channels 1 --coupling AC --range 50Vpp --no-trigger
"""
import argparse
import socket
import sys

# IPv6 link-local over USB-C heeft een zone-ID (%41 voor interface 41) nodig.
# De URL-pijplijn in urllib3+requests percent-decodeert de zone-ID waardoor
# '%41' verdwijnt. DEFAULT_ADDRESS is daarom triple-geëscaped ('%252541').
# Op socket-niveau moeten we '%25' weer terug naar '%' draaien zodat
# Windows' getaddrinfo het als echte zone-ID herkent.
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_fix_zoneid(host, *args, **kwargs):
    if isinstance(host, str) and "%25" in host:
        host = host.replace("%25", "%")
    return _orig_getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = _getaddrinfo_fix_zoneid

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from moku.instruments import Oscilloscope


DEFAULT_ADDRESS = "[fe80::7269:79ff:feb9:1072%252541]"  # MokuGo via USB-C; zone-ID 41 triple-geëscaped


def parse_args():
    p = argparse.ArgumentParser(description="Moku:Go live voltage plot")
    p.add_argument("--address", default=DEFAULT_ADDRESS,
                   help="IP of IPv6 link-local adres van de Moku")
    p.add_argument("--timebase", type=float, default=1e-3,
                   help="Halve tijdspan in seconden (toont -T..+T)")
    p.add_argument("--channels", default="1,2",
                   help="Komma-gescheiden lijst: 1, 2, of 1,2")
    p.add_argument("--interval-ms", type=int, default=100,
                   help="Verversingsinterval van de plot in ms")

    # Frontend (set_frontend) — Moku:Go heeft alleen 1 MOhm ingang
    p.add_argument("--coupling", default="DC", choices=["DC", "AC"],
                   help="Input coupling per kanaal")
    p.add_argument("--impedance", default="1MOhm", choices=["1MOhm"],
                   help="Input impedance (Moku:Go heeft alleen 1MOhm)")
    p.add_argument("--range", dest="range_", default="10Vpp",
                   choices=["10Vpp", "50Vpp"],
                   help="Input voltage range")

    # Trigger
    p.add_argument("--trigger", dest="trigger", action="store_true", default=True,
                   help="Schakel edge-trigger in (default)")
    p.add_argument("--no-trigger", dest="trigger", action="store_false",
                   help="Free-running, geen trigger")
    p.add_argument("--trigger-source", default="Input1",
                   help="Trigger source (bijv. Input1, Input2)")
    p.add_argument("--trigger-level", type=float, default=0.0,
                   help="Trigger level in volt")
    p.add_argument("--trigger-edge", default="Rising",
                   choices=["Rising", "Falling", "Both"],
                   help="Trigger edge")
    return p.parse_args()


def run(address, timebase, channels, interval_ms,
        coupling, impedance, range_,
        trigger, trigger_source, trigger_level, trigger_edge):
    osc = Oscilloscope(address, force_connect=True)
    try:
        for ch in channels:
            osc.set_frontend(ch, impedance=impedance,
                             coupling=coupling, range=range_)
            osc.set_source(ch, f"Input{ch}")

        if trigger:
            osc.set_trigger(type="Edge", source=trigger_source,
                            level=trigger_level, edge=trigger_edge)

        osc.set_timebase(-timebase, timebase)

        fig, ax = plt.subplots(figsize=(9, 5))
        lines = {ch: ax.plot([], [], label=f"ch{ch}")[0] for ch in channels}
        ax.set_xlabel("tijd (s)")
        ax.set_ylabel("spanning (V)")
        ax.set_title(f"Moku:Go live — {address}")
        ax.grid(True)
        ax.legend()

        logged_missing = set()

        def update(_frame):
            data = osc.get_data()
            if not data or "time" not in data:
                return list(lines.values())
            t = data["time"]
            for ch in channels:
                values = data.get(f"ch{ch}")
                if not values:
                    if ch not in logged_missing:
                        print(f"waarschuwing: ch{ch} niet in get_data() response "
                              f"— controleer --channels", file=sys.stderr)
                        logged_missing.add(ch)
                    continue
                lines[ch].set_data(t, values)
            ax.relim()
            ax.autoscale_view()
            return list(lines.values())

        _ani = FuncAnimation(fig, update, interval=interval_ms, blit=False,
                             cache_frame_data=False)
        try:
            plt.show()
        except KeyboardInterrupt:
            pass
    finally:
        osc.relinquish_ownership()


if __name__ == "__main__":
    args = parse_args()
    channels = [int(c) for c in args.channels.split(",")]
    run(args.address, args.timebase, channels, args.interval_ms,
        args.coupling, args.impedance, args.range_,
        args.trigger, args.trigger_source, args.trigger_level, args.trigger_edge)
