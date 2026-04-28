import socket

# _orig_getaddrinfo = socket.getaddrinfo
# def _getaddrinfo_fix_zoneid(host, *args, **kwargs):
#     if isinstance(host, str) and "%25" in host:
#         host = host.replace("%25", "%")
#     return _orig_getaddrinfo(host, *args, **kwargs)
# socket.getaddrinfo = _getaddrinfo_fix_zoneid

import numpy as np
import matplotlib.pyplot as plt
import time

from moku.instruments import Oscilloscope

osc = Oscilloscope('192.168.73.1', force_connect=True)

idn = osc.serial_number()
prop = osc.describe()

print('sjdfkljklsafd')
print(prop)
print('test')
