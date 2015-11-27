########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import os
import time

from cloudify_rest_client.executions import Execution
from cosmo_tester.test_suites.test_blueprints.hello_world_bash_test import clone_hello_world
from cosmo_tester.framework.testenv import TestCase

class SnapshotsHelloWorldTest(TestCase):

    def _assert_manager_clean(self):
        state = self.get_manager_state()
        for v in state.itervalues():
            self.assertFalse(v)

    def _assert_manager_state(self, blueprints_ids, deployment_ids):
        state = self.get_manager_state()
        self.assertEquals(set(blueprints_ids), state['blueprints'].keys())
        self.assertEquals(set(deployments_ids), state['deployments'].keys())
    
    def setUp(self):
        super(SnapshotsHelloWorldTest, self).setUp()
        self._assert_manager_clean()
        self.repo_dir = clone_hello_world(self.workdir)
        self.blueprint_yaml = os.path.join(self.repo_dir, 'blueprint.yaml')
        self.counter = 0

    def tearDown(self):
        print 'tearing down'
        state = self.get_manager_state()
        for d in state['deployments']:
            print d
            self.client.deployments.delete(d)
        for b in state['blueprints']:
            print b
            self.client.blueprints.delete(b)
        super(SnapshotsHelloWorldTest, self).tearDown()

    def _deploy(self, deployment_id, blueprint_id):
        self.upload_blueprint(blueprint_id)
        inputs={
            'agent_user': 'ubuntu',
            'image': '9d25fe2d-cf31-4b05-8c58-f238ec78e633',
            'flavor': '103'
        }
        self.create_deployment(blueprint_id, deployment_id, inputs=inputs)
        self.wait_for_stop_dep_env_execution_to_end(deployment_id)
    
    def _uuid(self):
        self.counter += 1
        return '{0}_{1}'.format(self.test_id, self.counter)

    def test_simple(self):
        dep = self._uuid()
        self._deploy(dep, dep)
        self.client.snapshots.create(dep, include_metrics=False,
                                     include_credentials=False)
        self.client.deployments.delete(dep)
        self.client.blueprints.delete(dep)
        self.wait_until_all_deployment_executions_end(dep)
        self._assert_manager_clean()
        self.client.snapshots.restore(dep)
        self._assert_manager_state(blueprinds_ids={dep},
                                   deployment_ids={dep})
        self.client.snapshots.delete(dep)
        self.client.deployments.delete(dep)
        self.client.blueprints.delete(dep)

        

#    def test_openstack_helloworld(self):
#        return
##       self._assert_manager_clean()
##        self.blueprint_id = self.test_id
##        self.deployment_id = self.test_id
##        self.repo_dir = clone_hello_world(self.workdir)
##        self.blueprint_yaml = os.path.join(self.repo_dir, 'blueprint.yaml')
#        print str(inputs)
##        self.upload_deploy_and_execute_install(inputs=inputs)
#        self.client.deployments.delete(self.deployment_id)
#        self.client.blueprints.delete(self.deployment_id)

    def on_nodecellar_installed(self):
        snapshot_id = 'nodecellar_sn-{0}'.format(time.strftime("%Y%m%d-%H%M"))

        self.cfy.create_deployment(self.blueprint_id, self.additional_dep_id,
                                   inputs=self.get_inputs())
        self.wait_until_all_deployment_executions_end(self.additional_dep_id)

        self.wait_for_stop_dep_env_execution_to_end(self.deployment_id)
        self.client.snapshots.create(snapshot_id, True, True)

        waited = 0
        time_between_checks = 5
        snapshot = self.client.snapshots.get(snapshot_id)
        while snapshot.status == 'creating':
            time.sleep(time_between_checks)
            waited += time_between_checks
            self.assertTrue(
                waited <= 3 * 60,
                'Waiting too long for create snapshot to finish'
            )
            snapshot = self.client.snapshots.get(snapshot_id)
        self.assertEqual('created', snapshot.status)

        self.cfy.delete_deployment(self.deployment_id, ignore_live_nodes=True)
        self.cfy.delete_deployment(self.additional_dep_id)
        self.client.blueprints.delete(self.blueprint_id)
        self.logger.info('Deleting all plugins from manager...')
        plugins = self.client.plugins.list()
        for plugin in plugins:
            self.logger.info(
                'Deleting plugin: {0} - {1}'.format(plugin.id,
                                                    plugin.package_name))
            self.client.plugins.delete(plugin.id)

        waited = 0
        execution = self.client.snapshots.restore(snapshot_id)
        while execution.status not in Execution.END_STATES:
            waited += time_between_checks
            time.sleep(time_between_checks)
            self.assertTrue(
                waited <= 20 * 60,
                'Waiting too long for restore snapshot to finish'
            )
            execution = self.client.executions.get(execution.id)
        if execution.status == Execution.FAILED:
            self.logger.error('Execution error: {0}'.format(execution.error))
        self.assertEqual(Execution.TERMINATED, execution.status)

        self.logger.info('Snapshot restored, deleting snapshot..')
        self.client.snapshots.delete(snapshot_id)
        # Throws if not found
        self.client.deployments.delete(self.additional_dep_id)
