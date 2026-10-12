#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -n bash "$0" "$@"
fi

cinema_repo_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cinema_units_dir=${1:-"$cinema_repo_root/deploy/systemd"}
install -m 0644 "$cinema_units_dir/evenements-cinema-import.service" /etc/systemd/system/
install -m 0644 "$cinema_units_dir/evenements-cinema-import.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now evenements-cinema-import.timer
systemctl list-timers evenements-cinema-import.timer --no-pager
