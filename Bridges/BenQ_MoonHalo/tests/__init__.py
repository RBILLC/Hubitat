import logging

# A bare FakeDdcPort() has no D9 register, so monitor detection (issue #40)
# warns once per model built in these tests. A handler on the logger keeps
# that off stderr; assertLogs still captures it where a test wants it.
logging.getLogger("moonhalo_bridge.ddc").addHandler(logging.NullHandler())
