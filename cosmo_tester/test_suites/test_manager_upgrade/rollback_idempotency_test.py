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

import sh

from manager_upgrade_base import BaseManagerUpgradeTest


class ManagerRollbackIdempotencyTest(BaseManagerUpgradeTest):
    def _get_bootstrap_inputs(self):
        rv = (super(ManagerRollbackIdempotencyTest, self)
              ._get_bootstrap_inputs())
        rv['webui_source_url'] = 'http://repository.cloudifysource.org/org/cloudify3/3.4.0/m5-RELEASE/cloudify-ui-3.4.0-m5-b394.tgz'  # NOQA
        return rv

    def _get_fail_rollback_inputs(self):
        # The fake sanity app url will cause the upgrade to fail
        return {
            'private_ip': self.manager_private_ip,
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
            'sanity_app_source_url': 'fake_path.tar.gz'
        }

    def fail_rollback_manager(self):
        blueprint_path = self.get_upgrade_blueprint()
        rollback_inputs = self._get_fail_rollback_inputs()
        self.rollback_manager(blueprint=blueprint_path,
                              inputs=rollback_inputs)

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
            self.manager_cfy.set_maintenance_mode(False)
        else:
            self.fail(msg='Rollback expected to fail')

        self.rollback_manager()
        self.post_rollback_checks(preupgrade_deployment_id)
        self.teardown_manager()

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
