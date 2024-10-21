# Some scripts to help setup vfe vhostd enviroment

May need **root** privilege to run for libvirtd connection

## TODO
* Collect all logs on host

## Dependencies

    sudo pip3 install libvirt-python


## How

1. Check if same uuid VFs in vhostd are ALL in SAME VM

        sudo ./vfe-vdpa-info.py

        [/] UUID check pass for gen-l-vrt-295-005-CentOS-7.4
        [/] UUID check pass for gen-l-vrt-295-008-RH-8.2
        [/] UUID check pass for gen-l-vrt-295-007-CentOS-7.4

2. Dump VF slot/vfid/socket/sriov related info (done)

        sudo ./vfe-vdpa-info.py -d


        == PF  ==
        {
          "name": "0000:3b:00.2",
          "type": "Virtio network device (rev 01)",
          "sriov_totalvfs": 63,
          "sriov_numvfs": 63,
          "vfid_map": {
            "0000:3b:04.4": 1,
            "0000:3b:04.5": 2,
            ...
            }
        }

        VM: gen-l-vrt-295-005-CentOS-7.4
        /tmp/vfe-net0: 0000:3b:04.4, 8de2c370-4f4b-41a1-a107-3139fe8b7210, vfid=1, configured=True, pf=0000:3b:00.2
        /tmp/vfe-net1: 0000:3b:04.5, 8de2c370-4f4b-41a1-a107-3139fe8b7210, vfid=2, configured=True, pf=0000:3b:00.2
        /tmp/vfe-net2: 0000:3b:04.6, 8de2c370-4f4b-41a1-a107-3139fe8b7210, vfid=3, configured=True, pf=0000:3b:00.2

        == Not added to VM ==
        /tmp/vfe-net16: 0000:3b:06.4, 8de2c370-4f4b-41a1-a107-3139fe8b7211, vfid=17, configured=False, pf=0000:3b:00.2
        /tmp/vfe-net17: 0000:3b:06.5, 8de2c370-4f4b-41a1-a107-3139fe8b7211, vfid=18, configured=False, pf=0000:3b:00.2


2. Verify VM xml is good for vDPA

        sudo ./vfe-vdpa-info.py  -i -n  gen-l-vrt-295-005-CentOS-7.4
        sudo ./vfe-vdpa-info.py  -i -f  /images/testbf3/configs/gen-l-vrt-295-005-CentOS-7.4.xml

        == gen-l-vrt-295-005-CentOS-7.4 ==

        [-] No xmlns:qemu in tag domain? you can not use <qemu:commandline>
        [/] hugepage size 1048576
        [/] QEMU binary: /images/testbf3/sw/qemu/bin/qemu-system-x86_64
        [/] Set numa memory as shared

    * xmlns:qemu in domain

        <domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>

    * hugepage as backend

          <memoryBacking>
            <hugepages>
              <page size='1048576' unit='KiB'/>
            </hugepages>
          </memoryBacking>

    * QEMU binary

        <emulator>/images/testvfe/sw/qemu/bin/x86_64-softmmu/qemu-system-x86_64</emulator>

    * Memory as shared

        <cpu mode='host-model' check='partial'>
          <numa>
            <cell id='0' cpus='0-3' memory='8388608' unit='KiB' memAccess='shared'/>
          </numa>
        </cpu>
