#!/usr/bin/env bash
set -eax

cd $manager_dir
source $activate_path
cfy executions start -w uninstall -d windows
