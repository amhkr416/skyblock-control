---
name: skyblock-farm
description: Provision, manage, monitor, and terminate ephemeral Cherry Servers Minecraft Skyblock worker nodes with automated backup and cost protection.
---

# Skyblock Ephemeral Farm Orchestrator

## When to Use
Use this skill whenever the user asks to start, stop, check status, deploy, or destroy the Minecraft Skyblock farm server, or manage its Floating IP and PrismLauncher backups.

## Core Commands
All scripts reside in /home/hermes_node/skyblock_control/provisioner/.

1. Start a timed farm session (default 4 hours, $0.05/hr):
   Run in background to avoid 180s tool timeout:
   nohup python3 /home/hermes_node/skyblock_control/provisioner/farm_lifecycle.py start --hours <HOURS> > /home/hermes_node/skyblock_control/provisioner/start.log 2>&1 &
   Wait 20 seconds, then inspect start.log and active_session.json to report the Server ID and IP.

2. Check active server status:
   python3 /home/hermes_node/skyblock_control/provisioner/farm_lifecycle.py status

3. Stop, backup PrismLauncher state, and destroy server immediately:
   python3 /home/hermes_node/skyblock_control/provisioner/farm_lifecycle.py stop

## Critical Pitfalls & Verification
- Always verify via Cherry API GET /v1/projects/303342/servers after stop that no orphan server remains billing.
- Never commit .env, config.json, active_session.json, or backups/ to Git.
