"""MoonHalo Bridge: turns Hubitat requests into DDC/CI writes to the BenQ
RD280UG's MoonHalo backlight. This package provides the DDC port, the
MoonHalo model, the Flask HTTP layer, and a command-line mode covering both
hands-on DDC access (`monitors`/`read`/`write`) and serving the HTTP bridge
(`serve`). Brightness and colour-temperature writes to VCP D9 arrive in a
later ticket.
"""
