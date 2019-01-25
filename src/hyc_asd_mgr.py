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
import requests
import socket
import traceback

from threading import Lock, Thread
from multiprocessing.dummy import Pool
from filelock import FileLock

from ha_lib.python.ha_lib import *
from utils import *

#
# Global services dictionary.
# Any new method to be supported must be added into this dictionary.
#
COMPONENT_SERVICE = "aerospike"
VERSION           = "v1.0"
HTTP_OK           = falcon.HTTP_200
HTTP_ACCEPTED     = falcon.HTTP_202
HTTP_UNAVAILABLE  = falcon.HTTP_503
HTTP_ERROR        = falcon.HTTP_400
UDF_DIR           = "/etc/aerospike"
STATUS_DIR        = "/var/log/aerospike/pio"

MESH_CONFIG_FILE       = "/etc/aerospike/aerospike_mesh.conf"
MULTICAST_CONFIG_FILE  = "/etc/aerospike/aerospike_multicast.conf"
MODDED_FILE            = "/etc/aerospike/modded.conf"
FILE_IN_USE            = None

LOCK_FILE = "/etc/aerospike/lock"

headers = {'Content-type': 'application/json'}
cert    = None
h       = "http"

REQ_ID            = 0

class ComponentStop(object):

    def on_get(self, req, resp):
        resp.status = HTTP_OK

def is_service_up():
    cmd = "pidof asd"
    ret = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=True)
    out, err = ret.communicate()
    status = ret.returncode

    if status:
        return False

    return True

def create_mesh_config(mesh_addrs, mesh_port):
    with open(MESH_CONFIG_FILE, 'r') as input_file, open(MODDED_FILE, 'w+') as output_file:
        filedata = input_file.readlines()

        update_port = 0
        for n, line in enumerate(filedata):
            if line.startswith("#"):
                output_file.write(filedata[n])
                continue

            elif line.strip().startswith("mode mesh"):
                update_port = 1
                output_file.write(filedata[n])
                continue

            elif line.strip().startswith("port") and update_port:
                filedata[n] = "\t\tport %s\n" %mesh_port
                output_file.write(filedata[n])
                for ip in mesh_addrs.split(","):
                    new_str = "\t\tmesh-seed-address-port %s %s\n" %(ip, mesh_port)
                    output_file.write(new_str)

                update_port = 0
                continue

            else:
                output_file.write(filedata[n])
                continue

    log.debug("Mesh config created")
    return

def create_multicast_config(multi_addr, multi_port):
    with open(MULTICAST_CONFIG_FILE, 'r') as input_file, open(MODDED_FILE, 'w+') as output_file:
        filedata = input_file.readlines()

        update_port = 0
        for n, line in enumerate(filedata):
            if line.startswith("#"):
                output_file.write(filedata[n])
                continue
            elif line.strip().startswith("multicast-group"):
                filedata[n] = "\t\tmulticast-group %s\n" %multi_addr
                output_file.write(filedata[n])
                update_port = 1
                continue
            elif line.strip().startswith("port") and update_port:
                filedata[n] = "\t\tport %s\n" %multi_port
                output_file.write(filedata[n])
                update_port = 0
                continue
            else:
                output_file.write(filedata[n])
                continue

    log.debug("Multicast config created")
    return

def start_asd_service():
    if FILE_IN_USE:
        cmd = "/usr/bin/asd --config-file %s" %FILE_IN_USE
    else:
        cmd = "/usr/bin/asd"

    log.debug("Executing %s" %cmd)
    return os.system(cmd)

def is_service_avaliable():
    cmd = "aql -c \"show namespaces\""
    ret = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=True)
    out, err = ret.communicate()
    status = ret.returncode
    if status:
        return False

    return True

