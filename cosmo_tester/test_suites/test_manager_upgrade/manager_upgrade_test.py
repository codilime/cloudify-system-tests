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
import time
import shutil
import socket
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

MANAGER_BLUEPRINTS_REPO_URL = 'https://github.com/codilime/' \
                              'cloudify-manager-blueprints.git'
SOURCE_BRANCH = 'restservice-test-endpoint'
UPGRADE_BRANCH = 'restservice-test-endpoint'


class ManagerUpgradeTest(TestCase):

    def test_manager_upgrade(self):
        import pudb; pu.db  # NOQA
        self.prepare_manager()
        # self.deploy_hello_world()
        self.upgrade_manager()
        # self.uninstall_deployment()
        self.rollback_manager()
        self.teardown_manager()

    def prepare_manager(self):
        self.manager_inputs = self._get_bootstrap_inputs()
        if 'foo_manager' in self.env.handler_configuration:
            self.source_manager_dir = tempfile.mkdtemp(
                prefix='cloudify-testenv-')
            self.source_cfy = CfyHelper(cfy_workdir=self.source_manager_dir)
            self.source_cfy.use(
                management_ip=self.env.handler_configuration['foo_manager'])
            self.upgrade_manager_ip = \
                self.env.handler_configuration['foo_manager']
        else:
            self.bootstrap_manager()

    def _get_bootstrap_inputs(self):
        if 'foo_manager' in self.env.handler_configuration:
            ssh_key_filename = self.env.handler_configuration['foo_key']
        else:
            ssh_key_filename = os.path.join(self.workdir, 'tt1.key')

        agent_key_path = os.path.join(self.workdir, 'tt2.key')
        manager_name = self.test_id + '-manager-33'

        return {
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
            'manager_public_key_name': 'tt1-manager-key',
            'agent_public_key_name': 'tt1-agents-key',
            'ssh_key_filename': ssh_key_filename,
            'agent_private_key_path': agent_key_path,

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

    def bootstrap_manager(self):
        source_manager_repo_dir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        # self.addCleanup(shutil.rmtree, source_manager_repo_dir)
        self.source_manager_repo_dir = clone(MANAGER_BLUEPRINTS_REPO_URL,
                                             source_manager_repo_dir,
                                             branch=SOURCE_BRANCH)
        blueprint_path = os.path.join(self.source_manager_repo_dir,
                                      'openstack-manager-blueprint.yaml')

        # self.addCleanup(self.env.handler.remove_keypair, 'tt1-key')
        # self.addCleanup(self.env.handler.remove_keypair, 'tt2-key')
        # self.addCleanup(os.unlink, self.bootstrap_inputs['ssh_key_filename'])
        # self.addCleanup(os.unlink,
        #            self.bootstrap_inputs['agent_private_key_path'])

        self.source_manager_dir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        # self.addCleanup(shutil.rmtree, self.source_manager_dir)
        self.source_cfy = CfyHelper(cfy_workdir=self.source_manager_dir)
        self.inputs_path = self.source_cfy._get_inputs_in_temp_file(
            self.manager_inputs, self._testMethodName)
        self.source_cfy.bootstrap(blueprint_path, inputs_file=self.inputs_path)
        self.upgrade_manager_ip = self.source_cfy.get_management_ip()
        self.source_cfy.use(management_ip=self.upgrade_manager_ip)  # ???

        group_name = self.manager_inputs['manager_security_group_name']
        for port in [5672, 8086, 9200]:
            self._allow_port_on_security_group(group_name, port)

    def deploy_hello_world(self):
        hello_repo_path = clone(
            'https://github.com/cloudify-cosmo/'
            'cloudify-hello-world-example.git',
            self.source_manager_dir
        )
        hello_blueprint_path = os.path.join(hello_repo_path, 'blueprint.yaml')
        self.source_cfy.upload_blueprint('hw1', hello_blueprint_path)
        self.addCleanup(self.source_cfy.delete_blueprint, 'hw1')
        inputs = {
            'agent_user': self.env.cloudify_agent_user,
            'image': self.env.ubuntu_trusty_image_name,
            'flavor': self.env.flavor_name
        }
        self.source_cfy.create_deployment('hw1', 'hw1', inputs=inputs)
        self.addCleanup(self.source_cfy.delete_deployment, 'hw1')
        self.source_cfy.execute_install(deployment_id='hw1')

    def upgrade_manager(self):
        target_manager_repo_dir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        self.addCleanup(shutil.rmtree, target_manager_repo_dir)
        self.target_manager_repo_dir = clone(MANAGER_BLUEPRINTS_REPO_URL,
                                             target_manager_repo_dir,
                                             branch=UPGRADE_BRANCH)
        target_manager_blueprint = os.path.join(
            self.target_manager_repo_dir, 'simple-manager-blueprint.yaml')

        upgrade_inputs = {
            'private_ip': '127.0.0.1',
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
            'elasticsearch_endpoint_port': 9200

        }
        upgrade_inputs_file = self.source_cfy._get_inputs_in_temp_file(
            upgrade_inputs, self._testMethodName)

        self.source_cfy.set_maintenance_mode(True)
        self.source_cfy.upgrade_manager(
            blueprint_path=target_manager_blueprint,
            inputs_file=upgrade_inputs_file)
        # self.source_cfy.set_maintenance_mode(False)

    def rollback_manager(self):
        rollback_repo_dir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        rollback_repo_dir = clone(MANAGER_BLUEPRINTS_REPO_URL,
                                  rollback_repo_dir,
                                  branch=UPGRADE_BRANCH)
        target_manager_blueprint = os.path.join(
            rollback_repo_dir, 'simple-manager-blueprint.yaml')

        rollback_inputs = {
            'private_ip': '127.0.0.1',
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
        }
        rollback_inputs_file = self.source_cfy._get_inputs_in_temp_file(
            rollback_inputs, self._testMethodName)
        self.source_cfy.set_maintenance_mode(True)
        self.source_cfy.rollback_manager(
            blueprint_path=target_manager_blueprint,
            inputs_file=rollback_inputs_file)

    def uninstall_deployment(self):
        self.source_cfy.executions.start(workflow='uninstall',
                                         deployment_id='hw1').wait()

    def teardown_manager(self):
        self.source_cfy.teardown(ignore_deployments=True).wait()

    def _allow_port_on_security_group(self, group_name, port, proto='tcp'):
        nova, neutron, cinder = self.env.handler.openstack_clients()
        group_id = nova.security_groups.find(name=group_name).id

        nova.security_group_rules.create(
            parent_group_id=group_id,
            from_port=port,
            to_port=port,
            ip_protocol=proto,
        )
        # Don't continue until the rule is actually active
        for attempt in range(1, 4):
            try:
                socket.create_connection((
                    self.upgrade_manager_ip,
                    port
                ))
            except socket.error:
                # Port is not yet active
                if attempt == 3:
                    # Maximum attempts reached, something is probably wrong
                    raise
                else:
                    # Try again soon
                    time.sleep(3)
            else:
                break
