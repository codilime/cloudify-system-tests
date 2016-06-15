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
from cStringIO import StringIO
from fabric.context_managers import quiet
import json
import os
import sh
import shutil
import time

from cosmo_tester.framework.testenv import bootstrap, teardown
from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.util import YamlPatcher


def setUp():
    bootstrap()


def tearDown():
    teardown()


UPGRADE_REPO_URL = 'https://github.com/codilime/' \
                   'cloudify-manager-blueprints.git'
UPGRADE_BRANCH = 'validation-fixups'


class TestManagerPreupgradeValidations(TestCase):
    def get_simple_blueprint(self):
        blueprint_dir = clone(UPGRADE_REPO_URL, self.workdir,
                              branch=UPGRADE_BRANCH)
        blueprint_path = (blueprint_dir /
                          'simple-manager-blueprint.yaml')
        self.addCleanup(shutil.rmtree, blueprint_dir)
        return blueprint_path

    def get_upgrade_inputs(self, **override):
        inputs = {
            'private_ip': self.cfy.get_management_ip(),
            'public_ip': self.cfy.get_management_ip(),
            'ssh_key_filename': self.env.management_key_path,
            'ssh_user': self.env.management_user_name
        }
        inputs.update(override)
        return self.cfy._get_inputs_in_temp_file(inputs, 'upgrade')

    def test_default_validations(self):
        inputs = self.get_upgrade_inputs()
        with self.cfy.maintenance_mode():
            self.cfy.upgrade_manager(
                blueprint_path=self.get_simple_blueprint(),
                inputs_file=inputs,
                validate_only=True)

    @contextmanager
    def change_es_port(self):
        es_properties_path = \
            '/opt/cloudify/elasticsearch/node_properties/properties.json'
        fetched_properties = StringIO()
        with self.manager_env_fabric() as fabric:
            fabric.get(es_properties_path,
                       fetched_properties)
            properties = json.loads(fetched_properties.getvalue())
            properties['es_endpoint_port'] = 10200
            fabric.put(StringIO(json.dumps(properties)),
                       es_properties_path)
            try:
                yield
            finally:
                fabric.put(fetched_properties, es_properties_path)

    def test_elasticsearch_up(self):
        """
        """
        inputs = self.get_upgrade_inputs()
        with self.change_es_port(), self.cfy.maintenance_mode():
            try:
                self.cfy.upgrade_manager(
                    blueprint_path=self.get_simple_blueprint(),
                    inputs_file=inputs,
                    validate_only=True)
            except sh.ErrorReturnCode as e:
                self.assertIn(
                    'ES returned an error when getting the provider context',
                    e.stdout)
            else:
                self.fail('ES validation should have failed')

    def test_elasticsearch_memory(self):
        blueprint_path = self.get_simple_blueprint()
        with YamlPatcher(blueprint_path) as yamlpatch:
                yamlpatch.set_value(
                    ('node_templates.elasticsearch.properties'
                     '.use_existing_on_upgrade'),
                    False)

        # set a heap size lower than what's currently used: just pass 1MB,
        # which surely must be lower than whatever the manager is
        # currently using!
        inputs = self.get_upgrade_inputs(elasticsearch_heap_size='1m')
        with self.cfy.maintenance_mode():
            try:
                self.cfy.upgrade_manager(
                    blueprint_path=blueprint_path,
                    inputs_file=inputs,
                    validate_only=True)
            except sh.ErrorReturnCode as e:
                self.assertIn(
                    'Elasticsearch Heap Size',
                    e.stdout)
            else:
                self.fail('ES validation should have failed')

    @contextmanager
    def disable_service(self, service_name):
        with self.manager_env_fabric() as fabric:
            fabric.sudo('systemctl stop {0}'.format(service_name))

        try:
            yield
        finally:
            with self.manager_env_fabric() as fabric, quiet():
                fabric.sudo('systemctl start {0}'.format(service_name))
                while True:
                    status = fabric.sudo('systemctl status {0}'.format(
                        service_name))
                    if status.return_code == 0:
                        break
                    time.sleep(1)

    def test_service_alive_checks(self):
        blueprint_path = self.get_simple_blueprint()
        inputs = self.get_upgrade_inputs()

        with self.cfy.maintenance_mode():
            # we can't test nginx or the restservice this way, because if we
            # turn them off, we won't be able to execute the upgrade :)
            for service_name, display_name in [
                ('cloudify-mgmtworker', 'mgmtworker'),
                ('logstash', 'logstash'),
                ('elasticsearch', 'elasticsearch'),
                ('cloudify-amqpinflux', 'amqpinflux'),
                ('cloudify-riemann', 'riemann'),
                ('cloudify-amqpinflux', 'amqpinflux'),
                ('cloudify-influxdb', 'influxdb')
            ]:
                with self.disable_service(service_name):
                    try:
                        self.cfy.upgrade_manager(
                            blueprint_path=blueprint_path,
                            inputs_file=inputs,
                            validate_only=True)
                    except sh.ErrorReturnCode as e:
                        self.assertIn(
                            '{0} is not running'.format(display_name),
                            e.stdout.lower())
                    else:
                        self.fail('should have failed')

    @contextmanager
    def move_upgrade_dirs(self, node_name):
        base = os.path.join('/opt/cloudify', node_name)
        properties_dir = os.path.join(base, 'node_properties')
        properties_dir_backup = os.path.join(base, 'node_properties_backup')
        resources_dir = os.path.join(base, 'resources')
        resources_dir_backup = os.path.join(base, 'resources_backup')

        with self.manager_env_fabric() as fabric:
            fabric.sudo('mv {0} {1}'.format(properties_dir,
                                            properties_dir_backup))
            fabric.sudo('mv {0} {1}'.format(resources_dir,
                                            resources_dir_backup))

        try:
            yield
        finally:
            with self.manager_env_fabric() as fabric:
                fabric.sudo('mv {0} {1}'.format(properties_dir_backup,
                                                properties_dir))
                fabric.sudo('mv {0} {1}'.format(resources_dir_backup,
                                                resources_dir))

    def test_node_directories(self):
        blueprint_path = self.get_simple_blueprint()
        inputs = self.get_upgrade_inputs()

        with self.cfy.maintenance_mode():
            for node_name in [
                'influxdb',
                'rabbitmq',
                'elasticsearch',
                'amqpinflux',
                'logstash',
                'restservice',
                'nginx',
                'riemann',
                'mgmtworker',
            ]:
                with self.move_upgrade_dirs(node_name):
                    try:
                        self.cfy.upgrade_manager(
                            blueprint_path=blueprint_path,
                            inputs_file=inputs,
                            validate_only=True)
                    except sh.ErrorReturnCode as e:
                        self.assertIn(
                            'service {0} has no properties file'.format(
                                node_name),
                            e.stdout.lower())
                    else:
                        self.fail('Upgrade directories validation for {0} '
                                  'succeeded, but it should have failed - '
                                  'node properties and rollback directories '
                                  'are missing'.format(node_name))

    def get_node_properties(self, node_name):
        fetched_properties = StringIO()
        properties_path = os.path.join('/opt/cloudify', node_name,
                                       'node_properties/properties.json')
        with self.manager_env_fabric() as fabric:
            fabric.get(properties_path, fetched_properties)
        fetched_properties.seek(0)
        return json.load(fetched_properties)

    def test_rabbit_credentials_changed(self):
        rabbitmq_properties = self.get_node_properties('rabbitmq')
        blueprint_path = self.get_simple_blueprint()
        with YamlPatcher(blueprint_path) as yamlpatch:
                yamlpatch.set_value(
                    ('node_templates.rabbitmq.properties'
                     '.use_existing_on_upgrade'),
                    False)

        new_password = rabbitmq_properties['rabbitmq_password'] + '-changed'
        inputs = self.get_upgrade_inputs(rabbitmq_password=new_password)

        with self.cfy.maintenance_mode():
            try:
                self.cfy.upgrade_manager(
                    blueprint_path=blueprint_path,
                    inputs_file=inputs,
                    validate_only=True)
            except sh.ErrorReturnCode as e:
                self.assertIn('rabbitmq properties must not change',
                              e.stdout.lower())
            else:
                self.fail('rabbitmq validation should have failed')
