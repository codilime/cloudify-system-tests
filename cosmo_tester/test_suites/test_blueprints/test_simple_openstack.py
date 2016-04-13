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


from contextlib import contextmanager
import os
import tempfile

from cosmo_tester.framework.testenv import TestCase
from cloudify.workflows import local
from cloudify_cli import constants as cli_constants
import fabric.context_managers
import fabric.api
import fabric.state
from fabric.exceptions import NetworkError


class TestSimpleOpenstack(TestCase):
    def setUp(self):
        super(TestSimpleOpenstack, self).setUp()
        self.openstack_inputs = {
            'os_username': self.env.keystone_username,
            'os_password': self.env.keystone_password,
            'os_tenant_name': self.env.keystone_tenant_name,
            'os_region': self.env.region,
            'os_auth_url': self.env.keystone_url,
        }
        self.vm_inputs = {
            'image_id': self.env.centos_7_image_name,
            'flavor': self.env.medium_flavor_id,
            'prefix': self.env.resources_prefix,
            'management_network_name': 'pup-test-management-network'
        }
        self.blueprint_dir = self.copy_blueprint('simple-openstack')
        self._prereqs = None

    def _get_prereqs(self):
        """Prepare the external resources these tests use.

        The VM blueprints in these tests use an external keypair, floating ip
        and a security group (so that they can use the exact same ip).
        This method creates these resources.
        """
        if self._prereqs is not None:
            return self._prereqs

        blueprint_yaml = self.blueprint_dir / 'simple.yaml'
        inputs = {
            'prefix': self.env.resources_prefix,
            'floating_network_name': 'external',
            'key_pair_path': '{0}/{1}-keypair.pem'.format(
                self.workdir, self.env.resources_prefix)
        }
        inputs.update(self.openstack_inputs)

        local_env = local.init_env(
            blueprint_yaml,
            inputs=inputs,
            name=self._testMethodName,
            ignored_modules=cli_constants.IGNORED_LOCAL_WORKFLOW_MODULES)

        self.addCleanup(self.uninstall, local_env)
        local_env.execute('install', task_retries=5)

        self._prereqs = local_env.outputs()
        return self._prereqs

    def _spawn_vm(self, blueprint='vm1.yaml'):
        vm1_yaml = self.blueprint_dir / 'vm1.yaml'

        secgroup_id = self._get_prereqs()['secgroup_id']
        ip_id = self._get_prereqs()['ip_id']

        vm1_inputs = {
            'floating_ip_id': ip_id,
            'secgroup_id': secgroup_id,
            'key_pair_id': self._get_prereqs()['key_pair_id'],
            'key_pair_path': self._get_prereqs()['key_pair_path'],
        }
        vm1_inputs.update(self.vm_inputs)
        vm1_inputs.update(self.openstack_inputs)
        vm1_env = local.init_env(
            vm1_yaml,
            inputs=vm1_inputs,
            name=self._testMethodName,
            ignored_modules=cli_constants.IGNORED_LOCAL_WORKFLOW_MODULES)
        self.addCleanup(self.uninstall, vm1_env)
        vm1_env.execute('install', task_retries=5)
        return vm1_env

    @contextmanager
    def vm_fabric_env(self, system_known_hosts=None):
        with fabric.context_managers.settings(
                user='centos',
                host_string=self._get_prereqs()['ip_to_use'],
                key_filename=self._get_prereqs()['key_pair_path'],
                system_known_hosts=system_known_hosts):
            yield fabric.api

    def _prepare_known_hosts(self):
        """Spawn a VM, add its host key to a known_hosts file, return its path.

        After spawning the vm, this function connects to it like you normally
        would using ssh, stores its host key in a file, and returns the
        filename
        """
        vm1_env = self._spawn_vm()
        fd, filename = tempfile.mkstemp()
        self.addCleanup(os.unlink, filename)
        os.close(fd)

        with self.vm_fabric_env():
            fabric.api.run('ls')

            conns = fabric.state.connections
            host_string = fabric.state.env.host_string
            conn = conns[host_string]
            conn._host_keys.save(filename)

        vm1_env.execute('uninstall', task_retries=40,
                        task_retry_interval=30)
        return filename

    def test_breaks_fabric_with_prepared_host_keys(self):
        """Fabric throws an error for a changed known host key.

        This test spawns a VM and stores its host key in a known_hosts file.
        Then it spawns another vm, assigns the same IP to it, and tries to
        connect to it using that known_hosts file, and raw fabric
        (ie. not the fabric plugin).

        Fabric should detect that the host key for this IP has changed,
        and should stop the connection.
        """
        known_hosts_filename = self._prepare_known_hosts()
        self._spawn_vm()

        try:
            with self.vm_fabric_env(system_known_hosts=known_hosts_filename):
                print fabric.api.run('ls')
        except NetworkError as e:
            self.assertIn('Host key', e.message)
        else:
            self.fail()

    def test_just_using_fabric_doesnt_break(self):
        """Fabric wont fail connecting to the same ip with different host keys.

        When using fabric (ie. not the fabric plugin) to connect to a VM,
        and then to another VM under the same IP, but with a different host
        key, fabric won't consider that a bad host key violation, and won't
        throw an exception.
        This is because fabric doesn't save the host key in a known_hosts file
        by itself.
        """
        env1 = self._spawn_vm()
        with self.vm_fabric_env():
            fabric.api.run('ls')
        self.uninstall(env1)

        env2 = self._spawn_vm()
        with self.vm_fabric_env():
            fabric.api.run('ls')
        self.uninstall(env2)

    def test_using_the_fabric_plugin_doesnt_break(self):
        """Same as the "just using fabric" test but using the plugin."""
        env1 = self._spawn_vm()
        with self.vm_fabric_env():
            fabric.api.run('ls')
        self.uninstall(env1)

        env2 = self._spawn_vm()
        with self.vm_fabric_env():
            fabric_yaml = self.blueprint_dir / 'with_plugin.yaml'
            fabric_inputs = {
                'commands': ['ls'],
                'fabric_env': fabric.state.env,
                'ip': ''
            }
            fabric_env = local.init_env(
                fabric_yaml,
                inputs=fabric_inputs,
                name=self._testMethodName,
                ignored_modules=cli_constants.IGNORED_LOCAL_WORKFLOW_MODULES)
            fabric_env.execute('execute_operation',
                               parameters={'operation': 'run_commands'})
        self.uninstall(env2)

    def uninstall(self, env):
        env.execute('uninstall',
                    task_retries=40,
                    task_retry_interval=30)