class RegisterUDF(object):

    def on_post(self, req, resp):

        log.debug("In RegisterUDF")
        data = req.stream.read()
        data = data.decode()

        # We may be running Register UDF just after starting the docker
        # where asd service may not been started yet, wait for some time
        retry_cnt = 12
        while retry_cnt:
           if is_service_avaliable():
              break
           else:
              time.sleep(5)
              retry_cnt = retry_cnt - 1
              log.debug("Retrying register_udf. Aerospike daemon is still not up.")

        if retry_cnt == 0:
           resp.status = HTTP_UNAVAILABLE
           log.debug("UDF apply failed because Aerospike daemon is not running.")
           return

        data_dict = load_data(data)
        udf_file  = data_dict['udf_file']
        log.debug("Register UDF file : %s" %udf_file)
        udf_path = '%s/%s' %(UDF_DIR, udf_file)
        log.debug("Register UDF path : %s" %udf_path)

        if os.path.isfile(udf_path) == False:
            log.debug("Register UDF file not present: %s" %udf_path)
            resp.status = HTTP_ERROR
            return

        cmd = "aql -c \"register module '%s'\"" %udf_path
        log.debug("Register UDF cmd is : %s" %cmd)
        ret = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=True)
        out, err = ret.communicate()
        status = ret.returncode
        if status:
            resp.status = HTTP_ERROR

        resp.status = HTTP_OK

class UnRegisterUDF(object):

    def on_post(self, req, resp):

        log.debug("In UnRegisterUDF")
        data = req.stream.read()
        data = data.decode()

        data_dict = load_data(data)
        udf_file  = data_dict['udf_file']
        log.debug("UnRegister UDF: %s" %udf_file)
        cmd = "aql -c \"remove module %s\"" %udf_file
        log.debug("UnRegister UDF cmd : %s" %cmd)
        ret = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=True)
        out, err = ret.communicate()
        status = ret.returncode
        #Ignore error case for now
        if status:
            resp.status = HTTP_OK

        resp.status = HTTP_OK

def get_self_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_nodes_in_cluster():
    cmd = "asadm -e 'show config cluster'"
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = p.communicate()
    if p.returncode != 0:
        log.error("Failed to get nodes in cluster")
        return -1

    out  = out.strip()

    for line in out.split("\n"):
        if line.startswith("NODE"):
            nodes = line.split()
            nodes.remove(':') if ':' in nodes else None
            nodes.remove('NODE') if 'NODE' in nodes else None
            break
    node_ips = []
    for node in nodes:
        node_ip = node.split(":")[0]
        node_ips.append(node_ip)

    self_ip = get_self_ip()
    node_ips.remove(self_ip) if self_ip in node_ips else None

    return node_ips

def get_config_on_host(namespace, set_name):

    # Sample output
    #objects=519:tombstones=0:memory_data_bytes=0:truncate_lut=0:deleting=false:stop-writes-count=0:set-enable-xdr=use-default:disable-eviction=false;

    cmd = "asinfo -v 'sets/%s/%s'" %(namespace, set_name)
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = p.communicate()
    if p.returncode != 0:
        log.error("Failed to get data for set: %s in ns: %s" %(set_name, namespace))
        return -1

    out  = out.strip()
    subs = out.split(":")

    cnt  = 0
    for sub in subs:
        if sub.startswith("stop-writes-count"):
            cnt = sub.split("=")[1]
            break

    return cnt

def set_config_on_host(namespace, set_name, vm_quota):

    curr_cnt = get_config_on_host(namespace, set_name)

    if curr_cnt == -1:
        log.error("Failed to set config as get failed")
        return -1

    set_total_quota = int(curr_cnt) + vm_quota

    cmd = "asinfo -v \"set-config:context=namespace;id=%s;set=%s;set-stop-writes-count=%s\""\
                 %(namespace, set_name, set_total_quota)
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = p.communicate()
    if p.returncode != 0:
        log.error("Failed to get data for set: %s in ns: %s" %(set_name, namespace))
        return -1

    log.debug("Shri: set_config_on_host success")

    return 0

def update_cnt_other(host, data, vmid):
    #TODO: Handle custom ports
    log.debug("\nhttp://%s:8000/%s/v1.0/update_set_count?vm_id=%s\n\n"  %(host, service_type, vmid))
    r = requests.post("http://%s:8000/%s/v1.0/update_set_count?vm_id=%s"
                %(host, service_type, vmid),
                    data=json.dumps(data),
                    headers=headers,
                    cert=cert,
                    verify=False)
    log.debug(r)
    return r.status_code

