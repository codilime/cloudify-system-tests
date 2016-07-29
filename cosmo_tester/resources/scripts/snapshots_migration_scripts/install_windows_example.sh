#!/usr/bin/env bash
set -eax

cd $manager_dir
source $activate_path
cfy blueprints upload -b windows -p $windows_blueprint_path
cfy deployments create -b windows -d windows
cfy executions start -w install -d windows
