#!/usr/bin/env python3
import libvirt
import json
import socket
import time
import copy
import sys
import os
import argparse

from xml.dom import minidom

# https://libvirt-python.readthedocs.io

__version__='v0.1'

class Libvirt:
    def __init__(self):
        self.conn = libvirt.open("qemu:///system")
        if not self.conn:
            raise SystemExit("Failed to open connection to qemu:///system")
        self.domains = self.conn.listAllDomains()
        self.active_doms = {}
        for d in self.domains:
            if d.isActive():
                self.active_doms[d.name()] = d

    def getActiveDoms(self):
        return self.active_doms;

    def getDomainXML(self, dom):
        return dom.XMLDesc()

class VhostC:
    decoder = json.JSONDecoder()

    def __init__(self, address, port, timeout=100.0):
        self.sock = None
        self._request_id = 0
        self.timeout = timeout
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((address, int(port)))
        except socket.error as ex:
            raise SystemExit("ERR: Can't connect to vhostd")

    def __json_to_string(self, request):
        return json.dumps(request)

    def send(self, method, params=None):
        self._request_id += 1
        req = {
            'jsonrpc': '2.0',
            'method': method,
            'id': self._request_id
        }
        if params:
            req['params'] = copy.deepcopy(params)

        self.sock.sendall(self.__json_to_string(req).encode("utf-8"))
        return self._request_id

    def __string_to_json(self, request_str):
        try:
            obj, idx = self.decoder.raw_decode(request_str)
            return obj
        except ValueError:
            return None

    def recv(self):
        timeout = self.timeout
        response = None
        buf = ""

        self.sock.settimeout(timeout)
        try:
            buf += self.sock.recv(4096).decode("utf-8")
        except socket.timeout:
            raise SystemExit("vhostd Response Timeout")

        self.sock.settimeout(0.2)
        while True:
            try:
                buf += self.sock.recv(4096).decode("utf-8") #enough?, should pack len in message.
            except socket.timeout:
                break
        response = self.__string_to_json(buf)
        return response

    def getPFs(self):
        PFs = []
        params = {'list':True}
        self.send("mgmtpf", params)
        rsp = self.recv()
        if 'devices' in rsp['result']:
            devices = rsp['result']['devices']
            for pf in devices:
                PFs.append(pf["pf"])
        return PFs

    def getVFs(self, pf):
        VFs = []
        params = {'list':True, 'mgmtpf':pf}
        self.send("vf", params)
        rsp = self.recv()
        if 'devices' in rsp['result']:
            VFs = rsp['result']['devices']
        return VFs

    def version(self):
        self.send("version")
        rsp = self.recv()
        return rsp

class PCIinfo:
    vendor_device = {
        "0x1af4:0x1041": "Virtio network device (rev 01)",
        "0x1af4:0x1042": "Virtio block device (rev 01)"
        }
    def __init__(self):
        pass

    @classmethod
    def getPFInfo(cls, pf):
        pf_path=f'/sys/bus/pci/devices/{pf}'
        if not os.path.exists(pf_path):
            raise SystemExit(f'pf: {pf_path} is not exist')
        with open(f'{pf_path}/vendor', 'r') as f: vendor = f.read().strip('\n')
        with open(f'{pf_path}/device', 'r') as f: device = f.read().strip('\n')
        with open(f'{pf_path}/sriov_numvfs', 'r') as f: sriov_numvfs = int(f.read().strip('\n'))
        with open(f'{pf_path}/sriov_totalvfs', 'r') as f: sriov_totalvfs = int(f.read().strip('\n'))
        info = {"name":pf}
        info['type'] = cls.vendor_device[f'{vendor}:{device}']
        info['sriov_totalvfs'] = sriov_totalvfs
        info['sriov_numvfs'] = sriov_numvfs
        vfid_map = {}
        for i in range(sriov_numvfs):
            vf = os.path.basename(os.readlink(f"{pf_path}/virtfn{i}"))
            vfid_map[vf] = i+1 # vfid begins from 1
        info['vfid_map'] = vfid_map
        return info