def lock_and_set(vm_id, req_id, data, namespace, set_name, vm_quota):
    log.debug("Shri:  lock_and_set enter")
    node_ips = get_nodes_in_cluster()

    lck_file = LOCK_FILE + "_" + namespace + "_" + set_name
    f_lock   = FileLock(lck_file)

    with f_lock.acquire(poll_intervall=1):
        log.debug("Locked for set_name: %s in ns: %s with cnt:%s"\
                         %(set_name, namespace, vm_quota))
        if data['is_master'] and len(node_ips):
            pool = Pool(len(node_ips))
            futures = []
            data['is_master'] = 0
            data['req_id']    = req_id

            for node in node_ips:
                futures.append(pool.apply_async(update_cnt_other,
					(node, data, vm_id)))

            for future in futures:
                #if future.get() == HTTP_OK or future.get() == HTTP_ACCEPTED:
                if future.get() == 202 or future.get() == 200:
                    continue
                else:
                    #TODO: Handle error
                    return -1

        rc = set_config_on_host(namespace, set_name, vm_quota)
        f_lock.release()

    log.debug("UnLocked for set_name: %s in ns: %s with cnt:%s" %(set_name, namespace, vm_quota))
    return rc

def create_forks(vm_id, req_id, data, namespace, set_name, vm_quota):
    try:
        pid = os.fork()
        if pid == 0:
            ret = lock_and_set(vm_id, req_id, data, namespace, set_name, vm_quota)
            log.debug("Return of lock_and_set: %s" %ret)

            if ret:
                status = "ERROR"
            else:
                status = "SUCCESS"

            os.system("touch %s/%s_%s_%s" %(STATUS_DIR, req_id, vm_id, status))
            sys.exit(ret)
    except Exception as e:
        traceback.print_exc()
        log.error("Update cnt failed err: %s" %e)
        return 1

    log.debug("Async set update started for vmid: %s" %vm_id)
    return 0

def get_update_cnt_status(vm_id, req_id, is_master):

    log.debug("Received %s, %s, %s" %(type(vm_id), type(req_id), type(is_master)))
    log.debug("Received %s, %s, %s" %((vm_id), (req_id), (is_master)))

    node_ips    = get_nodes_in_cluster()

    log.debug("Starting get_update_cnt_status")
    if is_master and len(node_ips):
        is_master = 0

        for node in node_ips:
            url = "http://%s:8000/%s/v1.0/update_set_count?vm_id=%s&req_id=%s"\
                    "&is_master=%s" %(node, service_type, vm_id, req_id, is_master)
            log.debug("Sending url: %s" %url)
            r = requests.get(url)
            if r.status_code != 200:
                log.error("Sending rest failed for node:" %node)
                return -1

            resp = r.json()

            #if r.json["status"] == -1:
            if resp["status"] == -1:
                log.error("Setting Update cnt failed for node:" %node)
                return -1

            #elif r.json["status"] == 1:
            elif resp["status"] == 1:
                log.debug("Setting Update cnt in progress for node:" %node)

            log.debug("Status: %s from node: %s " %(r.status_code, node))

    f_str = "%s/%s_%s_" %(STATUS_DIR, req_id, vm_id)

    if os.path.exists(f_str + "SUCCESS"):
        log.debug("get_update_cnt_status returning success :)")
        return 0
    elif os.path.exists(f_str + "ERROR"):
        log.debug("get_update_cnt_status returning error :(")
        return -1
    else:
        log.debug("get_update_cnt_status returning error :|")
        return 1

