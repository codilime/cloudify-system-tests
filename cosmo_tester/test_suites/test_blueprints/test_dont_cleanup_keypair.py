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

import os
import uuid

from cosmo_tester.framework.testenv import TestCase
from cloudify.workflows import local
from cloudify_cli import constants as cli_constants


class BreakingTest(TestCase):

    def test_and_break(self):
        """Doesn't clean up the keypair
        """

        # this runs "install", which creates a keypair, and throws an
        # exception in a script
        # this makes the .execute('install') call throw an exception too,
        # so control never reaches the .addCleanup line, thus uninstall
        # is never scheduled
        # cleanup is left for the system test handler to do, but currently
        # the openstack system test handler explicitly doesn't clean up
        # keypairs

        blueprint_dir = self.copy_blueprint('test-breaking')

        self.blueprint_yaml = blueprint_dir / 'with-keypair.yaml'
        self.inputs = {
            'os_username': self.env.keystone_username,
            'os_password': self.env.keystone_password,
            'os_tenant_name': self.env.keystone_tenant_name,
            'os_region': self.env.region,
            'os_auth_url': self.env.keystone_url,
            'prefix': self.env.resources_prefix,
            'key_pair_path': '{0}/keypair.pem'.format(self.workdir)
        }
        
        self.local_env = local.init_env(
            self.blueprint_yaml,
            inputs=self.inputs,
            name=self._testMethodName,
            ignored_modules=cli_constants.IGNORED_LOCAL_WORKFLOW_MODULES)
        self.addCleanup(self.env.handler.remove_keypair,
            self.inputs['prefix'] + '-keypair')

        self.local_env.execute('install', task_retries=0)
        self.addCleanup(self.uninstall)

    def uninstall(self):
        self.local_env.execute('uninstall',
                               task_retries=40,
                               task_retry_interval=30)
