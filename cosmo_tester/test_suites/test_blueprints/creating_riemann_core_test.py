########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
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


from cosmo_tester.framework.testenv import TestCase


class CreatingRiemannCoreTest(TestCase):

    def _get_riemann_configs_dir(self):
        # this probably shouldn't be hardcoded: the path is defined in the
        # manager blueprint: components/mgmtworker/config/cloudify-mgmtworker
        # the RIEMANN_CONFIGS_DIR environment variable
        return '/opt/riemann'

    def _run(self, blueprint_filename):
        blueprint_dir = self.copy_blueprint('riemann-core')
        riemann_configs_dir = self._get_riemann_configs_dir()

        with self.manager_env_fabric() as fab:
            out = fab.run('ls {0}'.format(riemann_configs_dir))
        self.assertNotIn(self.test_id, out)

        inputs = {
            'agent_user': self.env.cloudify_agent_user,
            'image': self.env.ubuntu_precise_image_name,
            'flavor': self.env.flavor_name
        }
        self.blueprint_yaml = blueprint_dir / blueprint_filename
        self.upload_deploy_and_execute_install(
            fetch_state=False,
            inputs=inputs)

        with self.manager_env_fabric() as fab:
            return fab.run('ls {0}'.format(riemann_configs_dir))

    def test_without_policies(self):
        out = self._run('without-policies.yaml')
        self.assertNotIn(self.test_id, out)

    def test_with_policies(self):
        out = self._run('with-policies.yaml')
        self.assertIn(self.test_id, out)
