#!/usr/bin/env python3
import logging
import midori
import sys

logger = logging.getLogger("midori")

try:
    midori.init()
    midori.instance.run()
except Exception:
    logger.critical("Unhandled exception in Midori main loop. Report a bug!", exc_info=1)
except KeyboardInterrupt:
    midori.instance.api.send_raw("QUIT :rip")
finally:
    sys.exit(midori.instance.exit())