class VhostdHelp:
    zero_uuid = "00000000-0000-0000-0000-000000000000"

    def __init__(self):
        self.devices = {}
        self.all_vfs = {}
        vhostc = VhostC("localhost",'12190')
        self.all_pfs = vhostc.getPFs()
        if not self.all_pfs:
            raise SystemExit("No PF added to vhostd")

        # get VF info vhostd and add vfid from sysfs
        for pf in self.all_pfs:
            info = PCIinfo.getPFInfo(pf)
            self.devices[pf] = info
            vf_list = vhostc.getVFs(pf)
            for vf in vf_list:
                vf_name = vf['vf']
                vf['pf'] = pf
                vf['vfid'] = info['vfid_map'][vf_name]
                self.all_vfs[vf["socket_file"]] = vf

        self.virt = Libvirt()
        self.doms = self.virt.getActiveDoms()

    def __get_vsocket_from_tag(self, xml, tagName):
        tag = xml.getElementsByTagName(tagName)
        vhostuser = [item for item in tag if item.getAttribute("type") == "vhostuser"]
        vsockets = [item.getElementsByTagName("source")[0].getAttribute('path') for item in vhostuser]
        return vsockets

    def __get_vsocket_from_tag_qemuarg(self, xml):
        tagQemuarg = xml.getElementsByTagName("qemu:arg")
        vsockets = []
        for i in tagQemuarg:
            value =i.getAttribute("value").split(',')
            matches = [item for item in value if 'path=' in item]
            vsockets += [ item.split("=")[1] for item in matches]
        return vsockets

    def get_vsocket_from_xml(self, vm_xml):
        vsockets = []
        xml = minidom.parseString(vm_xml)
        vmname = xml.getElementsByTagName("name")[0].firstChild.data

        # interface
        vsockets += self.__get_vsocket_from_tag(xml, "interface")
        vsockets += self.__get_vsocket_from_tag(xml, "disk")
        vsockets += self.__get_vsocket_from_tag_qemuarg(xml)
        return vsockets, vmname

    def __vm_vhostd_uuid_match_verify_one(self, vm_xml):
        vsockets, vmname = self.get_vsocket_from_xml(vm_xml)
        d = dict(self.all_vfs)

        vm_uuid = None
        # check all vsocket has same vm_uuid
        for vsock in vsockets:
            if not vsock in d: # not add to vhostd, skip
                continue
            if vm_uuid is None:
                vm_uuid = d[vsock]['vm_uuid']
            vf_uuid = d[vsock]['vm_uuid']
            if vf_uuid != vm_uuid:
                print(f"vsock:{vsock} uuid {vf_uuid} is not the same as {vm_uuid} in {vmname}")
                return False
            else:
                del d[vsock]

        # check all the other VFs don't have this vm_uuid
        for vsock, vf in d.items():
            vf_uuid = vf['vm_uuid']
            if vf_uuid != self.zero_uuid and vf_uuid == vm_uuid:
                print(f"vsock:{vsock} uuid {vf_uuid} belong to {vmname}, but not in VM xml")
                return False
        return True;

    def vm_vhostd_uuid_match_verify(self):
        result = True
        print()
        for name,dom in self.doms.items():
            xml = self.virt.getDomainXML(dom)
            if not self.__vm_vhostd_uuid_match_verify_one(xml):
                print(f"[x] UUID check FAIL for {name}")
                result = False
            else:
                print(f"[/] UUID check pass for {name}")
        print()
        return result

    def vm_vhostd_dump(self):

        print("\n== PF  ==")
        for d in self.devices.values():
            print(json.dumps(d, indent=2))

        d = dict(self.all_vfs)
        for name,dom in self.doms.items():
            xml = self.virt.getDomainXML(dom)
            vsockets, vmname = self.get_vsocket_from_xml(xml)
            print(f"\nVM: {vmname}")
            for vsock in vsockets:
                if vsock in d:
                    vf = d[vsock]
                    print(f"{vsock}: {vf['vf']}, {vf['vm_uuid']}, "
                          f"vfid={vf['vfid']}, configured={vf['configured']}, pf={vf['pf']}")
                    del d[vsock]
                else:
                    print(f"{vsock}: Not in vhostd")

        print("\n== Not added to VM ==")
        for vsock, vf in d.items():
            print(f"{vsock}: {vf['vf']}, {vf['vm_uuid']}, "
                  f"vfid={vf['vfid']}, configured={vf['configured']}, pf={vf['pf']}")

        print()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='vfe vhostd helper tool ' + __version__,
        usage='Default is checking uuid group'
        )

    parser.add_argument('-d', '--dump', action='store_true', dest='dump', help="Dump info")
    args = parser.parse_args()

    vhostd = VhostdHelp()

    if args.dump:
        vhostd.vm_vhostd_dump()
        sys.exit(0)

    if vhostd.vm_vhostd_uuid_match_verify() == False:
        print(f" !! verify fail !!\n")
