#! /usr/bin/env python
# flake8: NOQA

import os
import json
import tempfile
import logging

import yaml

logger = logging.getLogger('suites_builder')
logger.setLevel(logging.INFO)


def build_suites_json(all_suites_json_path):
    env_system_tests_suites = os.environ['SYSTEM_TESTS_SUITES']
    env_custom_suite = os.environ['SYSTEM_TESTS_CUSTOM_SUITE']
    env_custom_suite_name = os.environ['SYSTEM_TESTS_CUSTOM_SUITE_NAME']
    env_custom_tests_to_run = os.environ['SYSTEM_TESTS_CUSTOM_TESTS_TO_RUN']
    env_custom_cloudify_config = os.environ['SYSTEM_TESTS_CUSTOM_CLOUDIFY_CONFIG']
    env_custom_bootstrap_using_providers = os.environ['SYSTEM_TESTS_CUSTOM_BOOTSTRAP_USING_PROVIDERS']
    env_custom_bootstrap_using_docker = os.environ['SYSTEM_TESTS_CUSTOM_BOOTSTRAP_USING_DOCKER']
    env_custom_use_external_agent_packages = os.environ['SYSTEM_TESTS_CUSTOM_USE_EXTERNAL_AGENT_PACKAGES']
    env_custom_handler_module = os.environ['SYSTEM_TESTS_CUSTOM_HANDLER_MODULE']

    logger.info('Creating suites json configuration:\n'
                '\tSYSTEM_TESTS_SUITES={}\n'
                '\tSYSTEM_TESTS_CUSTOM_SUITE={}\n'
                '\tSYSTEM_TESTS_CUSTOM_SUITE_NAME={}\n'
                '\tSYSTEM_TESTS_CUSTOM_TESTS_TO_RUN={}\n'
                '\tSYSTEM_TESTS_CUSTOM_CLOUDIFY_CONFIG={}\n'
                '\tSYSTEM_TESTS_CUSTOM_BOOTSTRAP_USING_PROVIDERS={}\n'
                '\tSYSTEM_TESTS_CUSTOM_BOOTSTRAP_USING_DOCKER={}\n'
                '\tSYSTEM_TESTS_CUSTOM_USE_EXTERNAL_AGENT_PACKAGES={}\n'
                '\tSYSTEM_TESTS_CUSTOM_HANDLER_MODULE={}'
                .format(env_system_tests_suites,
                        env_custom_suite,
                        env_custom_suite_name,
                        env_custom_tests_to_run,
                        env_custom_cloudify_config,
                        env_custom_bootstrap_using_providers,
                        env_custom_bootstrap_using_docker,
                        env_custom_use_external_agent_packages,
                        env_custom_handler_module))

    tests_suites = [s.strip() for s in env_system_tests_suites.split(',')]
    custom_suite = env_custom_suite == 'yes'
    custom_suite_name = env_custom_suite_name
    custom_tests_to_run = env_custom_tests_to_run
    custom_cloudify_config = env_custom_cloudify_config
    custom_bootstrap_using_providers = \
        env_custom_bootstrap_using_providers == 'yes'
    custom_bootstrap_using_docker = \
        env_custom_bootstrap_using_docker == 'yes'
    custom_use_external_agent_packages = \
        env_custom_use_external_agent_packages == 'yes'
    custom_handler_module = env_custom_handler_module

    suites_json_path = tempfile.mktemp(prefix='suites-', suffix='.json')

    if custom_suite:
        suites = [{
            'suite_name': custom_suite_name,
            'tests_to_run': custom_tests_to_run,
            'cloudify_test_config': custom_cloudify_config,
            'bootstrap_using_providers': custom_bootstrap_using_providers,
            'bootstrap_using_docker': custom_bootstrap_using_docker,
            'use_external_agent_packages': custom_use_external_agent_packages,
            'cloudify_test_handler_module': custom_handler_module
        }]
    else:
        with open(all_suites_json_path) as f:
            suites_file = yaml.load(f.read())
        all_suites = suites_file['suites']
        suites = []
        for suite_name, suite in all_suites.items():
            if suite_name in tests_suites:
                suite['suite_name'] = suite_name
                suites.append(suite)

    with open(suites_json_path, 'w') as f:
        f.write(json.dumps(suites))

    return suites_json_path
