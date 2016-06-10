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
    @contextmanager
    def break_rollback(self):
        fetched_properties = StringIO()
        fetched_resources = StringIO()
        # TODO I think we also need rollback_node_properties
        properties_path = \
            '/opt/cloudify/sanity/node_properties/properties.json'
        resources_path = '/opt/cloudify/sanity/resources/__resources.json'

        with self._manager_fabric_env() as fabric:
            fabric.get(properties_path, fetched_properties)
            properties = json.loads(fetched_properties.getvalue())

            fabric.get(resources_path, fetched_resources)
            resources = json.loads(fetched_resources.getvalue())

            properties['sanity_app_source_url'] = 'fake.tar.gz'

            resources['fake.tar.gz'] = 'fake.tar.gz'

            fabric.put(StringIO(json.dumps(properties)), properties_path)
            fabric.put(StringIO(json.dumps(resources)), resources_path)

            try:
                yield
            finally:
                fabric.put(fetched_properties, properties_path)
                fabric.put(fetched_resources, resources_path)

    def fail_rollback_manager(self):
        with self.break_rollback():
            self.rollback_manager()

    def test_rollback_failure(self):
        """Upgrade, run rollback, fail in the middle, run rollback again
        and verify rollback complete.
        """
        import pudb; pu.db  # NOQA
        self.prepare_manager()
        preupgrade_deployment_id = self.deploy_hello_world('pre-')

        self.upgrade_manager()
        self.post_upgrade_checks(preupgrade_deployment_id)

        try:
            self.fail_rollback_manager()
        except sh.ErrorReturnCode:
            pass
        else:
            self.fail(msg='Rollback expected to fail')

        self.rollback_manager()
        self.post_rollback_checks(preupgrade_deployment_id)
        self.teardown_manager()

    def test_rollback_twice(self):
        """Upgrade, run rollback, finish, run rollback again and see that
        nothing changed.
        """
        self.prepare_manager()
        preupgrade_deployment_id = self.deploy_hello_world('pre-')

        self.upgrade_manager()
        self.post_upgrade_checks(preupgrade_deployment_id)

        self.rollback_manager()
        self.post_rollback_checks(preupgrade_deployment_id)
        self.rollback_manager()
        self.post_rollback_checks(preupgrade_deployment_id)

        self.teardown_manager()
