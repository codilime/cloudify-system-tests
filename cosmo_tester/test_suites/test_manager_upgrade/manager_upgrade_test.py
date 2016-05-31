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
from functools import total_ordering
import json
import os
import shutil
import re
import tempfile
import time
import urllib2

import fabric
from influxdb import InfluxDBClient

from cloudify.workflows import local

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.cfy_helper import CfyHelper

from cosmo_tester.framework.util import create_rest_client, YamlPatcher


BOOTSTRAP_REPO_URL = 'https://github.com/cloudify-cosmo/'\
                     'cloudify-manager-blueprints.git'
BOOTSTRAP_BRANCH = 'master'

UPGRADE_REPO_URL = 'https://github.com/cloudify-cosmo/'\
                   'cloudify-manager-blueprints.git'
UPGRADE_BRANCH = 'master'


# TODO maybe use setuptools instead?
@total_ordering
class VersionNumber(object):
    def __init__(self, version, **kwargs):
        self._version = version
        self._parts = [self._parse_part(part)
                       for part in self._split_version(version)]

    def _split_version(self, version):
        return re.split(r'[.-]', version)

    def _parse_part(self, part):
        try:
            return int(part)
        except ValueError:
            return part

    def __repr__(self):
        return '<{0} {1}>'.format(self.__class__.__name__,
                                  self._version)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self._parts == other._parts
        else:
            return self._parts == other

    def __lt__(self, other):
        if isinstance(other, self.__class__):
            return self._parts < other._parts
        else:
            return self._parts < other

KNOWN_RPM_PACKAGES = {
    'cloudify-amqp-influx-',
    'cloudify-rest-service-',
    'cloudify-management-worker-'
}


def _get_rpm_versions(output):
    """Parse out version numbers from a `rpm -qa` call.

    Only look at packages in KNOWN_RPM_PACKAGES.
    """
    versions = {}
    for line in output.split('\n'):
        line = line.strip()
        for package in KNOWN_RPM_PACKAGES:
            if line.startswith(package):
                line = line.replace(package, '')
                version, sep, arch = line.split('_')
                versions[package] = VersionNumber(version)
                break
    return versions