class UpdateSetCount(object):

    def on_post(self, req, resp):

        log.debug("In UpdateSetCount")

        data = req.stream.read()
        data = data.decode()

        data_dict = load_data(data)
        vm_id     = req.get_param("vm_id")

        if not data_dict['namespace'] or not data_dict['set']\
                or not data_dict['vm_quota'] or not 'is_master' in data_dict\
                or not vm_id:
            err_msg = "Invalid arguments provided"
            log.error(err_msg)
            resp.body   = json.dumps({"msg": err_msg})
            resp.status = HTTP_ERROR
            return

        global REQ_ID
        REQ_ID += 1
        rc = create_forks(vm_id, REQ_ID, data_dict, data_dict['namespace'], data_dict['set'],
                                data_dict['vm_quota'])
        if rc:
            err_msg = "Failed to set config for vmid: %s" %vm_id
            log.error(err_msg)
            resp.body   = json.dumps({"msg": err_msg})
            resp.status = HTTP_ERROR
            return

        resp.body   = json.dumps({"req_id": REQ_ID})
        resp.status = HTTP_ACCEPTED
        return

    def on_get(self, req, resp):

        log.debug("In GET UpdateSetCount")

        vm_id     = int(req.get_param("vm_id"))
        req_id    = int(req.get_param("req_id"))
        is_master = int(req.get_param("is_master"))

        if vm_id is None or req_id is None or is_master is None:
            err_msg = "Incorrent params given. Received vm_id:%s, req_id:%s,\
                                    is_master:%s" %(vm_id, req_id, is_master)
            log.debug(err_msg)
            resp.body   = json.dumps({"msg": err_msg})
            resp.status = HTTP_ERROR
            return

        rc = get_update_cnt_status(vm_id, req_id, is_master)

        if rc == 1:
            status_msg = "Update_cnt not yet complete"
        elif rc == -1:
            status_msg = "Not all nodes succeded to update_cnt"
        elif rc == 0:
            status_msg = "Successfully updated cnt everywhere"

        resp.body   = json.dumps({"status": rc, "msg": status_msg})
        resp.status = HTTP_OK
        return

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
        log.debug("HALib started")

    def on_post(self, req, resp, doc):
        if not self.started:
            ret = start_asd_service()
            if ret:
                log.debug("Failed to start asd service")
                resp.status = HTTP_UNAVAILABLE
                return

            self.started = True
            self.start()
            log.debug("Waiting for asd service to come up")
            time.sleep(10)
            os.system("touch %s" %LOCK_FILE)
            resp.status  = HTTP_OK
            return

        else:
            #Nothing to do. Return Success
            resp.status  = HTTP_OK
            pass

    def run(self):
        while (is_service_up()):
            self.halib.set_health(True)
            log.debug("Updated health lease")
            time.sleep(self.halib.get_health_lease()/ 3)

        log.debug("asd health is down")
        self.started = False
        log.debug("%s service is down" %COMPONENT_SERVICE)
        self.halib.set_health(False)
        return

services = {
	'register_udf': RegisterUDF(),
	'unregister_udf': UnRegisterUDF(),
	'update_set_count' : UpdateSetCount(),
	'component_stop' : ComponentStop(),
       }


args = ["etcdip", "svc_label", "svc_idx", "mode","ip", "port"]

etcd_server_ip = None
service_type   = None
service_idx    = None
mode           = None
ip_addr        = None
port_to_use    = None

for arg in sys.argv:
    if arg.startswith("etcdip"):
        etcd_server_ip = arg.split("=")[1]
        continue

    elif arg.startswith("svc_label"):
        service_type = arg.split("=")[1]
        continue

    elif arg.startswith("svc_idx"):
        service_idx = arg.split("=")[1]
        continue

    elif arg.startswith("mode"):
        mode = arg.split("=")[1]
        continue

    elif arg.startswith("ip"):
        ip_addr = arg.split("=")[1]
        continue

    elif arg.startswith("port"):
        port_to_use = arg.split("=")[1]
        continue


if mode != '':
    FILE_IN_USE = MODDED_FILE
    if mode == 'mesh':
        create_mesh_config(ip_addr, port_to_use)

    elif mode == 'multicast':
        create_multicast_config(ip_addr, port_to_use)

if etcd_server_ip == '' and service_type == '' and service_idx == '':
    etcd_server_ip = "127.0.0.1"
    service_type   = "AS_Server"
    service_idx    = 1

print (etcd_server_ip, service_type, service_idx, mode, ip_addr, port_to_use)

# Creating AsdManager instance
component_mgr  = ComponentMgr(etcd_server_ip, service_type, service_idx, VERSION)
