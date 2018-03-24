#!/usr/bin/env python3
"""
License:
  Copyright 2017 Anders Löwinger, anders@abundo.se

  This file is part of playsms_hilink_driver.

  playsms_hilink_driver is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  playsms_hilink_driver is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with playsms_hilink_driver.  If not, see <http://www.gnu.org/licenses/>.

"""

import sys
import logging
import logging.handlers


log = logging.getLogger('hilink_driver')
#log.setLevel(conf.log.level)

# remove all handlers
for hdlr in log.handlers:
    log.removeHandler(hdlr)

if sys.stdout.isatty():
    consolehandler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    consolehandler.setFormatter(formatter)
    log.addHandler(consolehandler)
else:
    syslogger = logging.handlers.SysLogHandler(address='/dev/log')
    formatter = logging.Formatter('%(module)s: %(levelname)s %(message)s')
    syslogger.setFormatter(formatter)
    log.addHandler(syslogger)

