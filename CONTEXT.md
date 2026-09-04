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
