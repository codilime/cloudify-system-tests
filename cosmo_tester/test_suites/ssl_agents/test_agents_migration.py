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

from contextlib import contextmanager
import os
import ssl
import time
import tempfile
# import threading

import celery
import fabric
import sh

from cloudify_cli.utils import load_cloudify_working_dir_settings
from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.cfy_helper import CfyHelper
from cosmo_tester.framework.util import sh_bake, YamlPatcher
from cosmo_tester.framework.git_helper import clone
from cloudify.workflows import local
from cloudify_rest_client import CloudifyClient


CLI_REPO = 'https://github.com/cloudify-cosmo/cloudify-cli'
BLUEPRINTS_REPO = ('https://github.com/cloudify-cosmo/'
                   'cloudify-manager-blueprints')
HELLOWORLD_REPO = ('https://github.com/cloudify-cosmo/'
                   'cloudify-hello-world-example')


class TestAgentsMigration(TestCase):

    def _manager_host(self, nova, label):
        env = self._bootstrap_local_env(self.cli_dirs[label])
        server = self._find_server(env.storage)
        manager_id = server['runtime_properties']['external_id']
        return nova.servers.find(id=manager_id)

    def _management_network(self, label):
        env = self._bootstrap_local_env(self.cli_dirs[label])
        network = self._find_mgmt_network(env.storage)
        return network['runtime_properties']['external_id']

    def _find_mgmt_network(self, storage):
        for node in storage.get_nodes():
            if node['type'] == 'cloudify.openstack.nodes.Network':
                if node['name'] == 'management_network':
                    break
        else:
            raise RuntimeError('No mgmt network in {0}'.format(storage))
        return self._get_node_instance(storage, node['id'])

    def _find_server(self, storage):
        for node in storage.get_nodes():
            if node['type'] == 'cloudify.openstack.nodes.Server':
                break
        else:
            raise RuntimeError('No server in {0}'.format(storage))
        return self._get_node_instance(storage, node['id'])

    def _get_node_instance(self, storage, node_id):
        instances = storage.get_node_instances()
        for instance in instances:
            if instance['node_id'] == node_id:
                return instance
        raise RuntimeError('No node instance {0}'.format(node_id))

    def _get_keys(self, prefix):
        keys_dir = tempfile.mkdtemp(dir=self.workdir)
        ssh_key_filename = os.path.join(keys_dir, 'manager.key')
        self.addCleanup(self.env.handler.remove_keypair,
                        prefix + '-manager-key')

        agent_key_path = os.path.join(keys_dir, 'agents.key')
        self.addCleanup(self.env.handler.remove_keypair,
                        prefix + '-agents-key')
        return ssh_key_filename, agent_key_path

    def _get_bootstrap_inputs(self, prefix):
        prefix = self.test_id + prefix

        ssh_key_filename, agent_key_path = self._get_keys(prefix)

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
            'resources_prefix': 'test-upgrade-',

            'manager_server_name': prefix + '-manager',

            # shared settings
            'manager_public_key_name': prefix + '-manager-key',
            'agent_public_key_name': prefix + '-agents-key',
            'ssh_key_filename': ssh_key_filename,
            'agent_private_key_path': agent_key_path,

            'management_network_name': prefix + '-network',
            'management_subnet_name': prefix + '-subnet',
            'management_router': prefix + '-router',

            'agents_user': '',

            # private settings
            'manager_security_group_name': prefix + '-m-sg',
            'agents_security_group_name': prefix + '-a-sg',
            'manager_port_name': prefix + '-port',

        }

    def _get_331_bootstrap_inputs(self):
        return {
            'rabbitmq_ssl_enabled': True,
            'rabbitmq_cert_public': """-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAItHr2leftE1MA0GCSqGSIb3DQEBBQUAMEUxCzAJBgNV
BAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBX
aWRnaXRzIFB0eSBMdGQwHhcNMTYwNzA2MDg1MDAzWhcNMTcwNzA2MDg1MDAzWjBF
MQswCQYDVQQGEwJBVTETMBEGA1UECAwKU29tZS1TdGF0ZTEhMB8GA1UECgwYSW50
ZXJuZXQgV2lkZ2l0cyBQdHkgTHRkMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIB
CgKCAQEArqdDAU74465+DgmzTPI9dcFVQ/u0o5mzUyWaoq4H4lwB2/VOtgBWCUmk
jC9P0k2Ovaf54fJeWzeFmPsiNUPSsNsbu9dQt+QraSpGCwrghtvDa+0dfZWDPHqH
QHSSZ2qbYkKY/nyS1GPbLsZk4MFNepMFBkFkhqDaSlsMjXZ/AG+el6+lIxIKLg/7
qF0EObxyH7x0SXTYr5jev/+jZioSuFrYx96YzkEYP35YrWd88/0DhrQXw/tHRzml
NzvY3CUVpJjBFOJDbUP0Tlvc1d4lAugaU5r+hBaTSsSSWqVAEgNHE3k7da+2pcdt
nSTcZHk0bs1s3aJsyc6Ql7q56f/KWwIDAQABo1AwTjAdBgNVHQ4EFgQUzJ36DQJC
zaojH0TSe1krcHbMwdQwHwYDVR0jBBgwFoAUzJ36DQJCzaojH0TSe1krcHbMwdQw
DAYDVR0TBAUwAwEB/zANBgkqhkiG9w0BAQUFAAOCAQEAGh3VzYB2Dk2GtgM8LqKb
d4oU4ZFTLxtupGEUISFG5gs1k5VkqZPbTkrLYSED9Hq3NfCR72E+iInGcBS2kbVr
w35k7fJI86bZctzSE7oFy1U1v3HE6irL74WE63S/HwP6Z3yZK7Z44fs/x8CP8GFK
U+VZiU8Yt35uEXqnm9hR3tQTahcZbCLC+iO5G5Niwo3HHRKuoVJPow/EAJN2cxbZ
6NI98uipAI+jWgVM9H+g9IDjv7bWP/UkIPcbTy27htfmA2BGIP1uVMLfkcDqYFu+
TSGdDWg1m7T72lp8CIfTBQ0ZC21KOmBkXWFZ9OML/68OPG8SaYMpNFz/xmsTrUED
hQ==
-----END CERTIFICATE-----
""",
            'rabbitmq_cert_private': """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCup0MBTvjjrn4O
CbNM8j11wVVD+7SjmbNTJZqirgfiXAHb9U62AFYJSaSML0/STY69p/nh8l5bN4WY
+yI1Q9Kw2xu711C35CtpKkYLCuCG28Nr7R19lYM8eodAdJJnaptiQpj+fJLUY9su
xmTgwU16kwUGQWSGoNpKWwyNdn8Ab56Xr6UjEgouD/uoXQQ5vHIfvHRJdNivmN6/
/6NmKhK4WtjH3pjOQRg/flitZ3zz/QOGtBfD+0dHOaU3O9jcJRWkmMEU4kNtQ/RO
W9zV3iUC6BpTmv6EFpNKxJJapUASA0cTeTt1r7alx22dJNxkeTRuzWzdomzJzpCX
urnp/8pbAgMBAAECggEBAJEptlh1EgrzchQq3ds7j/e6rCroH1jHHDQkkiVabnUm
sejnN/evydLIYbqebELIcbaS0e+JagF44VKokOMirxCN3LxAlvdw7t/m4fa1oK6W
JBQlLZi+1yhCUv4wparNAb8myVDjq4paQMfc3+Wq5MHXRprPaUU4lpasnH9LmP17
aO9urtLN0XF6Xp/PchTSB0p3UjhCG6oWuQIQoEUgX7F6WYJnLsGqiFOaT3z0/Tn+
uJBdBLeoWlosp7OyS09RXNhhyjlyMiKxsC3eAlgx3Fj2ce8MBkr4bStRnVd/FypW
wYgBq3ChcgIgJoJh2/A8nwAHSExnPDoK6xr2/LX+xxECgYEA2mwsGXbFXZKMWZ6s
ilFxzwiipERrhjksF1otJqVa911s1SyKrHMwP5iq08kPH14uUArOsr+LTDdPxIC8
yqqH+9Uep+ol51Fq8Z3SCuWd1ZF9/lIIGVdU10/XTs3Bv/Pdd8x8Tm+yGGz3kkra
5kx6SaR4q7uB6hyq+XhYAVEj6fMCgYEAzLNlD9PjHeJV6JvB2NOzkV17PDIdZ43c
WbiAfT47nZEu9cDIFN0S1so4xSLjHr1/PpnP2vMb72BIsOtjJfeKWRppVNpGLChj
MDt1FD8L1cgOKfxPbvUW7kEsyr4nc3WWPgv6HQLY27rDkY+jQBTYJKLyI1huGa/1
TA8LTqo0D/kCgYB7Huqk1+xc2JTAl87OkSZD+6wiSGcL3AJcj3pQBHmIYmNMrrTk
jHGwB5CTnQwnNGGKwOzOmWYd6jfOnnrNCt9oNzP2lugSwjQ0Si/x8IjNsBuDVh42
mqG6VMkbJKSIXSCDvQJ8/D05w4KyNfu6QXXVOR7EPwf2PX6q7Qk+hMxnvQKBgHyw
Ca9Kcd2SMKIvvjRFP+wb9SUFocOiNcaxDBM+BTJFbUVk2Htc7kzHgS0TwyTGaOvI
5UOJMkrta1nZB9vonO0JmX+GNZhQQZrvnLFodd0Srw4EEp6TzBP0v0P/8Cf0SEAj
K4bgZRfy+41+4QH3sHEgkD3Xb7lV5SUfRNP1+SCBAoGAHLRD+asCnPDp445jmMcY
ikkJusNZ1T0fGDrGD4jpaFPRorzZcPGpTLeSM4S9qx+zD8vVe1kQY4Gi8nwdVJyT
y5TwfTTtYOqvOiGQQrWDLw3z8pb/wqLxUZzbPyx+DyeJeEMrP2/mWQskST6HB0BI
8f7TIRcYjmjJYBoqBpkejdY=
-----END PRIVATE KEY-----
""",
        }

    def _get_tls_bootstrap_inputs(self):
        return {
            # 'install_python_compilers': True,
            'security_enabled': True,
            'ssl_enabled': True,
            'admin_username': 'admin',
            'admin_password': 'admin',

            'agent_rest_username': 'cfy_agent',
            'agent_rest_password': 'cfy_agent',

            'agent_verify_rest_certificate': True,

            'management_subnet_dns_nameservers': ['8.8.8.8', '8.8.4.4'],
            'rabbitmq_ssl_enabled': True,
            'rabbitmq_cert_public': """-----BEGIN CERTIFICATE-----
MIICATCCAWoCCQDvZEFbnvoOCTANBgkqhkiG9w0BAQsFADBFMQswCQYDVQQGEwJB
VTETMBEGA1UECAwKU29tZS1TdGF0ZTEhMB8GA1UECgwYSW50ZXJuZXQgV2lkZ2l0
cyBQdHkgTHRkMB4XDTE2MDYyODA3MDczMFoXDTE3MDYyODA3MDczMFowRTELMAkG
A1UEBhMCQVUxEzARBgNVBAgMClNvbWUtU3RhdGUxITAfBgNVBAoMGEludGVybmV0
IFdpZGdpdHMgUHR5IEx0ZDCBnzANBgkqhkiG9w0BAQEFAAOBjQAwgYkCgYEAwbTo
FZvNMKHq+VOID2TcyTJtWvRVYnh85bUrWbqRGmjhf0TqPodGdxujziMfMjZMoTNt
KPQDfOgwidhvjuoowXeC69NgUOEMHQ0XtRh0JIlozLeLauE8C6GcuLUVym0DCYUl
728G9JD8YyC+dUU7iDlUbcsv+kDvezEbukeTAasCAwEAATANBgkqhkiG9w0BAQsF
AAOBgQBK1k5iyz1cOCwBQMittecHWUA1Jr6sAB8mDjZfyhIhF/GS6VfXT25hKDy9
aKadfsDV1T60104Su2xhQhx/e2O4ZnHyLMqCAAxoaThq/AoSHlzHeOwvlpFGNdoe
sR3z7LPr3ZlUHQIfeNYMnO2d+DQpkteAv8vjdE2DSqI+SsM5mQ==
-----END CERTIFICATE-----
""",
            'rabbitmq_cert_private': """-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQDBtOgVm80woer5U4gPZNzJMm1a9FVieHzltStZupEaaOF/ROo+
h0Z3G6POIx8yNkyhM20o9AN86DCJ2G+O6ijBd4Lr02BQ4QwdDRe1GHQkiWjMt4tq
4TwLoZy4tRXKbQMJhSXvbwb0kPxjIL51RTuIOVRtyy/6QO97MRu6R5MBqwIDAQAB
AoGATSJtvJUTC0ee2vPRXVfrt06WTz62dYTHL22KOqvZNiwHh3d407dobuuZue8w
b/1BXHuu/zzT2rxW/70pBz7lRRt7vV/F3hjFxnhrC6ZCKsjG+uczHp9/l1rU+gIT
47LRmYkfqoRhHoJzGbATxZJS7/WiMNSCNl2SMNxeZXDeJjECQQDo4oHnITwo7GFt
zl2Fch8meCWNrj6gTct/cUY/g4vMxYKXNP23vuvnJ5yFErP2bDXb9Zjq1C8rek4c
l4necsgZAkEA1O7mw5feVq1U2vt+JvofucbMejG2nwWWwezGgcuD2FQV6A2wkfqt
QJudOsmH0qo4Hlo06jd9RstZS89wqSCgYwJBAIAsml6BdkD3yK/M0sAtjWN44QJX
knRcHNJpn8Y5OmpbkoJyUeodlGzG6mh7YL0R1ZrYU297lPKTAAbQiLr75ZECQAUy
z+92hbcYBDpUaYAKGzwt3lAdZpf7SvLxFOeWUGG3q9E+hFEMDa7GHdCRmv9JqJUV
HrWZJTXVQRjYt6dpZIECQFZsUvtTUYzFOEUsRFtB549CWWFjfbXaYx7CPbXCFYQk
DN51RPTgxDhccizv6poBRmTto2+yt+azNWzNEQloFxQ=
-----END RSA PRIVATE KEY-----
""",
            'rest_host_external_endpoint_type': 'public_ip',
            'rest_host_internal_endpoint_type': 'private_ip',
            'rest_service_source_url': 'https://github.com/cloudify-cosmo/cloudify-manager/archive/master.tar.gz',  # NOQA
            'plugins_common_source_url': 'https://github.com/cloudify-cosmo/cloudify-plugins-common/archive/master.tar.gz',  # NOQA
            'script_plugin_source_url': 'https://github.com/cloudify-cosmo/cloudify-script-plugin/archive/master.tar.gz',  # NOQA
            'agent_source_url': 'https://github.com/cloudify-cosmo/cloudify-agent/archive/master.tar.gz',  # NOQA
            'cli_source_url': 'https://github.com/cloudify-cosmo/cloudify-cli/archive/master.tar.gz',  # NOQA
            'rest_client_source_url': 'https://github.com/cloudify-cosmo/cloudify-rest-client/archive/master.tar.gz',  # NOQA
            'dsl_parser_source_url': 'https://github.com/cloudify-cosmo/cloudify-dsl-parser/archive/master.tar.gz',  # NOQA
            'agent_package_urls': {
                'centos_7x_agent': 'https://www.dropbox.com/s/he8kpkiw6ikfpgh/centos-Core-agent.tar.gz'  # NOQA
            }
        }

    def _bootstrap_local_env(self, workdir):
        storage = local.FileStorage(
            os.path.join(workdir, '.cloudify', 'bootstrap'))
        return local.load_env('manager', storage=storage)

    def _prepare_manager(self, label, tag, bootstrap_inputs, patch_dns=True,
                         blueprints_repo=BLUEPRINTS_REPO):
        venv = self.venvs[label]
        blueprints_dir = tempfile.mkdtemp(dir=self.workdir)
        blueprints = clone(blueprints_repo, blueprints_dir, tag)
        blueprint_path = os.path.join(
            blueprints / 'openstack-manager-blueprint.yaml')
        secgroup_cfg = [{
            'port_range_min': 5671,
            'port_range_max': 5671,
            'remote_ip_prefix': '0.0.0.0/0'
        }]
        secgroup_cfg_path = 'node_templates.management_security_group' \
                            '.properties.rules'
        with YamlPatcher(blueprint_path) as patch:
            patch.append_value(secgroup_cfg_path, secgroup_cfg)

        if patch_dns:
            with YamlPatcher(blueprint_path) as patch:
                patch.merge_obj(
                    'node_templates.management_subnet.properties.subnet',
                    {'dns_nameservers': ['8.8.4.4', '8.8.8.8']}
                )

        inputs_file = self.cfy[label]._get_inputs_in_temp_file(
            bootstrap_inputs, self._testMethodName + label)
        fd, bootstrap_script = tempfile.mkstemp(dir=self.workdir)
        os.close(fd)

        with open(bootstrap_script, 'w') as f:
            f.write("""
        source {venv}/bin/activate
        cd {workdir}
        cfy init
        CLOUDIFY_USERNAME=cfy_agent \
        CLOUDIFY_PASSWORD=cfy_agent \
        cfy bootstrap -p {blueprint_path} -i {inputs_file} \
        --install-plugins --keep-up-on-failure
            """.format(venv=venv, blueprint_path=blueprint_path,
                       inputs_file=inputs_file,
                       workdir=self.cli_dirs[label]))

        sh_bake(sh.bash, prefix=label + ' ')(bootstrap_script).wait()

    def _prepare_cli_331sec(self, label='sec331'):
        tag = 'tags/3.3.1-sec1'

        cli_repo_dir = tempfile.mkdtemp(dir=self.workdir)
        cli_repo = clone(CLI_REPO, cli_repo_dir, tag)

        venv = tempfile.mkdtemp(dir=self.workdir)
        self.cli_dirs[label] = tempfile.mkdtemp(dir=self.workdir)
        sh.virtualenv(venv).wait()
        pip = sh.Command(os.path.join(venv, 'bin/pip'))
        pip.install(e=cli_repo).wait()
        cfy = sh.Command(os.path.join(venv, 'bin/cfy'))
        self.cfy[label] = CfyHelper(cfy_workdir=self.cli_dirs[label],
                                    executable=cfy)
        self.venvs[label] = venv

    def _prepare_cli_tls(self, label='tls'):
        venv = tempfile.mkdtemp(dir=self.workdir)
        sh.virtualenv(venv).wait()
        pip = sh_bake(sh.Command(os.path.join(venv, 'bin/pip')))
        for repo in [
            'https://github.com/cloudify-cosmo/cloudify-dsl-parser',
            'https://github.com/cloudify-cosmo/cloudify-rest-client',
            'https://github.com/cloudify-cosmo/cloudify-plugins-common',
            'https://github.com/cloudify-cosmo/cloudify-cli',
        ]:
            repo_dir = tempfile.mkdtemp(dir=self.workdir)
            repo = clone(repo, repo_dir, 'master')
            pip.install(e=repo).wait()

        for package in ['pyopenssl', 'ndg-httpsclient', 'pyasn1']:
            pip.install(package).wait()

        cfy = sh.Command(os.path.join(venv, 'bin/cfy'))
        self.cli_dirs[label] = tempfile.mkdtemp(dir=self.workdir)
        self.cfy[label] = CfyHelper(cfy_workdir=self.cli_dirs[label],
                                    executable=cfy)
        self.venvs[label] = venv

    def _prepare_manager_331sec(self, label='sec331'):
        self._prepare_cli_331sec(label)
        bootstrap_inputs = self._get_bootstrap_inputs(label)
        bootstrap_inputs.update(self._get_331_bootstrap_inputs())
        self.bootstrap_inputs[label] = bootstrap_inputs
        self._prepare_manager(label, 'tags/3.3.1-sec1', bootstrap_inputs)

        helloworld_repo = clone(HELLOWORLD_REPO, self.workdir, 'tags/3.3.1')
        cfy_331 = self.cfy[label]
        cfy_331.upload_blueprint('hw', helloworld_repo / 'blueprint.yaml')
        cfy_331.create_deployment('hw', 'hw_dep', inputs={
            'image': '74ff4015-aee1-4e02-aaa8-1c77b2650394',
            'flavor': '196235bc-7ca5-4085-ac81-7e0242bda3f9',
            'agent_user': 'centos'
        })
        cfy_331.execute_install('hw_dep')
        time.sleep(30)
        cfy_331.create_snapshot('snap1')
        self.snapshot_path = os.path.join(self.workdir, 'snap1.snap')
        cfy_331.download_snapshot(
            'snap1', self.snapshot_path)

    def _prepare_manager_tls(self, label='tls'):
        self._prepare_cli_tls(label)
        bootstrap_inputs = self._get_bootstrap_inputs(label)
        bootstrap_inputs.update(self._get_tls_bootstrap_inputs())
        self.bootstrap_inputs[label] = bootstrap_inputs
        self._prepare_manager(label, 'master', bootstrap_inputs, False)

    def _fixup_networks(self, from_label, to_label):
        nova, neutron, _ = self.env.handler.openstack_clients()
        old_rest = CloudifyClient(
            host=self._get_manager_ip(from_label),
            api_version='v2')

        vm_instance = old_rest.node_instances.list(node_id='vm')[0]
        agent_runtime_props = vm_instance['runtime_properties']
        agent_host_id = agent_runtime_props['external_id']
        agent_host = nova.servers.find(id=agent_host_id)

        new_manager = self._manager_host(nova, to_label)
        old_network = self._management_network(from_label)
        new_network = self._management_network(to_label)

        old_port = neutron.create_port({'port': {'network_id': old_network}})
        new_manager.interface_attach(old_port['port']['id'], None, None)

        new_port = neutron.create_port({'port': {'network_id': new_network}})
        agent_host.interface_attach(new_port['port']['id'], None, None)

        with self._manager_fabric_env(to_label) as f:
            f.sudo('ifconfig eth1 {0} up'.format(
                old_port['port']['fixed_ips'][0]['ip_address']))

        with self._manager_fabric_env(from_label) as f:
            f.sudo('ssh-keyscan -t rsa {0} > ~/.ssh/known_hosts'.format(
                agent_runtime_props['cloudify_agent']['ip']))
            f.sudo('ssh {0}@{1} -i /root/.ssh/agent_key.pem'
                   ' "sudo /usr/sbin/ifconfig eth1 {2} up"'.format(
                       agent_runtime_props['cloudify_agent']['user'],
                       agent_runtime_props['cloudify_agent']['ip'],
                       new_port['port']['fixed_ips'][0]['ip_address']))

        agent_celery_name = 'celery@{0}'.format(vm_instance['id'])
        with self._manager_celery_client(from_label) as client:
            inspect = client.control.inspect()
            active = inspect.active()
            self.assertIn(agent_celery_name, active)

        with self._manager_celery_client(to_label) as client:
            inspect = client.control.inspect()
            active = inspect.active()
            self.assertNotIn(agent_celery_name, active)

    def _get_manager_ip(self, label):
        cfy = self.cfy[label]
        try:
            return cfy.get_management_ip()
        except AttributeError:
            with cfy.workdir:
                settings = load_cloudify_working_dir_settings()
                return settings._management_ip

    @contextmanager
    def _manager_celery_client(self, label):
        bootstrap_inputs = self.bootstrap_inputs[label]
        client = celery.Celery()
        broker_url = 'amqp://cloudify:c10udify@{0}:5671//'.format(
            self._get_manager_ip(label))
        fd, cert_path = tempfile.mkstemp(dir=self.workdir)
        os.close(fd)

        with open(cert_path, 'w') as f:
            f.write(bootstrap_inputs['rabbitmq_cert_public'])

        broker_ssl = {
            'ca_certs': cert_path,
            'cert_reqs': ssl.CERT_REQUIRED
        }
        client.conf.update(
            BROKER_URL=broker_url,
            CELERY_RESULT_BACKEND=broker_url,
            BROKER_USE_SSL=broker_ssl
        )
        try:
            yield client
        finally:
            os.remove(cert_path)

    @contextmanager
    def _manager_fabric_env(self, label):
        bootstrap_inputs = self.bootstrap_inputs[label]
        settings = {
            'host_string': self._get_manager_ip(label),
            'user': bootstrap_inputs['ssh_user'],
            'key_filename': bootstrap_inputs['ssh_key_filename'],
            'keepalive': 30
        }
        with fabric.context_managers.settings(**settings):
            yield fabric.api

    def test_migration(self):
        self.cli_dirs = {}
        self.cfy = {}
        self.venvs = {}
        self.bootstrap_inputs = {}
        import pudb; pu.db  # NOQA
        self._prepare_manager_331sec()
        self._prepare_manager_tls()
        self._fixup_networks('sec331', 'tls')

        # self.cfy_tls.install_agents()
        # XXX check celery inspect
