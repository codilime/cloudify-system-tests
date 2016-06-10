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
import json
from mock import patch
import sh
import shutil
import tempfile

from cosmo_tester.framework.testenv import bootstrap, teardown
from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.git_helper import clone


def setUp():
    bootstrap()


def tearDown():
    teardown()


UPGRADE_REPO_URL = 'https://github.com/cloudify-cosmo/' \
                   'cloudify-manager-blueprints.git'
UPGRADE_BRANCH = 'master'


class TestManagerPreupgradeValidations(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared_workdir = tempfile.mkdtemp(prefix='manager-upgrade-')
        cls.blueprint_dir = clone(UPGRADE_REPO_URL, cls.shared_workdir,
                                  branch=UPGRADE_BRANCH)
        cls.blueprint_path = (cls.blueprint_dir /
                              'simple-manager-blueprint.yaml')

    def get_upgrade_inputs(self, **override):
        inputs = {
            'private_ip': self.cfy.get_management_ip(),
            'public_ip': self.cfy.get_management_ip(),
            'ssh_key_filename': self.env.management_key_path,
            'ssh_user': self.env.management_user_name
        }
        inputs.update(override)
        return self.cfy._get_inputs_in_temp_file(inputs, 'upgrade')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.shared_workdir)

    def test_default_validations(self):
        import pudb; pu.db  # NOQA
        inputs = self.get_upgrade_inputs()
        with self.cfy.maintenance_mode():
            self.cfy.upgrade_manager(
                blueprint_path=self.blueprint_path,
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
        import pudb; pu.db  # NOQA
        inputs = self.get_upgrade_inputs()
        with self.change_es_port(), self.cfy.maintenance_mode(),\
                patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            try:
                self.cfy.upgrade_manager(
                    blueprint_path=self.blueprint_path,
                    inputs_file=inputs,
                    validate_only=True)
            except sh.ErrorReturnCode:
                self.assertIn(
                    'ES returned an error when getting the provider context',
                    mock_stdout.getvalue())
            else:
                self.fail('ES validation should have failed')