class ManagerUpgradeTest(TestCase):

    def test_manager_upgrade(self):
        """Bootstrap a manager, upgrade it, rollback it, examine the results.

        To test the manager in-place upgrade procedure:
            - bootstrap a manager (this is part of the system under test,
              does destructive changes to the manager, and need a known manager
              version: so, can't use the testenv manager)
            - deploy the hello world app
            - upgrade the manager, changing some inputs (eg. the port that
              Elasticsearch uses)
            - check that everything still works (the previous deployment still
              reports metrics; we can install another deployment)
            - rollback the manager
            - post-rollback checks: the changed inputs are now the original
              values again, the installed app still reports metrics
        """
        self.prepare_manager()

        self.preupgrade_deployment_id = self.deploy_hello_world('pre-')

        self.upgrade_manager()
        self.post_upgrade_checks()

        self.rollback_manager()
        self.post_rollback_checks()

        self.teardown_manager()

    @contextmanager
    def _manager_fabric_env(self):
        inputs = self.manager_inputs
        with fabric.context_managers.settings(
                host_string=self.upgrade_manager_ip,
                user=inputs['ssh_user'],
                key_filename=inputs['ssh_key_filename']):
            yield fabric.api

    def _cloudify_rpm_versions(self):
        with self._manager_fabric_env() as fabric:
            rpms = fabric.sudo('rpm -qa | grep cloudify')
        return _get_rpm_versions(rpms)

    def prepare_manager(self):
        # note that we're using a separate manager checkout, so we need to
        # create our own utils like cfy and the rest client, rather than use
        # the testenv ones
        self.cfy_workdir = tempfile.mkdtemp(prefix='manager-upgrade-')
        self.addCleanup(shutil.rmtree, self.cfy_workdir)
        self.manager_cfy = CfyHelper(cfy_workdir=self.cfy_workdir)

        self.manager_inputs = self._get_bootstrap_inputs()

        blueprint_path = self.get_bootstrap_blueprint()
        self.bootstrap_manager(blueprint_path)

        self.rest_client = create_rest_client(self.upgrade_manager_ip)

        self.bootstrap_rpm_versions = self._cloudify_rpm_versions()
        self.bootstrap_manager_version = VersionNumber(
            **self.rest_client.manager.get_version())

    def _get_bootstrap_inputs(self):
        prefix = self.test_id

        ssh_key_filename = os.path.join(self.workdir, 'manager.key')
        self.addCleanup(os.unlink, ssh_key_filename)
        self.addCleanup(self.env.handler.remove_keypair,
                        prefix + '-manager-key')

        agent_key_path = os.path.join(self.workdir, 'agents.key')
        self.addCleanup(os.unlink, agent_key_path)
        self.addCleanup(self.env.handler.remove_keypair,
                        prefix + '-agents-key')

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
            'management_subnet_dns_nameservers': ['8.8.8.8', '8.8.4.4']
        }

    def get_bootstrap_blueprint(self):
        manager_repo_dir = tempfile.mkdtemp(prefix='manager-upgrade-')
        self.addCleanup(shutil.rmtree, manager_repo_dir)
        manager_repo = clone(BOOTSTRAP_REPO_URL,
                             manager_repo_dir,
                             branch=BOOTSTRAP_BRANCH)
        yaml_path = manager_repo / 'openstack-manager-blueprint.yaml'

        # allow the ports that we're going to connect to from the tests,
        # when doing checks
        for port in [8086, 9200, 9900]:
            secgroup_cfg = [{
                'port_range_min': port,
                'port_range_max': port,
                'remote_ip_prefix': '0.0.0.0/0'
            }]
            secgroup_cfg_path = 'node_templates.management_security_group'\
                '.properties.rules'
            with YamlPatcher(yaml_path) as patch:
                patch.append_value(secgroup_cfg_path, secgroup_cfg)

        return yaml_path

    def _load_private_ip_from_env(self, workdir):
        storage = local.FileStorage(
            os.path.join(workdir, '.cloudify', 'bootstrap'))
        env = local.load_env('manager', storage=storage)
        return env.outputs()['private_ip']

    def bootstrap_manager(self, blueprint_path):
        inputs_path = self.manager_cfy._get_inputs_in_temp_file(
            self.manager_inputs, self._testMethodName)

        self.manager_cfy.bootstrap(blueprint_path,
                                   inputs_file=inputs_path)

        self.upgrade_manager_ip = self.manager_cfy.get_management_ip()
        self.manager_private_ip = self._load_private_ip_from_env(
            self.cfy_workdir)

        # TODO: why is this needed?
        self.manager_cfy.use(management_ip=self.upgrade_manager_ip)

    def deploy_hello_world(self, prefix=''):
        """Install the hello world app."""
        blueprint_id = prefix + self.test_id
        deployment_id = prefix + self.test_id
        hello_repo_dir = tempfile.mkdtemp(prefix='manager-upgrade-')
        hello_repo_path = clone(
            'https://github.com/cloudify-cosmo/'
            'cloudify-hello-world-example.git',
            hello_repo_dir
        )
        self.addCleanup(shutil.rmtree, hello_repo_dir)
        hello_blueprint_path = hello_repo_path / 'blueprint.yaml'
        self.manager_cfy.upload_blueprint(blueprint_id, hello_blueprint_path)

        inputs = {
            'agent_user': self.env.ubuntu_image_user,
            'image': self.env.ubuntu_trusty_image_name,
            'flavor': self.env.flavor_name
        }
        self.manager_cfy.create_deployment(blueprint_id, deployment_id,
                                           inputs=inputs)

        self.manager_cfy.execute_install(deployment_id=deployment_id)
        return deployment_id

    def get_upgrade_blueprint(self):
        repo_dir = tempfile.mkdtemp(prefix='manager-upgrade-')
        self.addCleanup(shutil.rmtree, repo_dir)
        upgrade_blueprint_path = clone(UPGRADE_REPO_URL,
                                       repo_dir,
                                       branch=UPGRADE_BRANCH)

        return upgrade_blueprint_path / 'simple-manager-blueprint.yaml'

    def upgrade_manager(self):
        blueprint_path = self.get_upgrade_blueprint()

        # we're changing one of the ES inputs - make sure we also re-install ES
        with YamlPatcher(blueprint_path) as patch:
            patch.set_value(
                ('node_templates.elasticsearch.properties'
                 '.use_existing_on_upgrade'),
                False)

        upgrade_inputs = {
            'private_ip': self.manager_private_ip,
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
            'elasticsearch_endpoint_port': 9900

        }
        upgrade_inputs_file = self.manager_cfy._get_inputs_in_temp_file(
            upgrade_inputs, self._testMethodName)

        with self.manager_cfy.maintenance_mode():
            self.manager_cfy.upgrade_manager(
                blueprint_path=blueprint_path,
                inputs_file=upgrade_inputs_file)

    def post_upgrade_checks(self):
        """To check if the upgrade succeeded:
            - fire a request to the REST service
            - check that elasticsearch is listening on the changed port
            - check that the pre-existing deployment still reports to influxdb
            - install a new deployment, check that it reports to influxdb,
              and uninstall it: to check that the manager still allows
              creating, installing and uninstalling deployments correctly
        """
        upgrade_manager_version = VersionNumber(
            **self.rest_client.manager.get_version())
        upgrade_rpm_versions = self._cloudify_rpm_versions()
        self.assertGreaterEqual(upgrade_manager_version,
                                self.bootstrap_manager_version)
        for package, original_version in self.bootstrap_rpm_versions.items():
            upgraded_version = upgrade_rpm_versions[package]
            self.assertGreaterEqual(upgraded_version, original_version)

        self.rest_client.blueprints.list()
        self.check_elasticsearch(self.upgrade_manager_ip, 9900)
        self.check_influx(self.preupgrade_deployment_id)

        postupgrade_deployment_id = self.deploy_hello_world('post-')
        self.check_influx(postupgrade_deployment_id)
        self.uninstall_deployment(postupgrade_deployment_id)

    def check_influx(self, deployment_id):
        """Check that the deployment_id continues to report metrics.

        Look at the last 5 seconds worth of metrics. To avoid race conditions
        (running this check before the deployment even had a chance to report
        any metrics), first wait 5 seconds to allow some metrics to be
        gathered.
        """
        # TODO influx config should be pulled from props?
        time.sleep(5)
        influx_client = InfluxDBClient(self.upgrade_manager_ip, 8086,
                                       'root', 'root', 'cloudify')
        try:
            result = influx_client.query('select * from /^{0}\./i '
                                         'where time > now() - 5s'
                                         .format(deployment_id))
        except NameError as e:
            self.fail('monitoring events list for deployment with ID {0} were'
                      ' not found on influxDB. error is: {1}'
                      .format(deployment_id, e))

        self.assertTrue(len(result) > 0)

    def check_elasticsearch(self, host, port):
        """Check that elasticsearch is listening on the given host:port.

        This is used for checking if the ES port changed correctly during
        the upgrade.
        """
        try:
            response = urllib2.urlopen('http://{0}:{1}'.format(
                self.upgrade_manager_ip, port))
            response = json.load(response)
            if response['status'] != 200:
                raise ValueError('Incorrect status {0}'.format(
                    response['status']))
        except (ValueError, urllib2.URLError):
            self.fail('elasticsearch isnt listening on the changed port')

    def uninstall_deployment(self, deployment_id):
        self.manager_cfy.execute_uninstall(deployment_id)

    def rollback_manager(self):
        rollback_manager_version = VersionNumber(
            **self.rest_client.manager.get_version())
        rollback_rpm_versions = self._cloudify_rpm_versions()

        for package, original_version in self.bootstrap_rpm_versions.items():
            upgraded_version = rollback_rpm_versions[package]
            self.assertEqual(upgraded_version, original_version)

        self.assertEqual(rollback_manager_version,
                         self.bootstrap_manager_version)

        blueprint_path = self.get_upgrade_blueprint()
        rollback_inputs = {
            'private_ip': self.manager_private_ip,
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
        }
        rollback_inputs_file = self.manager_cfy._get_inputs_in_temp_file(
            rollback_inputs, self._testMethodName)

        with self.manager_cfy.maintenance_mode():
            self.manager_cfy.rollback_manager(
                blueprint_path=blueprint_path,
                inputs_file=rollback_inputs_file)

    def post_rollback_checks(self):
        self.rest_client.blueprints.list()
        self.check_elasticsearch(self.upgrade_manager_ip, 9200)
        self.check_influx(self.preupgrade_deployment_id)

    def teardown_manager(self):
        self.manager_cfy.teardown(ignore_deployments=True)
