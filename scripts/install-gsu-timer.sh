#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -n bash "$0" "$@"
fi

gsu_repo_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
gsu_units_dir=${1:-"$gsu_repo_root/deploy/systemd"}
install -m 0644 "$gsu_units_dir/evenements-gsu-import.service" /etc/systemd/system/
install -m 0644 "$gsu_units_dir/evenements-gsu-import.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now evenements-gsu-import.timer
systemctl list-timers evenements-gsu-import.timer --no-pager
