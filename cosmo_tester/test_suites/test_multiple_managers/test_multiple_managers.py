import random
import string
import time
import os

from cloudify_rest_client.exceptions import CloudifyClientError

from cosmo_tester.test_suites.test_blueprints.nodecellar_test import (
    OpenStackNodeCellarTest)


class MultiManagerTest(OpenStackNodeCellarTest):
    """
    This test bootstraps managers, installs nodecellar using the first manager,
    checks whether it was installed correctly, creates a snapshot, downloads it,
    uploads it to the second manager, uninstalls nodecellar using the second
    manager, checks whether nodecellar is actually not running and tears down
    those managers.

    It is required that there is at least one additional manager defined
    in handler configuration.
    """
    def _start_execution_and_wait(self, client, deployment, workflow_id):
        execution = client.executions.start(deployment, workflow_id)
        self.wait_for_execution(execution, self.default_timeout, client)

    def _create_snapshot(self, client, name):
        execution = client.snapshots.create(name, False, False)

        self.wait_for_execution(execution, self.default_timeout, client)

    def _restore_snapshot(self, client, name):
        execution = client.snapshots.restore(name, True)
        self.wait_for_execution(execution, self.default_timeout, client)

    def before_uninstall(self):
        self.logger.info('Creating snapshot...')
        self._create_snapshot(self.client, self.test_id)
        try:
            self.client.snapshots.get(self.test_id)
        except CloudifyClientError as e:
            self.fail(e.message)
        self.logger.info('Snapshot created.')

        self.logger.info('Downloading snapshot...')
        snapshot_file_name = ''.join(random.choice(string.ascii_letters)
                                     for _ in xrange(10))
        snapshot_file_path = os.path.join('/tmp', snapshot_file_name)
        self.client.snapshots.download(self.test_id, snapshot_file_path)
        self.logger.info('Snapshot downloaded.')

        self.logger.info('Uploading snapshot to the second manager...')
        self.additional_clients[0].snapshots.upload(snapshot_file_path,
                                                    self.test_id)
        # creating a snapshots is asynchronous, but it lasts a second or two...
        time.sleep(3)
        try:
            uploaded_snapshot = self.additional_clients[0].snapshots.get(
                self.test_id)
            self.assertEqual(
                uploaded_snapshot.status,
                'uploaded',
                "Snapshot {} has a wrong status: '{}' instead of 'uploaded'."
                .format(self.test_id, uploaded_snapshot.status)
            )
        except CloudifyClientError as e:
            self.fail(e.message)
        self.logger.info('Snapshot uploaded.')

        self.logger.info('Removing snapshot file...')
        if os.path.isfile(snapshot_file_path):
            os.remove(snapshot_file_path)
        self.logger.info('Snapshot file removed.')

        self.logger.info('Restoring snapshot...')
        self._restore_snapshot(self.additional_clients[0], self.test_id)
        try:
            self.additional_clients[0].deployments.get(self.test_id)
        except CloudifyClientError as e:
            self.fail(e.message)
        self.logger.info('Snapshot restored.')

        self.logger.info('Installing new agents...')
        self._start_execution_and_wait(
            self.additional_clients[0], self.test_id, 'install_new_agents')
        self.logger.info('Installed new agents.')

    def execute_uninstall(self, deployment_id=None, cfy=None):
        super(MultiManagerTest, self).execute_uninstall(
            cfy=self.additional_cfys[0])

    def assert_monitoring_data_exists(self):
        pass

    def post_uninstall_assertions(self, client=None):
        super(MultiManagerTest, self).post_uninstall_assertions(
            self.additional_clients[0])

    @property
    def default_timeout(self):
        return 1000

    @property
    def repo_branch(self):
        return 'tags/3.3m5'

    def get_inputs(self):
        return {
            'image': self.env.ubuntu_trusty_image_id,
            'flavor': self.env.medium_flavor_id,
            'agent_user': self.env.ubuntu_trusty_image_user
        }
