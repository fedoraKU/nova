# vim: tabstop=4 shiftwidth=4 softtabstop=4

#  Copyright 2012 Cloudbase Solutions Srl
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

"""
Test suite for the Hyper-V driver and related APIs.
"""

import io
import mox
import os
import platform
import shutil
import time
import uuid

from nova.api.metadata import base as instance_metadata
from nova.compute import power_state
from nova.compute import task_states
from nova import context
from nova import db
from nova.image import glance
from nova.openstack.common import cfg
from nova import test
from nova.tests import fake_network
from nova.tests.hyperv import db_fakes
from nova.tests.hyperv import fake
from nova.tests.image import fake as fake_image
from nova.tests import matchers
from nova import utils
from nova.virt import configdrive
from nova.virt.hyperv import basevolumeutils
from nova.virt.hyperv import constants
from nova.virt.hyperv import driver as driver_hyperv
from nova.virt.hyperv import hostutils
from nova.virt.hyperv import livemigrationutils
from nova.virt.hyperv import networkutils
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import volumeutils
from nova.virt.hyperv import volumeutilsv2
from nova.virt import images

CONF = cfg.CONF
CONF.import_opt('vswitch_name', 'nova.virt.hyperv.vif')


class HyperVAPITestCase(test.TestCase):
    """Unit tests for Hyper-V driver calls."""

    def __init__(self, test_case_name):
        self._mox = mox.Mox()
        super(HyperVAPITestCase, self).__init__(test_case_name)

    def setUp(self):
        super(HyperVAPITestCase, self).setUp()

        self._user_id = 'fake'
        self._project_id = 'fake'
        self._instance_data = None
        self._image_metadata = None
        self._fetched_image = None
        self._update_image_raise_exception = False
        self._volume_target_portal = 'testtargetportal:3260'
        self._volume_id = '0ef5d708-45ab-4129-8c59-d774d2837eb7'
        self._context = context.RequestContext(self._user_id, self._project_id)
        self._instance_ide_disks = []
        self._instance_ide_dvds = []
        self._instance_volume_disks = []

        self._setup_stubs()

        self.flags(instances_path=r'C:\Hyper-V\test\instances',
                   vswitch_name='external',
                   network_api_class='nova.network.quantumv2.api.API',
                   force_volumeutils_v1=True)

        self._conn = driver_hyperv.HyperVDriver(None)

    def _setup_stubs(self):
        db_fakes.stub_out_db_instance_api(self.stubs)
        fake_image.stub_out_image_service(self.stubs)
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)

        def fake_fetch(context, image_id, target, user, project):
            self._fetched_image = target
        self.stubs.Set(images, 'fetch', fake_fetch)

        def fake_get_remote_image_service(context, name):
            class FakeGlanceImageService(object):
                def update(self_fake, context, image_id, image_metadata, f):
                    if self._update_image_raise_exception:
                        raise vmutils.HyperVException(
                            "Simulated update failure")
                    self._image_metadata = image_metadata
            return (FakeGlanceImageService(), 1)
        self.stubs.Set(glance, 'get_remote_image_service',
                       fake_get_remote_image_service)

        def fake_sleep(ms):
            pass
        self.stubs.Set(time, 'sleep', fake_sleep)

        self.stubs.Set(pathutils, 'PathUtils', fake.PathUtils)
        self._mox.StubOutWithMock(fake.PathUtils, 'open')

        self._mox.StubOutWithMock(vmutils.VMUtils, 'vm_exists')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_vm')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'destroy_vm')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'attach_ide_drive')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_scsi_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_nic')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'set_vm_state')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'list_instances')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_summary_info')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'take_vm_snapshot')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'remove_vm_snapshot')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'set_nic_connection')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_iscsi_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_ide_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_attached_disks_count')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'attach_volume_to_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'get_mounted_disk_by_drive_number')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'detach_vm_disk')

        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'create_differencing_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'reconnect_parent_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'merge_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'get_vhd_parent_path')

        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_cpus_info')
        self._mox.StubOutWithMock(hostutils.HostUtils,
                                  'is_cpu_feature_present')
        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_memory_info')
        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_volume_info')
        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_windows_version')

        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'get_external_vswitch')
        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'create_vswitch_port')

        self._mox.StubOutWithMock(livemigrationutils.LiveMigrationUtils,
                                  'live_migrate_vm')
        self._mox.StubOutWithMock(livemigrationutils.LiveMigrationUtils,
                                  'check_live_migration_config')

        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'volume_in_mapping')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_session_id_from_mounted_disk')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_device_number_for_target')

        self._mox.StubOutWithMock(volumeutils.VolumeUtils,
                                  'login_storage_target')
        self._mox.StubOutWithMock(volumeutils.VolumeUtils,
                                  'logout_storage_target')
        self._mox.StubOutWithMock(volumeutils.VolumeUtils,
                                  'execute_log_out')

        self._mox.StubOutWithMock(volumeutilsv2.VolumeUtilsV2,
                                  'login_storage_target')
        self._mox.StubOutWithMock(volumeutilsv2.VolumeUtilsV2,
                                  'logout_storage_target')
        self._mox.StubOutWithMock(volumeutilsv2.VolumeUtilsV2,
                                  'execute_log_out')

        self._mox.StubOutWithMock(shutil, 'copyfile')
        self._mox.StubOutWithMock(shutil, 'rmtree')

        self._mox.StubOutWithMock(os, 'remove')

        self._mox.StubOutClassWithMocks(instance_metadata, 'InstanceMetadata')
        self._mox.StubOutWithMock(instance_metadata.InstanceMetadata,
                                  'metadata_for_config_drive')

        # Can't use StubOutClassWithMocks due to __exit__ and __enter__
        self._mox.StubOutWithMock(configdrive, 'ConfigDriveBuilder')
        self._mox.StubOutWithMock(configdrive.ConfigDriveBuilder, 'make_drive')

        self._mox.StubOutWithMock(utils, 'execute')

    def tearDown(self):
        self._mox.UnsetStubs()
        super(HyperVAPITestCase, self).tearDown()

    def test_get_available_resource(self):
        cpu_info = {'Architecture': 'fake',
                    'Name': 'fake',
                    'Manufacturer': 'ACME, Inc.',
                    'NumberOfCores': 2,
                    'NumberOfLogicalProcessors': 4}

        tot_mem_kb = 2000000L
        free_mem_kb = 1000000L

        tot_hdd_b = 4L * 1024 ** 3
        free_hdd_b = 3L * 1024 ** 3

        windows_version = '6.2.9200'

        hostutils.HostUtils.get_memory_info().AndReturn((tot_mem_kb,
                                                        free_mem_kb))

        m = hostutils.HostUtils.get_volume_info(mox.IsA(str))
        m.AndReturn((tot_hdd_b, free_hdd_b))

        hostutils.HostUtils.get_cpus_info().AndReturn([cpu_info])
        m = hostutils.HostUtils.is_cpu_feature_present(mox.IsA(int))
        m.MultipleTimes()

        m = hostutils.HostUtils.get_windows_version()
        m.AndReturn(windows_version)

        self._mox.ReplayAll()
        dic = self._conn.get_available_resource(None)
        self._mox.VerifyAll()

        self.assertEquals(dic['vcpus'], cpu_info['NumberOfLogicalProcessors'])
        self.assertEquals(dic['hypervisor_hostname'], platform.node())
        self.assertEquals(dic['memory_mb'], tot_mem_kb / 1024)
        self.assertEquals(dic['memory_mb_used'],
                          tot_mem_kb / 1024 - free_mem_kb / 1024)
        self.assertEquals(dic['local_gb'], tot_hdd_b / 1024 ** 3)
        self.assertEquals(dic['local_gb_used'],
                          tot_hdd_b / 1024 ** 3 - free_hdd_b / 1024 ** 3)
        self.assertEquals(dic['hypervisor_version'],
                          windows_version.replace('.', ''))

    def test_get_host_stats(self):
        tot_mem_kb = 2000000L
        free_mem_kb = 1000000L

        tot_hdd_b = 4L * 1024 ** 3
        free_hdd_b = 3L * 1024 ** 3

        hostutils.HostUtils.get_memory_info().AndReturn((tot_mem_kb,
                                                        free_mem_kb))

        m = hostutils.HostUtils.get_volume_info(mox.IsA(str))
        m.AndReturn((tot_hdd_b, free_hdd_b))

        self._mox.ReplayAll()
        dic = self._conn.get_host_stats(True)
        self._mox.VerifyAll()

        self.assertEquals(dic['disk_total'], tot_hdd_b / 1024 ** 3)
        self.assertEquals(dic['disk_available'], free_hdd_b / 1024 ** 3)

        self.assertEquals(dic['host_memory_total'], tot_mem_kb / 1024)
        self.assertEquals(dic['host_memory_free'], free_mem_kb / 1024)

        self.assertEquals(dic['disk_total'],
                          dic['disk_used'] + dic['disk_available'])
        self.assertEquals(dic['host_memory_total'],
                          dic['host_memory_overhead'] +
                          dic['host_memory_free'])

    def test_list_instances(self):
        fake_instances = ['fake1', 'fake2']
        vmutils.VMUtils.list_instances().AndReturn(fake_instances)

        self._mox.ReplayAll()
        instances = self._conn.list_instances()
        self._mox.VerifyAll()

        self.assertEquals(instances, fake_instances)

    def test_get_info(self):
        self._instance_data = self._get_instance_data()

        summary_info = {'NumberOfProcessors': 2,
                        'EnabledState': constants.HYPERV_VM_STATE_ENABLED,
                        'MemoryUsage': 1000,
                        'UpTime': 1}

        m = vmutils.VMUtils.vm_exists(mox.Func(self._check_instance_name))
        m.AndReturn(True)

        func = mox.Func(self._check_instance_name)
        m = vmutils.VMUtils.get_vm_summary_info(func)
        m.AndReturn(summary_info)

        self._mox.ReplayAll()
        info = self._conn.get_info(self._instance_data)
        self._mox.VerifyAll()

        self.assertEquals(info["state"], power_state.RUNNING)

    def test_spawn_cow_image(self):
        self._test_spawn_instance(True)

    def test_spawn_no_cow_image(self):
        self._test_spawn_instance(False)

    def _setup_spawn_config_drive_mocks(self, use_cdrom):
        im = instance_metadata.InstanceMetadata(mox.IgnoreArg(),
                                                content=mox.IsA(list),
                                                extra_md=mox.IsA(dict))

        cdb = self._mox.CreateMockAnything()
        m = configdrive.ConfigDriveBuilder(instance_md=mox.IgnoreArg())
        m.AndReturn(cdb)
        # __enter__ and __exit__ are required by "with"
        cdb.__enter__().AndReturn(cdb)
        cdb.make_drive(mox.IsA(str))
        cdb.__exit__(None, None, None).AndReturn(None)

        if not use_cdrom:
            utils.execute(CONF.qemu_img_cmd,
                          'convert',
                          '-f',
                          'raw',
                          '-O',
                          'vpc',
                          mox.IsA(str),
                          mox.IsA(str),
                          attempts=1)
            os.remove(mox.IsA(str))

        m = vmutils.VMUtils.attach_ide_drive(mox.IsA(str),
                                             mox.IsA(str),
                                             mox.IsA(int),
                                             mox.IsA(int),
                                             mox.IsA(str))
        m.WithSideEffects(self._add_ide_disk)

    def _test_spawn_config_drive(self, use_cdrom):
        self.flags(force_config_drive=True)
        self.flags(config_drive_cdrom=use_cdrom)
        self.flags(mkisofs_cmd='mkisofs.exe')

        self._setup_spawn_config_drive_mocks(use_cdrom)

        if use_cdrom:
            expected_ide_disks = 1
            expected_ide_dvds = 1
        else:
            expected_ide_disks = 2
            expected_ide_dvds = 0

        self._test_spawn_instance(expected_ide_disks=expected_ide_disks,
                                  expected_ide_dvds=expected_ide_dvds)

    def test_spawn_config_drive(self):
        self._test_spawn_config_drive(False)

    def test_spawn_config_drive_cdrom(self):
        self._test_spawn_config_drive(True)

    def test_spawn_no_config_drive(self):
        self.flags(force_config_drive=False)

        expected_ide_disks = 1
        expected_ide_dvds = 0

        self._test_spawn_instance(expected_ide_disks=expected_ide_disks,
                                  expected_ide_dvds=expected_ide_dvds)

    def test_spawn_nova_net_vif(self):
        self.flags(network_api_class='nova.network.api.API')
        # Reinstantiate driver, as the VIF plugin is loaded during __init__
        self._conn = driver_hyperv.HyperVDriver(None)

        def setup_vif_mocks():
            fake_vswitch_path = 'fake vswitch path'
            fake_vswitch_port = 'fake port'

            m = networkutils.NetworkUtils.get_external_vswitch(
                CONF.vswitch_name)
            m.AndReturn(fake_vswitch_path)

            m = networkutils.NetworkUtils.create_vswitch_port(
                fake_vswitch_path, mox.IsA(str))
            m.AndReturn(fake_vswitch_port)

            vmutils.VMUtils.set_nic_connection(mox.IsA(str), mox.IsA(str),
                                               fake_vswitch_port)

        self._test_spawn_instance(setup_vif_mocks_func=setup_vif_mocks)

    def test_spawn_nova_net_vif_no_vswitch_exception(self):
        self.flags(network_api_class='nova.network.api.API')
        # Reinstantiate driver, as the VIF plugin is loaded during __init__
        self._conn = driver_hyperv.HyperVDriver(None)

        def setup_vif_mocks():
            m = networkutils.NetworkUtils.get_external_vswitch(
                CONF.vswitch_name)
            m.AndRaise(vmutils.HyperVException(_('fake vswitch not found')))

        self.assertRaises(vmutils.HyperVException, self._test_spawn_instance,
                          setup_vif_mocks_func=setup_vif_mocks,
                          with_exception=True)

    def _check_instance_name(self, vm_name):
        return vm_name == self._instance_data['name']

    def _test_vm_state_change(self, action, from_state, to_state):
        self._instance_data = self._get_instance_data()

        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     to_state)

        self._mox.ReplayAll()
        action(self._instance_data)
        self._mox.VerifyAll()

    def test_pause(self):
        self._test_vm_state_change(self._conn.pause, None,
                                   constants.HYPERV_VM_STATE_PAUSED)

    def test_pause_already_paused(self):
        self._test_vm_state_change(self._conn.pause,
                                   constants.HYPERV_VM_STATE_PAUSED,
                                   constants.HYPERV_VM_STATE_PAUSED)

    def test_unpause(self):
        self._test_vm_state_change(self._conn.unpause,
                                   constants.HYPERV_VM_STATE_PAUSED,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_unpause_already_running(self):
        self._test_vm_state_change(self._conn.unpause, None,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_suspend(self):
        self._test_vm_state_change(self._conn.suspend, None,
                                   constants.HYPERV_VM_STATE_SUSPENDED)

    def test_suspend_already_suspended(self):
        self._test_vm_state_change(self._conn.suspend,
                                   constants.HYPERV_VM_STATE_SUSPENDED,
                                   constants.HYPERV_VM_STATE_SUSPENDED)

    def test_resume(self):
        self._test_vm_state_change(lambda i: self._conn.resume(i, None),
                                   constants.HYPERV_VM_STATE_SUSPENDED,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_resume_already_running(self):
        self._test_vm_state_change(lambda i: self._conn.resume(i, None), None,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_power_off(self):
        self._test_vm_state_change(self._conn.power_off, None,
                                   constants.HYPERV_VM_STATE_DISABLED)

    def test_power_off_already_powered_off(self):
        self._test_vm_state_change(self._conn.power_off,
                                   constants.HYPERV_VM_STATE_DISABLED,
                                   constants.HYPERV_VM_STATE_DISABLED)

    def test_power_on(self):
        self._test_vm_state_change(self._conn.power_on,
                                   constants.HYPERV_VM_STATE_DISABLED,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_power_on_already_running(self):
        self._test_vm_state_change(self._conn.power_on, None,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_reboot(self):

        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        self._instance_data = self._get_instance_data()

        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     constants.HYPERV_VM_STATE_REBOOT)

        self._mox.ReplayAll()
        self._conn.reboot(self._context, self._instance_data, network_info,
                          None)
        self._mox.VerifyAll()

    def test_destroy(self):
        self._instance_data = self._get_instance_data()

        m = vmutils.VMUtils.vm_exists(mox.Func(self._check_instance_name))
        m.AndReturn(True)

        m = vmutils.VMUtils.destroy_vm(mox.Func(self._check_instance_name),
                                       True)
        m.AndReturn([])

        self._mox.ReplayAll()
        self._conn.destroy(self._instance_data)
        self._mox.VerifyAll()

    def test_live_migration(self):
        self._test_live_migration(False)

    def test_live_migration_with_target_failure(self):
        self._test_live_migration(True)

    def _test_live_migration(self, test_failure):
        dest_server = 'fake_server'

        instance_data = self._get_instance_data()

        fake_post_method = self._mox.CreateMockAnything()
        if not test_failure:
            fake_post_method(self._context, instance_data, dest_server,
                             False)

        fake_recover_method = self._mox.CreateMockAnything()
        if test_failure:
            fake_recover_method(self._context, instance_data, dest_server,
                                False)

        m = livemigrationutils.LiveMigrationUtils.live_migrate_vm(
            instance_data['name'], dest_server)
        if test_failure:
            m.AndRaise(Exception('Simulated failure'))

        self._mox.ReplayAll()
        try:
            self._conn.live_migration(self._context, instance_data,
                                      dest_server, fake_post_method,
                                      fake_recover_method)
            exception_raised = False
        except Exception:
            exception_raised = True

        self.assertTrue(not test_failure ^ exception_raised)
        self._mox.VerifyAll()

    def test_pre_live_migration_cow_image(self):
        self._test_pre_live_migration(True)

    def test_pre_live_migration_no_cow_image(self):
        self._test_pre_live_migration(False)

    def _test_pre_live_migration(self, cow):
        self.flags(use_cow_images=cow)

        instance_data = self._get_instance_data()

        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)

        m = livemigrationutils.LiveMigrationUtils.check_live_migration_config()
        m.AndReturn(True)

        if cow:
            m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(mox.IsA(str),
                                                                  None)
            m.AndReturn([])

        self._mox.ReplayAll()
        self._conn.pre_live_migration(self._context, instance_data,
                                      None, network_info)
        self._mox.VerifyAll()

        if cow:
            self.assertTrue(self._fetched_image is not None)
        else:
            self.assertTrue(self._fetched_image is None)

    def test_snapshot_with_update_failure(self):
        (snapshot_name, func_call_matcher) = self._setup_snapshot_mocks()

        self._update_image_raise_exception = True

        self._mox.ReplayAll()
        self.assertRaises(vmutils.HyperVException, self._conn.snapshot,
                          self._context, self._instance_data, snapshot_name,
                          func_call_matcher.call)
        self._mox.VerifyAll()

        # Assert states changed in correct order
        self.assertIsNone(func_call_matcher.match())

    def _setup_snapshot_mocks(self):
        expected_calls = [
            {'args': (),
             'kwargs': {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs': {'task_state': task_states.IMAGE_UPLOADING,
                        'expected_state': task_states.IMAGE_PENDING_UPLOAD}}
        ]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        snapshot_name = 'test_snapshot_' + str(uuid.uuid4())

        fake_hv_snapshot_path = 'fake_snapshot_path'
        fake_parent_vhd_path = 'C:\\fake_vhd_path\\parent.vhd'

        self._instance_data = self._get_instance_data()

        func = mox.Func(self._check_instance_name)
        m = vmutils.VMUtils.take_vm_snapshot(func)
        m.AndReturn(fake_hv_snapshot_path)

        m = vhdutils.VHDUtils.get_vhd_parent_path(mox.IsA(str))
        m.AndReturn(fake_parent_vhd_path)

        self._fake_dest_disk_path = None

        def copy_dest_disk_path(src, dest):
            self._fake_dest_disk_path = dest

        m = shutil.copyfile(mox.IsA(str), mox.IsA(str))
        m.WithSideEffects(copy_dest_disk_path)

        self._fake_dest_base_disk_path = None

        def copy_dest_base_disk_path(src, dest):
            self._fake_dest_base_disk_path = dest

        m = shutil.copyfile(fake_parent_vhd_path, mox.IsA(str))
        m.WithSideEffects(copy_dest_base_disk_path)

        def check_dest_disk_path(path):
            return path == self._fake_dest_disk_path

        def check_dest_base_disk_path(path):
            return path == self._fake_dest_base_disk_path

        func1 = mox.Func(check_dest_disk_path)
        func2 = mox.Func(check_dest_base_disk_path)
        # Make sure that the hyper-v base and differential VHDs are merged
        vhdutils.VHDUtils.reconnect_parent_vhd(func1, func2)
        vhdutils.VHDUtils.merge_vhd(func1, func2)

        def check_snapshot_path(snapshot_path):
            return snapshot_path == fake_hv_snapshot_path

        # Make sure that the Hyper-V snapshot is removed
        func = mox.Func(check_snapshot_path)
        vmutils.VMUtils.remove_vm_snapshot(func)

        shutil.rmtree(mox.IsA(str))

        m = fake.PathUtils.open(func2, 'rb')
        m.AndReturn(io.BytesIO(b'fake content'))

        return (snapshot_name, func_call_matcher)

    def test_snapshot(self):
        (snapshot_name, func_call_matcher) = self._setup_snapshot_mocks()

        self._mox.ReplayAll()
        self._conn.snapshot(self._context, self._instance_data, snapshot_name,
                            func_call_matcher.call)
        self._mox.VerifyAll()

        self.assertTrue(self._image_metadata and
                        "disk_format" in self._image_metadata and
                        self._image_metadata["disk_format"] == "vhd")

        # Assert states changed in correct order
        self.assertIsNone(func_call_matcher.match())

    def _get_instance_data(self):
        instance_name = 'openstack_unit_test_vm_' + str(uuid.uuid4())
        return db_fakes.get_fake_instance_data(instance_name,
                                               self._project_id,
                                               self._user_id)

    def _spawn_instance(self, cow, block_device_info=None):
        self.flags(use_cow_images=cow)

        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)

        image = db_fakes.get_fake_image_data(self._project_id, self._user_id)

        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)

        self._conn.spawn(self._context, instance, image,
                         injected_files=[], admin_password=None,
                         network_info=network_info,
                         block_device_info=block_device_info)

    def _add_ide_disk(self, vm_name, path, ctrller_addr,
                      drive_addr, drive_type):
        if drive_type == constants.IDE_DISK:
            self._instance_ide_disks.append(path)
        elif drive_type == constants.IDE_DVD:
            self._instance_ide_dvds.append(path)

    def _add_volume_disk(self, vm_name, controller_path, address,
                         mounted_disk_path):
        self._instance_volume_disks.append(mounted_disk_path)

    def _setup_spawn_instance_mocks(self, cow, setup_vif_mocks_func=None,
                                    with_exception=False,
                                    block_device_info=None):
        self._test_vm_name = None

        def set_vm_name(vm_name):
            self._test_vm_name = vm_name

        def check_vm_name(vm_name):
            return vm_name == self._test_vm_name

        m = vmutils.VMUtils.vm_exists(mox.IsA(str))
        m.WithSideEffects(set_vm_name).AndReturn(False)

        if not block_device_info:
            m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(mox.IsA(str),
                                                                  None)
            m.AndReturn([])
        else:
            m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(
                mox.IsA(str), block_device_info)
            m.AndReturn(True)

        if cow:
            def check_path(parent_path):
                return parent_path == self._fetched_image

            vhdutils.VHDUtils.create_differencing_vhd(mox.IsA(str),
                                                      mox.Func(check_path))

        vmutils.VMUtils.create_vm(mox.Func(check_vm_name), mox.IsA(int),
                                  mox.IsA(int), mox.IsA(bool))

        if not block_device_info:
            m = vmutils.VMUtils.attach_ide_drive(mox.Func(check_vm_name),
                                                 mox.IsA(str),
                                                 mox.IsA(int),
                                                 mox.IsA(int),
                                                 mox.IsA(str))
            m.WithSideEffects(self._add_ide_disk).InAnyOrder()

        m = vmutils.VMUtils.create_scsi_controller(mox.Func(check_vm_name))
        m.InAnyOrder()

        vmutils.VMUtils.create_nic(mox.Func(check_vm_name), mox.IsA(str),
                                   mox.IsA(str)).InAnyOrder()

        if setup_vif_mocks_func:
            setup_vif_mocks_func()

        # TODO(alexpilotti) Based on where the exception is thrown
        # some of the above mock calls need to be skipped
        if with_exception:
            m = vmutils.VMUtils.vm_exists(mox.Func(check_vm_name))
            m.AndReturn(True)

            vmutils.VMUtils.destroy_vm(mox.Func(check_vm_name), True)
        else:
            vmutils.VMUtils.set_vm_state(mox.Func(check_vm_name),
                                         constants.HYPERV_VM_STATE_ENABLED)

    def _test_spawn_instance(self, cow=True,
                             expected_ide_disks=1,
                             expected_ide_dvds=0,
                             setup_vif_mocks_func=None,
                             with_exception=False):
        self._setup_spawn_instance_mocks(cow, setup_vif_mocks_func,
                                         with_exception)

        self._mox.ReplayAll()
        self._spawn_instance(cow, )
        self._mox.VerifyAll()

        self.assertEquals(len(self._instance_ide_disks), expected_ide_disks)
        self.assertEquals(len(self._instance_ide_dvds), expected_ide_dvds)

        if not cow:
            self.assertEquals(self._fetched_image, self._instance_ide_disks[0])

    def test_attach_volume(self):
        instance_data = self._get_instance_data()
        instance_name = instance_data['name']

        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']

        mount_point = '/dev/sdc'

        volumeutils.VolumeUtils.login_storage_target(target_lun,
                                                     target_iqn,
                                                     target_portal)

        fake_mounted_disk = "fake_mounted_disk"
        fake_device_number = 0
        fake_controller_path = 'fake_scsi_controller_path'
        fake_free_slot = 1

        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndReturn(fake_device_number)

        m = vmutils.VMUtils.get_mounted_disk_by_drive_number(
            fake_device_number)
        m.AndReturn(fake_mounted_disk)

        m = vmutils.VMUtils.get_vm_iscsi_controller(instance_name)
        m.AndReturn(fake_controller_path)

        m = vmutils.VMUtils.get_attached_disks_count(fake_controller_path)
        m.AndReturn(fake_free_slot)

        m = vmutils.VMUtils.attach_volume_to_controller(instance_name,
                                                        fake_controller_path,
                                                        fake_free_slot,
                                                        fake_mounted_disk)
        m.WithSideEffects(self._add_volume_disk)

        self._mox.ReplayAll()
        self._conn.attach_volume(connection_info, instance_data, mount_point)
        self._mox.VerifyAll()

        self.assertEquals(len(self._instance_volume_disks), 1)

    def test_detach_volume(self):
        instance_data = self._get_instance_data()
        instance_name = instance_data['name']

        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        mount_point = '/dev/sdc'

        fake_mounted_disk = "fake_mounted_disk"
        fake_device_number = 0
        fake_free_slot = 1
        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndReturn(fake_device_number)

        m = vmutils.VMUtils.get_mounted_disk_by_drive_number(
            fake_device_number)
        m.AndReturn(fake_mounted_disk)

        vmutils.VMUtils.detach_vm_disk(mox.IsA(str), fake_mounted_disk)

        volumeutils.VolumeUtils.logout_storage_target(mox.IsA(str))

        self._mox.ReplayAll()
        self._conn.detach_volume(connection_info, instance_data, mount_point)
        self._mox.VerifyAll()

    def test_boot_from_volume(self):
        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']

        block_device_info = db_fakes.get_fake_block_device_info(
            self._volume_target_portal, self._volume_id)

        fake_mounted_disk = "fake_mounted_disk"
        fake_device_number = 0
        fake_controller_path = 'fake_scsi_controller_path'

        volumeutils.VolumeUtils.login_storage_target(target_lun,
                                                     target_iqn,
                                                     target_portal)

        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndReturn(fake_device_number)

        m = vmutils.VMUtils.get_mounted_disk_by_drive_number(
            fake_device_number)
        m.AndReturn(fake_mounted_disk)

        m = vmutils.VMUtils.get_vm_ide_controller(mox.IsA(str), mox.IsA(int))
        m.AndReturn(fake_controller_path)

        m = vmutils.VMUtils.attach_volume_to_controller(mox.IsA(str),
                                                        fake_controller_path,
                                                        0,
                                                        fake_mounted_disk)
        m.WithSideEffects(self._add_volume_disk)

        self._setup_spawn_instance_mocks(cow=False,
                                         block_device_info=block_device_info)

        self._mox.ReplayAll()
        self._spawn_instance(False, block_device_info)
        self._mox.VerifyAll()

        self.assertEquals(len(self._instance_volume_disks), 1)
