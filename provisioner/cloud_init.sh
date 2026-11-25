#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y openjdk-17-jre openjdk-8-jre xvfb x11vnc fluxbox wget tar jq

mkdir -p /root/PrismLauncher /root/.local/share/PrismLauncher
cd /root/PrismLauncher
wget -q "https://github.com/PrismLauncher/PrismLauncher/releases/download/9.2/PrismLauncher-Linux-x86_64.AppImage" -O PrismLauncher.AppImage
chmod +x PrismLauncher.AppImage
./PrismLauncher.AppImage --appimage-extract

Xvfb :99 -screen 0 1280x720x16 &
sleep 2
DISPLAY=:99 fluxbox &
x11vnc -display :99 -nopw -forever -bg

touch /root/READY_FLAG
