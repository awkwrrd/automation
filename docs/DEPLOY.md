# Deploying on a Linux server (Ubuntu)

Tested layout: Ubuntu 22.04/24.04 server or VM, Docker Engine + Compose plugin, the stack from
`docker-compose.yml` (PostgreSQL, WMS, mock picking system, optional Cloudflare tunnel). All containers
restart automatically after a reboot.

## 1. Install Docker (once)

Run on the server (SSH in first, e.g. `ssh you@10.1.0.34`):
```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```
Log out and SSH in again (so `docker` works without `sudo`), then check: `docker run --rm hello-world`.

## 2. Get the code

```bash
git clone https://github.com/awkwrrd/automation.git ~/automation
cd ~/automation
```
For a private repo, git asks for a username and password: use your GitHub username and a **personal access
token** (GitHub → Settings → Developer settings → Fine-grained tokens, read-only *Contents* on this repo) as the
password.

## 3. Configuration (`.env`)

Copy `.env` from the old machine (it holds the mock's API key and any secrets), from the old machine's
project folder (PowerShell on Windows has `scp` built in):
```powershell
scp .env you@10.1.0.34:~/automation/.env
```
Then on the server, edit it (`nano ~/automation/.env`) and make sure it contains at least:
```
WMS_SECRET_KEY=<long random string>      # generate one: openssl rand -hex 32
WMS_ADMIN_PASSWORD=<only used when the users table is empty>
WMS_PUBLIC_URL=http://10.1.0.34:8000     # how other systems reach this WMS
WMS_SEED_DEMO_DATA=false                 # if you're moving data over or want a clean start
MOCK_PICKING_API_KEY=<keep the same key so the SOFTBOT config still works>
```
`WMS_SECRET_KEY` must not stay at the default: it signs logins. Changing it logs everyone out once.

## 4a. Fresh start

```bash
cd ~/automation
docker compose --profile tunnel up -d --build     # drop "--profile tunnel" if nothing in the cloud needs the mock
```

## 4b. Move the data from the old machine instead

**On the old machine** (project folder; the stack must be running). Dump inside the container and copy the
file out, which avoids PowerShell changing the file's encoding:
```powershell
docker compose exec -T db pg_dump -U wms -d wms -f /tmp/wms.sql
docker compose cp db:/tmp/wms.sql .\wms.sql
scp .\wms.sql you@10.1.0.34:~/automation/wms.sql
```
**On the server**, load it into an empty database *before* the WMS starts (otherwise the WMS creates its own
tables and the restore conflicts):
```bash
cd ~/automation
docker compose up -d db                        # database only
sleep 5
docker compose cp wms.sql db:/tmp/wms.sql
docker compose exec -T db psql -U wms -d wms -v ON_ERROR_STOP=1 -q -f /tmp/wms.sql
docker compose --profile tunnel up -d --build  # now start everything
rm wms.sql                                     # it contains secrets (Shopify, endpoints, users)
```
Then **stop the old machine's stack** (`docker compose down` there). Two WMS copies connected to the same
Shopify store would both import orders, push stock and create fulfillments.

## 5. Check and connect

- WMS: `http://10.1.0.34:8000` from any machine on that network. Mock: `http://10.1.0.34:9100/?key=<key>`.
- Firewall: if `sudo ufw status` says *active*, allow the ports: `sudo ufw allow 8000/tcp` and `sudo ufw allow 9100/tcp`.
- New tunnel address for the cloud SOFTBOT: `docker compose logs tunnel | grep trycloudflare` and update the
  SOFTBOT's URL.
- Logs: `docker compose logs -f wms` (Ctrl+C to stop following). Status: `docker compose ps`.

## Updating to a new version

```bash
cd ~/automation && git pull && docker compose --profile tunnel up -d --build
```
Database changes (new columns/tables) are applied automatically on start. Note that rebuilding restarts the
tunnel, which gets a new address.

## Backups

One-off:
```bash
cd ~/automation && mkdir -p backups
docker compose exec -T db pg_dump -U wms -d wms | gzip > backups/wms-$(date +%F-%H%M).sql.gz
```
Nightly at 02:30, keeping 14 days (`crontab -e`, add one line):
```
30 2 * * * cd $HOME/automation && mkdir -p backups && docker compose exec -T db pg_dump -U wms -d wms | gzip > backups/wms-$(date +\%F).sql.gz && find backups -name 'wms-*.sql.gz' -mtime +14 -delete
```
Restore a backup into an empty database the same way as step 4b (`gunzip -k` it first).
Backups contain secrets: keep them on the server or encrypted storage.

## Before others use it

- [ ] `WMS_SECRET_KEY` set to a long random value
- [ ] `admin` password changed; demo users `supervisor` / `operator` deactivated or re-passworded
- [ ] Each person has their own user with the right role (Operator / Supervisor / Admin)
- [ ] `MOCK_PICKING_API_KEY` set if the tunnel is on
- [ ] Remote teammates: use a VPN-style network (e.g. Tailscale on the server) rather than exposing port 8000
      to the internet
- [ ] Nightly backup in place
