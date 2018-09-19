#!/usr/bin/env python
#
# Copyright 2018 Cachebox, Inc. All rights reserved. This software
# is property of Cachebox, Inc and contains trade secrects,
# confidential & proprietary information. Use, disclosure or copying
# this without explicit written permission from Cachebox, Inc is
# prohibited.
#
# Author: Cachebox, Inc (sales@cachebox.com)
#
import sys
import os
import time
import subprocess
import falcon
from threading import Lock, Thread

from ha_lib.python.ha_lib import *

#
# Global services dictionary.
# Any new method to be supported must be added into this dictionary.
#
COMPONENT_SERVICE = "aerospike"
VERSION           = "v1.0"
HTTP_OK           = falcon.HTTP_200
HTTP_UNAVAILABLE  = falcon.HTTP_503

class ComponentStop(object):

    def on_get(self, req, resp):
        resp.status = HTTP_OK

def dummy1():
    pass

def dummy2():
    pass

services = {
            'component_stop' : ComponentStop(),
            'dummy1' : dummy1(),
            'dummy2' : dummy2(),
           }

def is_service_up():
    cmd = "pidof asd"
    ret = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=True)
    out, err = ret.communicate()
    status = ret.returncode

    if status:
        return False

    return True


def create_aero_config(multi_addr, multi_port):
    with open('/modded_aero.conf', 'r') as f:
        filedata = f.readlines()

    update_port = 0
    for n, line in enumerate(filedata):
        if line.startswith("#"):
            continue
        if line.strip().startswith("multicast-group"):
            filedata[n] = "\t\tmulticast-group %s\n" %multi_addr
            update_port = 1
            continue
        if line.strip().startswith("port") and update_port:
            filedata[n] = "\t\tport %s\n" %multi_port
            update_port = 0
            break

    with open('/modded_aero.conf', 'w') as f:
        for line in filedata:
            f.write(line)

def start_asd_service():
    cmd = "/usr/bin/asd --config-file /modded_aero.conf"
    return os.system(cmd)

#
# ComponentMgr Class:
# Creates an instance of halib with itself.
# Mgr is started at first component_start
#
class ComponentMgr(Thread):
    def __init__(self, etcd_server_ip, service_type, service_idx, VERSION,
                   lease_interval = 120):

        Thread.__init__(self)
        self.setDaemon(True)
        self.started = False
        services["component_start"] = self

        self.halib = HALib(etcd_server_ip, VERSION, service_type, services,
                                service_idx)
        print("HALib started")

    def on_post(self, req, resp, doc):
        if not self.started:
            ret = start_asd_service()
            if ret:
                print("Failed to start asd service")
                resp.status = HTTP_UNAVAILABLE
                return

            self.started = True
            self.start()
            time.sleep(10)
            resp.status  = HTTP_OK

        else:
            #Nothing to do. Return Success
            resp.status  = HTTP_OK
            pass

    def run(self):
        while (is_service_up()):
            self.halib.set_health(True)
            time.sleep(self.halib.get_health_lease()/ 2)

        print("asd health is down")
        self.started = False
        print("%s service is down" %COMPONENT_SERVICE)
        self.halib.set_health(False)
        return


argc           = len(sys.argv)
etcd_server_ip = sys.argv[argc - 5]
service_type   = sys.argv[argc - 4]
service_idx    = sys.argv[argc - 3]
multi_addr     = sys.argv[argc - 2]
multi_port     = sys.argv[argc - 1]

create_aero_config(multi_addr, multi_port)

# Creating AsdManager instance
component_mgr  = ComponentMgr(etcd_server_ip, service_type, service_idx, VERSION)
