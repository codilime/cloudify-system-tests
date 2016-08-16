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
import json
import shutil
import logging
import tempfile
from contextlib import contextmanager

import sh
import yaml
import requests
from path import path

from cloudify_cli.utils import (load_cloudify_working_dir_settings,
                                get_configuration_path,
                                update_wd_settings)
from cosmo_tester.framework.util import (sh_bake,
                                         YamlPatcher,
                                         download_file)


DEFAULT_EXECUTE_TIMEOUT = 1800
INPUTS = 'inputs'
PARAMETERS = 'parameters'


class CfyHelper(object):

    def __init__(self,
                 cfy_workdir=None,
                 management_ip=None,
                 management_user=None,
                 management_key=None,
                 management_port='22',
                 executable=sh.cfy,
                 username=None,
                 password=None,
                 trust_all=False):
        env = {}
        if username and password:
            env = {'CLOUDIFY_USERNAME': username,
                   'CLOUDIFY_PASSWORD': password}
        if trust_all:
            env['CLOUDIFY_SSL_TRUST_ALL'] = 'true'
        if env:
            executable = executable.bake(_env=env)
        self._executable = sh_bake(executable)
        self._executable_out = executable
        self.logger = logging.getLogger('TESTENV')
        self.logger.setLevel(logging.INFO)
        self._cfy_workdir = cfy_workdir
        self.tmpdir = False
        if cfy_workdir is None:
            self.tmpdir = True
            self._cfy_workdir = tempfile.mkdtemp(prefix='cfy-')
        self.workdir = path(self._cfy_workdir)
        if management_ip is not None:
            self.use(management_ip)
            if management_user and management_key and management_port:
                try:
                    self._set_management_creds(management_user, management_key,
                                               management_port)
                except Exception as ex:
                    self.logger.warn(
                        'Failed to set management creds. Note that you will '
                        'not be able to perform ssh actions after bootstrap. '
                        'Reason: {0}'.format(ex))

    def bootstrap(self,
                  blueprint_path,
                  inputs_file=None,
                  install_plugins=True,
                  keep_up_on_failure=False,
                  validate_only=False,
                  reset_config=False,
                  task_retries=5,
                  task_retry_interval=90,
                  subgraph_retries=2,
                  verbose=False,
                  debug=False):
        with self.workdir:
            self._executable.init(reset_config=reset_config).wait()

            with YamlPatcher(get_configuration_path()) as patch:
                prop_path = ('local_provider_context.'
                             'cloudify.workflows.subgraph_retries')
                patch.set_value(prop_path, subgraph_retries)

            if not inputs_file:
                inputs_file = self._get_inputs_in_temp_file({}, 'manager')

            self._executable.bootstrap(
                blueprint_path=blueprint_path,
                inputs=inputs_file,
                install_plugins=install_plugins,
                keep_up_on_failure=keep_up_on_failure,
                validate_only=validate_only,
                task_retries=task_retries,
                task_retry_interval=task_retry_interval,
                verbose=verbose,
                debug=debug).wait()

            if not validate_only:
                self.upload_plugins()

    def _download_wagons(self):
        self.logger.info('Downloading Wagons...')

        wagon_paths = []

        plugin_urls_location = (
            'https://raw.githubusercontent.com/cloudify-cosmo/'
            'cloudify-versions/{branch}/packages-urls/plugin-urls.yaml'.format(
                branch=os.environ.get('BRANCH_NAME_CORE', 'master'),
            )
        )

        plugins = yaml.load(
            requests.get(plugin_urls_location).text
        )['plugins']
        for plugin in plugins:
            self.logger.info(
                'Downloading: {0}...'.format(plugin['wgn_url'])
            )
            wagon_paths.append(
                download_file(plugin['wgn_url'])
            )
        return wagon_paths

    def upload_plugins(self):
        downloaded_wagon_paths = self._download_wagons()
        for wagon in downloaded_wagon_paths:
            with self.workdir:
                self.logger.info('Uploading {0}'.format(wagon))
                upload = self._executable.plugins.upload(p=wagon, verbose=True)
                upload.wait()

    def recover(self, snapshot_path, task_retries=5):
        with self.workdir:
            self._executable.recover(force=True,
                                     task_retries=task_retries,
                                     snapshot_path=snapshot_path).wait()

    def create_snapshot(self,
                        snapshot_id,
                        include_metrics=False,
                        exclude_credentials=False):
        with self.workdir:
            self._executable.snapshots.create(
                snapshot_id=snapshot_id,
                include_metrics=include_metrics,
                exclude_credentials=exclude_credentials).wait()

    def download_snapshot(self, snapshot_id, output_path=''):

        with self.workdir:
            self._executable.snapshots.download(
                snapshot_id=snapshot_id,
                output=output_path).wait()

    def teardown(self,
                 ignore_deployments=True,
                 verbose=False):
        with self.workdir:
            self._executable.teardown(
                ignore_deployments=ignore_deployments,
                force=True,
                verbose=verbose).wait()

    def uninstall(self, deployment_id, workflow_id, parameters,
                  allow_custom_parameters, timeout, include_logs):

        parameters = self._get_parameters_in_temp_file(parameters, workflow_id)

        with self.workdir:
            self._executable.uninstall(
                deployment_id=deployment_id, workflow=workflow_id,
                parameters=parameters,
                allow_custom_parameters=allow_custom_parameters,
                timeout=timeout, include_logs=include_logs).wait()

    def install(
            self,
            blueprint_path,
            blueprint_id,
            deployment_id,
            verbose=False,
            include_logs=True,
            execute_timeout=DEFAULT_EXECUTE_TIMEOUT,
            inputs=None):

        inputs_file = self._get_inputs_in_temp_file(inputs, deployment_id)

        with self.workdir:
            self._executable.install(blueprint_path=blueprint_path,
                                     blueprint_id=blueprint_id,
                                     deployment_id=deployment_id,
                                     inputs=inputs_file,
                                     timeout=execute_timeout,
                                     include_logs=include_logs,
                                     verbose=verbose).wait()

    upload_deploy_and_execute_install = install

    def publish_archive(self,
                        blueprint_id,
                        archive_location,
                        verbose=False):
        with self.workdir:
            self._executable.blueprints.publish_archive(
                blueprint_id=blueprint_id,
                archive_location=archive_location,
                blueprint_filename='blueprint.yaml',
                verbose=verbose).wait()

    def create_deployment(self,
                          blueprint_id,
                          deployment_id,
                          verbose=False,
                          inputs=None):
        with self.workdir:
            inputs_file = self._get_inputs_in_temp_file(inputs, deployment_id)
            self._executable.deployments.create(
                blueprint_id=blueprint_id,
                deployment_id=deployment_id,
                verbose=verbose,
                inputs=inputs_file).wait()

    def delete_deployment(self, deployment_id,
                          verbose=False,
                          ignore_live_nodes=False):
        with self.workdir:
            self._executable.deployments.delete(
                deployment_id=deployment_id,
                ignore_live_nodes=ignore_live_nodes,
                verbose=verbose).wait()

    def delete_blueprint(self, blueprint_id,
                         verbose=False):
        with self.workdir:
            self._executable.blueprints.delete(
                blueprint_id=blueprint_id,
                verbose=verbose).wait()

    def list_blueprints(self, verbose=False):
        with self.workdir:
            self._executable.blueprints.list(verbose=verbose).wait()

    def list_deployments(self, verbose=False):
        with self.workdir:
            self._executable.deployments.list(verbose=verbose).wait()

    def list_executions(self, verbose=False):
        with self.workdir:
            self._executable.executions.list(verbose=verbose).wait()

    def list_events(self, execution_id, verbosity='', include_logs=True):
        with self.workdir:
            command = self._executable_out.events.list.bake(
                execution_id=execution_id,
                include_logs=include_logs)
            if verbosity:
                command = command.bake(verbosity)
            return command().stdout.strip()

    def get_blueprint(self, blueprint_id, verbose=False):
        with self.workdir:
            self._executable.blueprints.get(
                blueprint_id=blueprint_id, verbose=verbose).wait()

    def get_deployment(self, deployment_id, verbose=False):
        with self.workdir:
            self._executable.deployments.get(
                deployment_id=deployment_id, verbose=verbose).wait()

    def update_deployment(self,
                          deployment_id,
                          blueprint_path=None,
                          inputs=None,
                          blueprint_filename=None,
                          archive_location=None,
                          skip_install=False,
                          skip_uninstall=False,
                          workflow_id=None,
                          force=False,
                          include_logs=None,
                          json=None):

        deployment_update_kwargs = {
            'skip_install': skip_install,
            'skip_uninstall': skip_uninstall,
            'force': force
        }

        if blueprint_path:
            deployment_update_kwargs['blueprint_path'] = blueprint_path
        if inputs:
            deployment_update_kwargs['inputs'] = inputs
        if blueprint_filename:
            deployment_update_kwargs['blueprint_filename'] = blueprint_filename
        if archive_location:
            deployment_update_kwargs['archive_location'] = archive_location
        if workflow_id:
            deployment_update_kwargs['workflow_id'] = workflow_id
        if include_logs:
            deployment_update_kwargs['include_logs'] = include_logs
        if json:
            deployment_update_kwargs['json'] = json

        with self.workdir:
            self._executable.deployments.update(
                deployment_id=deployment_id, **deployment_update_kwargs)

    def get_execution(self, execution_id, verbose=False):
        with self.workdir:
            self._executable.executions.get(
                execution_id=execution_id, verbose=verbose).wait()

    def cancel_execution(self, execution_id, verbose=False):
        with self.workdir:
            self._executable.executions.cancel(
                execution_id=execution_id, verbose=verbose).wait()

    def execute_install(self,
                        deployment_id,
                        verbose=False,
                        include_logs=True,
                        execute_timeout=DEFAULT_EXECUTE_TIMEOUT):
        self.execute_workflow(
            workflow='install',
            deployment_id=deployment_id,
            execute_timeout=execute_timeout,
            verbose=verbose,
            include_logs=include_logs)

    def execute_uninstall(self,
                          deployment_id,
                          verbose=False,
                          include_logs=True,
                          execute_timeout=DEFAULT_EXECUTE_TIMEOUT):
        self.execute_workflow(
            workflow='uninstall',
            deployment_id=deployment_id,
            execute_timeout=execute_timeout,
            verbose=verbose,
            include_logs=include_logs)

    def upload_blueprint(self,
                         blueprint_id,
                         blueprint_path,
                         verbose=False):
        with self.workdir:
            self._executable.blueprints.upload(
                blueprint_path=blueprint_path,
                blueprint_id=blueprint_id,
                verbose=verbose).wait()

    def download_blueprint(self, blueprint_id):
        with self.workdir:
            self._executable.blueprints.download(
                blueprint_id=blueprint_id).wait()

    def download_plugin(self, plugin_id, output_file):
        with self.workdir:
            self._executable.plugins.download(
                plugin_id=plugin_id, output=output_file).wait()

    def use(self, management_ip):
        with self.workdir:
            self._executable.use(management_ip=management_ip).wait()

    def get_management_ip(self):
        with self.workdir:
            settings = load_cloudify_working_dir_settings()
            return settings.get_management_server()

    def _set_management_creds(self, user, key, port):
        with self.workdir, update_wd_settings() as ws_settings:
            ws_settings.set_management_user(user)
            ws_settings.set_management_key(key)
            ws_settings.set_management_port(port)

    def get_provider_context(self):
        with self.workdir:
            settings = load_cloudify_working_dir_settings()
            return settings.get_provider_context()

    def install_agents(self, deployment_id=None, include_logs=False,
                       install_script=None):
        kwargs = {'include_logs': include_logs}
        if deployment_id is not None:
            kwargs['deployment_id'] = deployment_id

        if install_script is not None:
            kwargs['install_script'] = install_script

        with self.workdir:
            self._executable.agents.install(**kwargs).wait()

    def close(self):
        if self.tmpdir:
            shutil.rmtree(self._cfy_workdir)

    def execute_workflow(self,
                         workflow,
                         deployment_id,
                         verbose=False,
                         include_logs=True,
                         execute_timeout=DEFAULT_EXECUTE_TIMEOUT,
                         parameters=None):

        params_file = self._get_parameters_in_temp_file(parameters, workflow)
        with self.workdir:
            self._executable.executions.start(
                workflow=workflow,
                deployment_id=deployment_id,
                timeout=execute_timeout,
                verbose=verbose,
                include_logs=include_logs,
                parameters=params_file).wait()

    def download_logs(self, output=os.getcwd()):
        with self.workdir:
            self._executable.logs.download(
                output=output,
                verbose=True).wait()

    def purge_logs(self, force=True, backup_first=False):
        with self.workdir:
            self._executable.logs.purge(
                force=force,
                backup_first=backup_first,
                verbose=True).wait()

    def backup_logs(self):
        with self.workdir:
            self._executable.logs.backup(verbose=True).wait()

    def ssh_list(self):
        with self.workdir:
            return self._executable_out.ssh(list=True)

    def ssh_run_command(self, command):
        with self.workdir:
            return self._executable_out.ssh(command=command)

    def install_plugins_locally(self, blueprint_path):
        self._executable.local(
            'install-plugins',
            blueprint_path=blueprint_path).wait()

    def _get_dict_in_temp_file(self, dictionary, prefix, suffix):
        dictionary = dictionary or {}
        file_ = tempfile.mktemp(prefix='{0}-'.format(prefix),
                                suffix=suffix,
                                dir=self.workdir)
        with open(file_, 'w') as f:
            f.write(json.dumps(dictionary))
        return file_

    def _get_inputs_in_temp_file(self, inputs, inputs_prefix):
        return self._get_dict_in_temp_file(dictionary=inputs,
                                           prefix=inputs_prefix,
                                           suffix='-inputs.json')

    def _get_parameters_in_temp_file(self, parameters, parameters_prefix):
        return self._get_dict_in_temp_file(dictionary=parameters,
                                           prefix=parameters_prefix,
                                           suffix='-parameters.json')

    def upgrade_manager(self,
                        blueprint_path,
                        inputs_file=None,
                        validate_only=False,
                        install_plugins=True):
        if not inputs_file:
            inputs_file = self._get_inputs_in_temp_file({}, 'manager')
        with self.workdir:
            self._executable.upgrade(
                blueprint_path=blueprint_path,
                inputs=inputs_file,
                validate_only=validate_only,
                install_plugins=install_plugins).wait()

    def rollback_manager(self, blueprint_path, inputs_file=None):
        if not inputs_file:
            inputs_file = self._get_inputs_in_temp_file({}, 'manager')
        with self.workdir:
            self._executable.rollback(
                blueprint_path=blueprint_path,
                inputs=inputs_file).wait()

    def set_maintenance_mode(self, activate):
        maintenance_handler = self._executable.bake('maintenance-mode')
        with self.workdir:
            if activate:
                maintenance_handler.activate(wait=True).wait()
            else:
                maintenance_handler.deactivate().wait()

    @contextmanager
    def maintenance_mode(self):
        self.set_maintenance_mode(True)
        try:
            yield
        finally:
            self.set_maintenance_mode(False)

    def upload_snapshot(self, snapshot_id, path):
        with self.workdir:
            self._executable.snapshots.upload(s=snapshot_id, p=path).wait()

    def restore_snapshot(self, snapshot_id):
        with self.workdir:
            self._executable.snapshots.restore(s=snapshot_id).wait()
