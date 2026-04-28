"""Live voltage-plot van de fotodetector via Moku:Go Oscilloscope.

Gebruik:
    python moku_live.py                              # default Input1, 10ms timebase
    python moku_live.py --address 192.168.x.x        # ander IPv4-adres
    python moku_live.py --channel 2                  # fotodetector op Input2
    python moku_live.py --range 50Vpp --timebase 5e-3
    python moku_live.py --trigger --trigger-level 0.5
"""
import argparse
import sys

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from moku.instruments import Oscilloscope


DEFAULT_ADDRESS = "192.168.73.1"  # MokuGo in Access Point mode


def parse_args():
    p = argparse.ArgumentParser(description="MokuGo live fotodetector plot")
    p.add_argument("--address", default=DEFAULT_ADDRESS,
                   help="IPv4 adres van de Moku")
    p.add_argument("--channel", type=int, default=1, choices=[1, 2],
                   help="Moku-input waarop de fotodetector zit")
    p.add_argument("--timebase", type=float, default=10e-3,
                   help="Halve tijdspan in seconden (toont -T..+T)")
    p.add_argument("--interval-ms", type=int, default=100,
                   help="Verversingsinterval van de plot in ms")
    p.add_argument("--coupling", default="DC", choices=["DC", "AC"])
    p.add_argument("--range", dest="range_", default="10Vpp",
                   choices=["10Vpp", "50Vpp"])
    p.add_argument("--trigger", action="store_true",
                   help="Edge-trigger inschakelen (default: free-running)")
    p.add_argument("--trigger-level", type=float, default=0.0,
                   help="Trigger level in volt")
    p.add_argument("--trigger-edge", default="Rising",
                   choices=["Rising", "Falling", "Both"])
    return p.parse_args()


def run(address, channel, timebase, interval_ms, coupling, range_,
        trigger, trigger_level, trigger_edge):
    print(f"Verbinden met MokuGo op {address} ...")
    osc = Oscilloscope(address, force_connect=True)
    try:
        osc.set_frontend(channel, impedance="1MOhm",
                         coupling=coupling, range=range_)
        osc.set_source(channel, f"Input{channel}")

        if trigger:
            osc.set_trigger(type="Edge", source=f"Input{channel}",
                            level=trigger_level, edge=trigger_edge)

        osc.set_timebase(-timebase, timebase)

        fig, ax = plt.subplots(figsize=(9, 5))
        line, = ax.plot([], [], lw=1.2)
        ax.set_xlabel("tijd (s)")
        ax.set_ylabel("spanning (V)")
        ax.set_title(f"Fotodetector — Input{channel} @ {address}")
        ax.grid(True)
        ax.set_xlim(-timebase, timebase)

        def update(_frame):
            data = osc.get_data()
            if not data or "time" not in data:
                return (line,)
            values = data.get(f"ch{channel}")
            if not values:
                print(f"waarschuwing: ch{channel} leeg in response",
                      file=sys.stderr)
                return (line,)
            line.set_data(data["time"], values)
            ax.relim()
            ax.autoscale_view(scalex=False, scaley=True)
            return (line,)

        _ani = FuncAnimation(fig, update, interval=interval_ms,
                             blit=False, cache_frame_data=False)
        plt.show()
    finally:
        osc.relinquish_ownership()
        print("Verbinding losgelaten.")


if __name__ == "__main__":
    a = parse_args()
    run(a.address, a.channel, a.timebase, a.interval_ms,
        a.coupling, a.range_,
        a.trigger, a.trigger_level, a.trigger_edge)
