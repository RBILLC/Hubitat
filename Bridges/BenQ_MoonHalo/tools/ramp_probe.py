"""Drive the real MoonHalo through the Bridge model and print every DDC/CI
write with its timing, to verify a Ramp on the hardware without the Hub.

    py tools/ramp_probe.py brightness   # step 1 -> the remembered level
    py tools/ramp_probe.py colour       # colour -> 7, then a combined move back
    py tools/ramp_probe.py power        # off dims out, on relights, on mid dim-out turns around

Run from ``Bridges/BenQ_MoonHalo`` while the serving Bridge is idle. The probe
reads ``state.json`` for the halo's remembered state, works in its own state
file under ``tools/``, uses the serving Bridge's ``transition_seconds`` (or
``--sweep`` to override), and ends with the halo back at the remembered state.
The serving Bridge's own state file is never written. Each line shows the
time since the command, the gap from the previous write, the register and
value, and how long the ``SetVCPFeature`` call itself took (the write floor).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIDGE_DIR = HERE.parent
sys.path.insert(0, str(BRIDGE_DIR))

from moonhalo_bridge.config import load_config  # noqa: E402
from moonhalo_bridge.ddc import WindowsDdcPort  # noqa: E402
from moonhalo_bridge.model import MoonHaloModel  # noqa: E402


class TimedPort(WindowsDdcPort):
    """The real port, recording every write as (time, code, value, call cost)."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[float, int, int, float]] = []

    def write_vcp(self, code: int, value: int) -> None:
        started = time.monotonic()
        super().write_vcp(code, value)
        finished = time.monotonic()
        self.log.append((finished, code, value, finished - started))


def show(port: TimedPort, since: float) -> None:
    previous = since
    for landed, code, value, cost in port.log:
        print(
            "  +%.3fs  gap %.3fs  VCP %02X <- 0x%04X  (call %.0f ms)"
            % (landed - since, landed - previous, code, value, cost * 1000)
        )
        previous = landed
    port.log.clear()


def settle(seconds: float = 1.5) -> None:
    time.sleep(seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=["brightness", "colour", "power"])
    parser.add_argument("--sweep", type=float, default=None, help="override transition_seconds for this run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    live_config = load_config(BRIDGE_DIR / "config.json")
    live_state = json.loads((BRIDGE_DIR / "state.json").read_text(encoding="utf-8"))
    print("remembered state:", live_state)

    probe_state = HERE / "probe_state.json"
    probe_state.write_text(json.dumps(live_state), encoding="utf-8")
    config = load_config(BRIDGE_DIR / "config.json")
    overrides = {"state_file": probe_state, "log_file": None}
    if args.sweep is not None:
        overrides["transition_seconds"] = args.sweep
    config = type(config)(**{**config.__dict__, **overrides})
    print("transition_seconds:", config.transition_seconds)

    port = TimedPort()
    model = MoonHaloModel(port, config)
    level = live_state.get("last_level") or live_config.default_on_level
    colour = live_state.get("colortemp_step") or live_config.default_colortemp_step

    if args.scenario == "brightness":
        print("snap to level 1")
        model.set_level(1, transition=0)
        settle(0.5)
        port.log.clear()
        print("level 1 -> %d" % level)
        started = time.monotonic()
        model.set_level(level)
        print("  reply after %.3fs: %s" % (time.monotonic() - started, model.last_transition))
        settle()
        show(port, started)

    elif args.scenario == "colour":
        print("colour %d -> 7" % colour)
        started = time.monotonic()
        model.set_colortemp(7)
        print("  reply after %.3fs: %s" % (time.monotonic() - started, model.last_transition))
        settle()
        show(port, started)
        print("combined: brightness 10 (step 2), then colour %d 100 ms later" % colour)
        started = time.monotonic()
        model.set_level(10)
        time.sleep(0.1)
        model.set_colortemp(colour)
        print("  second reply after %.3fs: %s" % (time.monotonic() - started, model.last_transition))
        settle()
        show(port, started)
        print("restore level %d" % level)
        started = time.monotonic()
        model.set_level(level)
        settle()
        show(port, started)

    else:
        print("off")
        started = time.monotonic()
        reply = model.turn_off()
        print("  reply after %.3fs: %s power=%s level=%s" % (
            time.monotonic() - started, model.last_transition, reply["power"], reply["level"]))
        settle()
        show(port, started)
        time.sleep(1.0)
        print("on (dark)")
        started = time.monotonic()
        model.turn_on()
        print("  reply after %.3fs: %s immediate=%s" % (
            time.monotonic() - started, model.last_transition, model.last_writes))
        settle()
        show(port, started)
        print("off over 1.0 s, then on after 0.4 s (turnaround: D7 off must not appear)")
        started = time.monotonic()
        model.turn_off(1.0)
        time.sleep(0.4)
        model.turn_on()
        print("  on reply: %s immediate=%s" % (model.last_transition, model.last_writes))
        settle()
        show(port, started)
        if live_state.get("power") != "on":
            model.turn_off(0)
            print("restored power off")

    print("probe state:", json.loads(probe_state.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
