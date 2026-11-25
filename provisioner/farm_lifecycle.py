import os, sys, json, time, base64, argparse, subprocess, urllib.request, urllib.error

BASE_DIR = "/home/hermes_node/skyblock_control"
PROV_DIR = f"{BASE_DIR}/provisioner"
ENV_FILE = f"{PROV_DIR}/.env"
CONFIG_FILE = f"{PROV_DIR}/config.json"
SESSION_FILE = f"{PROV_DIR}/active_session.json"
BACKUP_FILE = f"{BASE_DIR}/backups/mc_farm_state.tar.gz"
SSH_KEY = "/home/hermes_node/.ssh/cherry_farm_key"
API_BASE = "https://api.cherryservers.com/v1"

def get_token():
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("CHERRY_API_TOKEN="):
                return line.strip().split("=", 1)[1].strip("'\"")
    raise RuntimeError("Token not found")

def api_req(method, path, payload=None):
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def get_ubuntu_image(plan_slug):
    status, data = api_req("GET", f"/plans/{plan_slug}/images")
    if status == 200 and isinstance(data, list):
        for img in data:
            slug = img.get("slug", "")
            if "ubuntu_22_04" in slug or "ubuntu_24_04" in slug:
                return slug
        if data:
            return data[0].get("slug")
    return "ubuntu_22_04"

def start_server(hours):
    if os.path.exists(SESSION_FILE):
        print("Error: Active session already exists! Run status or stop first.")
        return

    with open(CONFIG_FILE) as f:
        cfg = json.load(f)

    plan_slug = cfg["plan"]["slug"] if isinstance(cfg["plan"], dict) else cfg["plan"]
    region = cfg["plan"]["regions"][0] if isinstance(cfg["plan"], dict) else cfg.get("region", "LT-Siauliai")
    image = cfg.get("image") or get_ubuntu_image(plan_slug)
    cfg["image"] = image
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

    with open(f"{PROV_DIR}/cloud_init.sh", "rb") as f:
        user_data_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "plan": plan_slug,
        "region": region,
        "image": image,
        "hostname": "mc-farm-worker",
        "ssh_keys": [int(cfg["ssh_key_id"])],
        "cycle": "hourly",
        "user_data": user_data_b64
    }

    print(f"Deploying server ({plan_slug} | {image} | {region})...")
    status, res = api_req("POST", f"/projects/{cfg['project_id']}/servers", payload)
    if status not in (200, 201):
        print(f"Failed ({status}): {res}")
        return

    server_id = res["id"]
    print(f"Server created! ID: {server_id}. Waiting for active state & IP...")

    ip_addr = None
    for _ in range(40):
        time.sleep(15)
        st, info = api_req("GET", f"/servers/{server_id}")
        if st == 200 and info.get("state") == "active":
            ips = info.get("ip_addresses", [])
            pub = [i["address"] for i in ips if i.get("type") == "primary-ip"]
            if pub:
                ip_addr = pub[0]
                break

    if not ip_addr:
        print("Timeout waiting for server IP. Check Cherry portal!")
        return

    destroy_at = time.time() + (hours * 3600)
    session = {"server_id": server_id, "ip": ip_addr, "hours": hours, "destroy_at": destroy_at}
    with open(SESSION_FILE, "w") as f:
        json.dump(session, f, indent=2)

    print(f"Server ACTIVE at IP: {ip_addr}. Waiting for cloud_init READY_FLAG...")
    ssh_opts = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
    for _ in range(30):
        time.sleep(15)
        chk = subprocess.run(["ssh", *ssh_opts, f"root@{ip_addr}", "test -f /root/READY_FLAG && echo READY"], capture_output=True, text=True)
        if "READY" in chk.stdout:
            break

    if os.path.exists(BACKUP_FILE):
        print("Restoring PrismLauncher state backup...")
        subprocess.run(["scp", *ssh_opts, BACKUP_FILE, f"root@{ip_addr}:/root/mc_farm_state.tar.gz"])
        subprocess.run(["ssh", *ssh_opts, f"root@{ip_addr}", "tar -xzf /root/mc_farm_state.tar.gz -C /root/.local/share/PrismLauncher"])

    cmd = f"sleep {int(hours * 3600)} && python3 {PROV_DIR}/farm_lifecycle.py stop >> {PROV_DIR}/lifecycle.log 2>&1"
    subprocess.Popen(["nohup", "bash", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print(f"DONE! Worker ready at {ip_addr} | Auto-destroy scheduled in {hours}h.")

def stop_server():
    if not os.path.exists(SESSION_FILE):
        print("No active session found.")
        return

    with open(SESSION_FILE) as f:
        session = json.load(f)

    server_id = session["server_id"]
    ip_addr = session["ip"]
    ssh_opts = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]

    print(f"Backing up PrismLauncher state from {ip_addr}...")
    subprocess.run(["ssh", *ssh_opts, f"root@{ip_addr}", "pkill -SIGTERM java || true; sleep 3; tar -czf /root/mc_farm_state.tar.gz -C /root/.local/share/PrismLauncher ."])
    subprocess.run(["scp", *ssh_opts, f"root@{ip_addr}:/root/mc_farm_state.tar.gz", BACKUP_FILE])

    print(f"Terminating server {server_id} via Cherry API...")
    status, res = api_req("DELETE", f"/servers/{server_id}")
    print(f"DELETE response ({status}): {res}")
    if status in (200, 202, 204, 404):
        os.remove(SESSION_FILE)
        print("Server destroyed & billing stopped!")

def status_server():
    if not os.path.exists(SESSION_FILE):
        print("Status: IDLE (No active worker server).")
        return
    with open(SESSION_FILE) as f:
        s = json.load(f)
    rem = max(0, int((s["destroy_at"] - time.time()) / 60))
    print(f"Status: ACTIVE | Server ID: {s['server_id']} | IP: {s['ip']} | Remaining: {rem} mins")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--hours", type=float, default=4.0)
    args = parser.parse_args()
    if args.action == "start": start_server(args.hours)
    elif args.action == "stop": stop_server()
    elif args.action == "status": status_server()
