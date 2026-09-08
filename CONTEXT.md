# Hubitat MoonHalo Bridge

Controls the MoonHalo backlight of a BenQ RD280UG monitor from a Hubitat hub by relaying commands through a helper service on the Windows PC the monitor is attached to.

## Language

**MoonHalo**:
The LED backlight built into the rear of the BenQ RD280UG monitor. The only monitor feature this project controls.
_Avoid_: Moon Halo, halo light, bias light, backlight

**Hub**:
The Hubitat Elevation hub that runs the driver and issues commands.
_Avoid_: Hubitat (when meaning the physical hub), controller

**Bridge**:
The HTTP service running on the Windows PC that turns a request from the Hub into a DDC/CI write to the monitor.
_Avoid_: PC bridge, server, Flask app, script

**Driver**:
The Groovy device driver installed on the Hub that presents the MoonHalo as a dimmable, colour-temperature light.
_Avoid_: device handler, integration

**VCP register**:
A DDC/CI feature code on the monitor that a value is written to. MoonHalo brightness and colour temperature share one register, distinguished by an encoding scheme.
_Avoid_: VCP code, opcode, command

**Encoding scheme**:
The rule the Bridge uses to pack a MoonHalo setting into the 16-bit value written to its VCP register. Two are known: the channel scheme and the packed scheme.
_Avoid_: formula, multiplexing, format

**Hardware step**:
A value in the monitor's own units for a MoonHalo setting, such as colour temperature 1 to 7.
_Avoid_: raw value, native value, monitor value

**Level**:
Brightness as the Hub expresses it, a percentage from 0 to 100. Only the Bridge converts a level into a hardware step.
_Avoid_: brightness percent, dim level

**Connection state**:
Whether the Hub could reach the Bridge on its last attempt: online, offline, or unknown. Offline is how the Driver shows a MoonHalo whose PC is powered down, like a bulb with no power.
_Avoid_: health, presence, reachability

**Transition**:
The time over which the Bridge moves the MoonHalo from its applied setting to the target setting. Zero means the change is immediate.
_Avoid_: fade, transition time, tt, duration (when meaning the concept)

**Ramp**:
The sequence of hardware-step writes that realises a Transition, one write per hardware step moved, evenly spaced over the Transition.
_Avoid_: animation, interpolation

**Sweep time**:
The Transition a full nine-step brightness move takes. The Bridge's default pace and the Driver's Default transition preference are Sweep times: every move keeps the same interval between writes, a ninth of the Sweep time, so a short move finishes sooner. A Transition passed with a command is instead the total time for that move.
_Avoid_: default transition (when meaning the concept), rate, speed

**Target state**:
The MoonHalo setting most recently commanded. What the Bridge reports to the Hub, whether or not the Ramp has reached it.
_Avoid_: requested state, desired state

**Applied state**:
The MoonHalo setting the Bridge last wrote to the monitor. Equals the Target state once a Ramp completes.
_Avoid_: current state, actual state, hardware state
