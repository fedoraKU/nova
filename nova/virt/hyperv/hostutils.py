# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Cloudbase Solutions Srl
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import ctypes
import sys

if sys.platform == 'win32':
    import wmi

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class HostUtils(object):
    def __init__(self):
        if sys.platform == 'win32':
            self._conn_cimv2 = wmi.WMI(moniker='//./root/cimv2')

    def get_cpus_info(self):
        cpus = self._conn_cimv2.query("SELECT * FROM Win32_Processor "
                                      "WHERE ProcessorType = 3")
        cpus_list = []
        for cpu in cpus:
            cpu_info = {'Architecture': cpu.Architecture,
                        'Name': cpu.Name,
                        'Manufacturer': cpu.Manufacturer,
                        'NumberOfCores': cpu.NumberOfCores,
                        'NumberOfLogicalProcessors':
                        cpu.NumberOfLogicalProcessors}
            cpus_list.append(cpu_info)
        return cpus_list

    def is_cpu_feature_present(self, feature_key):
        return ctypes.windll.kernel32.IsProcessorFeaturePresent(feature_key)

    def get_memory_info(self):
        """
        Returns a tuple with total visible memory and free physical memory
        expressed in kB.
        """
        mem_info = self._conn_cimv2.query("SELECT TotalVisibleMemorySize, "
                                          "FreePhysicalMemory "
                                          "FROM win32_operatingsystem")[0]
        return (long(mem_info.TotalVisibleMemorySize),
                long(mem_info.FreePhysicalMemory))

    def get_volume_info(self, drive):
        """
        Returns a tuple with total size and free space
        expressed in bytes.
        """
        logical_disk = self._conn_cimv2.query("SELECT Size, FreeSpace "
                                              "FROM win32_logicaldisk "
                                              "WHERE DeviceID='%s'"
                                              % drive)[0]
        return (long(logical_disk.Size), long(logical_disk.FreeSpace))

    def get_windows_version(self):
        return self._conn_cimv2.Win32_OperatingSystem()[0].Version
