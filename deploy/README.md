# Deploy to Oracle Cloud Free Tier

## Prerequisites

- Oracle Cloud Free Tier account (sign up at https://cloud.oracle.com)
- An Ubuntu VM created (ARM, 4 OCPU, 24GB RAM — always free)

## Steps

### 1. From your local machine — package the project

```powershell
# In yt_autopilot directory, compress everything
Compress-Archive -Path * -DestinationPath ..\yt_autopilot.zip -Force
```

### 2. Copy to Oracle Cloud VM

```powershell
# Replace <VM-IP> with your instance's public IP
scp ..\yt_autopilot.zip ubuntu@<VM-IP>:~
```

### 3. SSH into the VM and set up

```bash
ssh ubuntu@<VM-IP>

# Unzip
sudo apt install unzip -y
unzip yt_autopilot.zip -d ~/yt_autopilot

# Run the setup script
cd ~/yt_autopilot
bash deploy/setup.sh
```

### 4. Start the autopilot

```bash
sudo systemctl start autopilot
```

## Managing the service

```bash
# Check status
sudo systemctl status autopilot

# View live logs
journalctl -u autopilot -f

# Stop
sudo systemctl stop autopilot

# Restart
sudo systemctl restart autopilot
```

## Test manually before starting the service

```bash
cd ~/yt_autopilot
source venv/bin/activate
python main.py --status
```

## Updating

```bash
sudo systemctl stop autopilot
# Upload new files, then:
sudo systemctl start autopilot
```

## How the loop works

`python main.py --loop --interval=4`

This runs indefinitely:
1. Check current subscriber count and goals
2. Run Manager to re-evaluate strategy
3. Produce 1 long video + 1 auto-clipped Short
4. Upload both to YouTube
5. Wait 4 hours
6. Repeat

The service auto-restarts on crash or reboot.
