#!/usr/bin/env bash
set -eax

cd $manager_dir
source $activate_path
cfy snapshots restore -s s
sleep 60
cfy agents install
