########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
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
import tempfile

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.cfy_helper import CfyHelper
from cosmo_tester.framework.testenv import (initialize_without_bootstrap,
                                            clear_environment)


def setUp():
    initialize_without_bootstrap()


def tearDown():
    clear_environment()

MANAGER_BLUEPRINTS_REPO_URL = 'https://github.com/cloudify-cosmo/' \
                              'cloudify-manager-blueprints.git'
SOURCE_BRANCH = '3.4m5'


class ManagerUpgradeTest(TestCase):

    def test_manager_upgrade(self):
        import pudb; pu.db
        self.bootstrap_manager()
        self.deploy_hello_world()
        self.upgrade_manager()
        self.uninstall_deployment()
        self.teardown_manager()

    def bootstrap_manager(self):
        source_manager_repo_dir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        self.source_manager_repo_dir = clone(MANAGER_BLUEPRINTS_REPO_URL,
                                             source_manager_repo_dir,
                                             branch=SOURCE_BRANCH)

        blueprint_path = os.path.join(self.source_manager_repo_dir,
                                      'openstack-manager-blueprint.yaml')
        manager_name = self.test_id + '-manager-33'

        bootstrap_inputs = {
            'keystone_username': self.env.keystone_username,
            'keystone_password': self.env.keystone_password,
            'keystone_tenant_name': self.env.keystone_tenant_name,
            'keystone_url': self.env.keystone_url,
            'region': self.env.region,
            'flavor_id': self.env.medium_flavor_id,
            'image_id': self.env.centos_7_image_id,

            'ssh_user': self.env.centos_7_image_user,
            'external_network_name': self.env.external_network_name,
            'resources_prefix': self.env.resources_prefix,

            'manager_server_name': manager_name,

            # shared settings
            'manager_public_key_name': 'tt1-key',
            'agent_public_key_name': 'tt1-key',
            'ssh_key_filename': os.path.join(self.workdir, 'tt1.key'),
            'agent_private_key_path': os.path.join(self.workdir, 'tt2.key'),

            'management_network_name': 'tt1-network',
            'management_subnet_name': 'tt1-subnet',
            'management_router': 'tt1-router',

            'agents_user': '',

            # private settings
            'manager_security_group_name': manager_name + '-m-sg',
            'agents_security_group_name': manager_name + '-a-sg',
            'manager_port_name': manager_name + '-port',
            'management_subnet_dns_nameservers': ['8.8.8.8']
        }

        self.source_manager_dir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        self.source_cfy = CfyHelper(cfy_workdir=self.source_manager_dir)
        self.inputs_path = self.source_cfy._get_inputs_in_temp_file(
            bootstrap_inputs, self._testMethodName)
        self.source_cfy.bootstrap(blueprint_path, inputs_file=self.inputs_path)

    def deploy_hello_world(self):
        hello_repo_path = clone(
            'https://github.com/cloudify-cosmo/'
            'cloudify-hello-world-example.git',
            self.source_manager_dir
        )
        hello_blueprint_path = os.path.join(hello_repo_path, 'blueprint.yaml')
        self.source_cfy.upload_blueprint('hw1', hello_blueprint_path)
        self.source_cfy.create_deployment('hw1', 'hw1')
        self.source_cfy.executions.start(workflow='install',
                                         deployment_id='hw1').wait()

    def upgrade_manager(self):
        target_manager_repo_dir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        self.target_manager_repo_dir = clone(MANAGER_BLUEPRINTS_REPO_URL,
                                             target_manager_repo_dir)
        target_manager_blueprint = os.path.join(
            self.target_manager_repo_dir, 'openstack-manager-blueprint.yaml')
        self.source_cfy.manager_upgrade(
            blueprint_path=target_manager_blueprint,
            inputs_file=self.inputs_path)

    def uninstall_deployment(self):
        self.source_cfy.executions.start(workflow='uninstall',
                                         deployment_id='hw1').wait()

    def teardown_manager(self):
        self.source_cfy.teardown(ignore_deployments=True,
                                 force=True).wait()
