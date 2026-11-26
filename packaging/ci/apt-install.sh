#!/bin/bash
# Installs Ubuntu packages on a GitHub build machine: apt-install.sh <package>...
# The machine's own Ubuntu mirror is sometimes so slow that a few packages take minutes. So a try that stalls is
# stopped for real (with what it left behind, so the next one doesn't wait for its lock), and the next try uses the
# main Ubuntu archive instead. What a stopped try already downloaded stays in apt's cache, so nothing is fetched twice.
set -u
APT="-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o DPkg::Lock::Timeout=60 -o Dpkg::Use-Pty=0"
sudo rm -f /var/lib/man-db/auto-update  # its rebuild after installing can stall for a long time
for try in 1 2 3; do
  if timeout -k 15 420 sudo env DEBIAN_FRONTEND=noninteractive sh -c "apt-get update $APT && apt-get install -y --no-install-recommends $APT $*"; then
    exit 0
  fi
  echo "::group::try $try stopped: what was running"
  ps -eo pid,etimes,stat,args --sort=etimes | grep -E 'apt|dpkg|http|ldconfig|man|update-' | grep -v grep | cut -c1-150 | tail -15
  echo "::endgroup::"
  sudo pkill -9 -x apt-get || true; sudo pkill -9 -f /usr/lib/apt/methods/ || true; sudo pkill -9 -x dpkg || true
  sudo dpkg --configure -a || true
  if [ "$try" = 1 ] && [ -f /etc/apt/apt-mirrors.txt ]; then  # from now on the main archive first
    echo "switching to the main Ubuntu archive"
    printf 'http://archive.ubuntu.com/ubuntu/\n' | sudo tee /etc/apt/apt-mirrors.txt.new >/dev/null
    sudo sh -c 'cat /etc/apt/apt-mirrors.txt >> /etc/apt/apt-mirrors.txt.new && mv /etc/apt/apt-mirrors.txt.new /etc/apt/apt-mirrors.txt'
  fi
  sleep 10
done
exit 1
