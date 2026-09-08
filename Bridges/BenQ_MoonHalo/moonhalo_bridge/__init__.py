"""MoonHalo Bridge: turns Hubitat requests into DDC/CI writes to the BenQ
RD280UG's MoonHalo backlight. This package provides the DDC port, the
MoonHalo model, the Flask HTTP layer, and a command-line mode covering both
hands-on DDC access (`monitors`/`read`/`write`) and serving the HTTP bridge
(`serve`).
"""

#: Bridge version, kept in lockstep with the Driver's header version.
__version__ = "0.0.6"
