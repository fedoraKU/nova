# Copyright (c) 2012 Rackspace Hosting
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
"""
Tests For Cells RPCAPI
"""

from nova.cells import rpcapi as cells_rpcapi
from nova.openstack.common import cfg
from nova.openstack.common import rpc
from nova import test

CONF = cfg.CONF
CONF.import_opt('topic', 'nova.cells.opts', group='cells')


class CellsAPITestCase(test.TestCase):
    """Test case for cells.api interfaces."""

    def setUp(self):
        super(CellsAPITestCase, self).setUp()
        self.fake_topic = 'fake_topic'
        self.fake_context = 'fake_context'
        self.flags(topic=self.fake_topic, enable=True, group='cells')
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def _stub_rpc_method(self, rpc_method, result):
        call_info = {}

        def fake_rpc_method(ctxt, topic, msg, *args, **kwargs):
            call_info['context'] = ctxt
            call_info['topic'] = topic
            call_info['msg'] = msg
            return result

        self.stubs.Set(rpc, rpc_method, fake_rpc_method)
        return call_info

    def _check_result(self, call_info, method, args, version=None):
        if version is None:
            version = self.cells_rpcapi.BASE_RPC_API_VERSION
        self.assertEqual(self.fake_context, call_info['context'])
        self.assertEqual(self.fake_topic, call_info['topic'])
        self.assertEqual(method, call_info['msg']['method'])
        self.assertEqual(version, call_info['msg']['version'])
        self.assertEqual(args, call_info['msg']['args'])

    def test_cast_compute_api_method(self):
        fake_cell_name = 'fake_cell_name'
        fake_method = 'fake_method'
        fake_method_args = (1, 2)
        fake_method_kwargs = {'kwarg1': 10, 'kwarg2': 20}

        expected_method_info = {'method': fake_method,
                                'method_args': fake_method_args,
                                'method_kwargs': fake_method_kwargs}
        expected_args = {'method_info': expected_method_info,
                         'cell_name': fake_cell_name,
                         'call': False}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.cast_compute_api_method(self.fake_context,
                fake_cell_name, fake_method,
                *fake_method_args, **fake_method_kwargs)
        self._check_result(call_info, 'run_compute_api_method',
                expected_args)

    def test_call_compute_api_method(self):
        fake_cell_name = 'fake_cell_name'
        fake_method = 'fake_method'
        fake_method_args = (1, 2)
        fake_method_kwargs = {'kwarg1': 10, 'kwarg2': 20}
        fake_response = 'fake_response'

        expected_method_info = {'method': fake_method,
                                'method_args': fake_method_args,
                                'method_kwargs': fake_method_kwargs}
        expected_args = {'method_info': expected_method_info,
                         'cell_name': fake_cell_name,
                         'call': True}

        call_info = self._stub_rpc_method('call', fake_response)

        result = self.cells_rpcapi.call_compute_api_method(self.fake_context,
                fake_cell_name, fake_method,
                *fake_method_args, **fake_method_kwargs)
        self._check_result(call_info, 'run_compute_api_method',
                expected_args)
        self.assertEqual(fake_response, result)

    def test_schedule_run_instance(self):
        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.schedule_run_instance(
                self.fake_context, arg1=1, arg2=2, arg3=3)

        expected_args = {'host_sched_kwargs': {'arg1': 1,
                                               'arg2': 2,
                                               'arg3': 3}}
        self._check_result(call_info, 'schedule_run_instance',
                expected_args)

    def test_instance_update_at_top(self):
        fake_info_cache = {'id': 1,
                           'instance': 'fake_instance',
                           'other': 'moo'}
        fake_sys_metadata = [{'id': 1,
                              'key': 'key1',
                              'value': 'value1'},
                             {'id': 2,
                              'key': 'key2',
                              'value': 'value2'}]
        fake_instance = {'id': 2,
                         'security_groups': 'fake',
                         'instance_type': 'fake',
                         'volumes': 'fake',
                         'cell_name': 'fake',
                         'name': 'fake',
                         'metadata': 'fake',
                         'info_cache': fake_info_cache,
                         'system_metadata': fake_sys_metadata,
                         'other': 'meow'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_update_at_top(
                self.fake_context, fake_instance)

        expected_args = {'instance': fake_instance}
        self._check_result(call_info, 'instance_update_at_top',
                expected_args)

    def test_instance_destroy_at_top(self):
        fake_instance = {'uuid': 'fake-uuid'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_destroy_at_top(
                self.fake_context, fake_instance)

        expected_args = {'instance': fake_instance}
        self._check_result(call_info, 'instance_destroy_at_top',
                expected_args)

    def test_instance_delete_everywhere(self):
        fake_instance = {'uuid': 'fake-uuid'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_delete_everywhere(
                self.fake_context, fake_instance,
                'fake-type')

        expected_args = {'instance': fake_instance,
                         'delete_type': 'fake-type'}
        self._check_result(call_info, 'instance_delete_everywhere',
                expected_args)

    def test_instance_fault_create_at_top(self):
        fake_instance_fault = {'id': 2,
                               'other': 'meow'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.instance_fault_create_at_top(
                self.fake_context, fake_instance_fault)

        expected_args = {'instance_fault': fake_instance_fault}
        self._check_result(call_info, 'instance_fault_create_at_top',
                expected_args)

    def test_bw_usage_update_at_top(self):
        update_args = ('fake_uuid', 'fake_mac', 'fake_start_period',
                'fake_bw_in', 'fake_bw_out', 'fake_ctr_in',
                'fake_ctr_out')
        update_kwargs = {'last_refreshed': 'fake_refreshed'}

        call_info = self._stub_rpc_method('cast', None)

        self.cells_rpcapi.bw_usage_update_at_top(
                self.fake_context, *update_args, **update_kwargs)

        bw_update_info = {'uuid': 'fake_uuid',
                          'mac': 'fake_mac',
                          'start_period': 'fake_start_period',
                          'bw_in': 'fake_bw_in',
                          'bw_out': 'fake_bw_out',
                          'last_ctr_in': 'fake_ctr_in',
                          'last_ctr_out': 'fake_ctr_out',
                          'last_refreshed': 'fake_refreshed'}

        expected_args = {'bw_update_info': bw_update_info}
        self._check_result(call_info, 'bw_usage_update_at_top',
                expected_args)

    def test_get_cell_info_for_neighbors(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.get_cell_info_for_neighbors(
                self.fake_context)
        self._check_result(call_info, 'get_cell_info_for_neighbors', {},
                           version='1.1')
        self.assertEqual(result, 'fake_response')

    def test_sync_instances(self):
        call_info = self._stub_rpc_method('cast', None)
        self.cells_rpcapi.sync_instances(self.fake_context,
                project_id='fake_project', updated_since='fake_time',
                deleted=True)

        expected_args = {'project_id': 'fake_project',
                         'updated_since': 'fake_time',
                         'deleted': True}
        self._check_result(call_info, 'sync_instances', expected_args,
                           version='1.1')

    def test_service_get_all(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        fake_filters = {'key1': 'val1', 'key2': 'val2'}
        result = self.cells_rpcapi.service_get_all(self.fake_context,
                filters=fake_filters)

        expected_args = {'filters': fake_filters}
        self._check_result(call_info, 'service_get_all', expected_args,
                           version='1.2')
        self.assertEqual(result, 'fake_response')

    def test_service_get_by_compute_host(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.service_get_by_compute_host(
                self.fake_context, host_name='fake-host-name')
        expected_args = {'host_name': 'fake-host-name'}
        self._check_result(call_info, 'service_get_by_compute_host',
                           expected_args,
                           version='1.2')
        self.assertEqual(result, 'fake_response')

    def test_proxy_rpc_to_manager(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.proxy_rpc_to_manager(
                self.fake_context, rpc_message='fake-msg',
                topic='fake-topic', call=True, timeout=-1)
        expected_args = {'rpc_message': 'fake-msg',
                         'topic': 'fake-topic',
                         'call': True,
                         'timeout': -1}
        self._check_result(call_info, 'proxy_rpc_to_manager',
                           expected_args,
                           version='1.2')
        self.assertEqual(result, 'fake_response')

    def test_task_log_get_all(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.task_log_get_all(self.fake_context,
                task_name='fake_name',
                period_beginning='fake_begin',
                period_ending='fake_end',
                host='fake_host',
                state='fake_state')

        expected_args = {'task_name': 'fake_name',
                         'period_beginning': 'fake_begin',
                         'period_ending': 'fake_end',
                         'host': 'fake_host',
                         'state': 'fake_state'}
        self._check_result(call_info, 'task_log_get_all', expected_args,
                           version='1.3')
        self.assertEqual(result, 'fake_response')

    def test_compute_node_get_all(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.compute_node_get_all(self.fake_context,
                hypervisor_match='fake-match')

        expected_args = {'hypervisor_match': 'fake-match'}
        self._check_result(call_info, 'compute_node_get_all', expected_args,
                           version='1.4')
        self.assertEqual(result, 'fake_response')

    def test_compute_node_stats(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.compute_node_stats(self.fake_context)
        expected_args = {}
        self._check_result(call_info, 'compute_node_stats',
                           expected_args, version='1.4')
        self.assertEqual(result, 'fake_response')

    def test_compute_node_get(self):
        call_info = self._stub_rpc_method('call', 'fake_response')
        result = self.cells_rpcapi.compute_node_get(self.fake_context,
                'fake_compute_id')
        expected_args = {'compute_id': 'fake_compute_id'}
        self._check_result(call_info, 'compute_node_get',
                           expected_args, version='1.4')
        self.assertEqual(result, 'fake_response')
