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

from contextlib import contextmanager
from cStringIO import StringIO
import json
import sh

from manager_upgrade_base import BaseManagerUpgradeTest


class ManagerRollbackIdempotencyTest(BaseManagerUpgradeTest):
    def _get_fail_rollback_inputs(self):
        # The fake sanity app url will cause the upgrade to fail
        return {
            'private_ip': self.manager_private_ip,
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
            'sanity_app_source_url': 'fake_path.tar.gz'
        }

    @contextmanager
    def break_rollback(self):
        fetched_properties = StringIO()
        fetched_resources = StringIO()

        with self._manager_fabric_env() as fabric:
            fabric.get('/opt/cloudify/sanity/node_properties/properties.json',
                       fetched_properties)
            properties = json.load(fetched_properties)
            fabric.get('/opt/cloudify/sanity/resources/__resources.json',
                       fetched_resources)
            resources = json.load(fetched_resources)
            modified_properties = {'sanity_app_source_url': 'fake.tar.gz'}
            modified_resources = {'fake.tar.gz': 'fake.tar.gz'}

            fabric.put(
                '/opt/cloudify/sanity/node_properties/properties.json',
                StringIO(json.dumps(modified_properties)))
            fabric.put(
                '/opt/cloudify/sanity/resources/__resources.json',
                StringIO(json.dumps(modified_resources)))
            yield
            fabric.put(
                '/opt/cloudify/sanity/node_properties/properties.json',
                StringIO(json.dumps(properties)))
            fabric.put(
                '/opt/cloudify/sanity/resources/__resources.json',
                StringIO(json.dumps(resources)))

    def fail_rollback_manager(self):
        with self.break_rollback():
            self.rollback_manager()

    def test_rollback_failure(self):
        """Upgrade, run rollback, fail in the middle, run rollback again
        and verify rollback complete.
        """
        import pudb; pu.db  # NOQA
        # self.prepare_manager()
        # preupgrade_deployment_id = self.deploy_hello_world('pre-')

        # self.upgrade_manager()
        # self.post_upgrade_checks(preupgrade_deployment_id)
        self.manager_inputs = self._get_bootstrap_inputs()
        self.manager_private_ip = '172.16.0.3'
        self.upgrade_manager_ip = '185.98.149.79'

        try:
            self.fail_rollback_manager()
        except sh.ErrorReturnCode:
            self.manager_cfy.set_maintenance_mode(False)
        else:
            self.fail(msg='Rollback expected to fail')

        # self.rollback_manager()
        # self.post_rollback_checks(preupgrade_deployment_id)
        # self.teardown_manager()

    def test_rollback_twice(self):
        """Upgrade, run rollback, finish, run rollback again and see that
        nothing changed.
        """
        import pudb; pu.db  # NOQA
        self.prepare_manager()
        preupgrade_deployment_id = self.deploy_hello_world('pre-')

        self.upgrade_manager()
        self.post_upgrade_checks(preupgrade_deployment_id)

        self.rollback_manager()
        self.post_rollback_checks(preupgrade_deployment_id)
        self.rollback_manager()
        self.post_rollback_checks(preupgrade_deployment_id)

        self.teardown_manager()
