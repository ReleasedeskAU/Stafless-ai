# Host setup — Ubuntu Server 24.04 LTS (noble)

Do this on the Azure VM **before** cloning **this StaffLess AI fork**, **before**
`docker compose build`, **before** `docker compose up`, and **before**
`setup-onyx.sh`. StaffLess AI containers — API, in-compose nginx, OpenSearch —
do not care about 22.04 vs 24.04. The host kernel, firewall backend, and
Docker Engine install do. Engine source is our
[Stafless-ai](https://github.com/ReleasedeskAU/Stafless-ai) fork of
**onyx-foss** (MIT), not the main Onyx repo. Compose/API names stay as that
software ships them.

Target: **Ubuntu Server 24.04 LTS**. Docker Engine lists Noble as a supported distro
(https://docs.docker.com/engine/install/ubuntu/).

VM size: **Azure D4as_v5** (4 vCPU / 16 GB, AMD). Same RAM/CPU count as D4s_v5;
compose limits in this folder are unchanged.

---

## 1. Docker networking on 24.04 (the actual difference)

Ubuntu 24.04’s `iptables` command is the **iptables-nft** frontend
(`iptables -V` prints `(nf_tables)`). That is what Docker Engine supports.

What is **not** compatible (Docker’s own install warning):

- Firewall rules created with the **`nft` command** / `/etc/nftables.conf`
  (`flush ruleset` wipes Docker’s tables; published ports die until
  `systemctl restart docker`).
- Switching the host to **`iptables-legacy`** because an old 22.04 blog said so.
  That splits rules across two backends and is a common way to break forwarding.
- Docker daemon `"iptables": false` — containers lose NAT and outbound HTTPS
  (OpenAI, image pulls).
- Docker 29’s experimental `"firewall-backend": "nftables"` — do not enable it
  for this deploy; it drops the `DOCKER-USER` chain.

**Do this after Docker is installed:**

```bash
iptables -V
# Expect: iptables v1.8.x (nf_tables)
# If it says (legacy), do not proceed — the alternatives pointer is wrong:
#   sudo update-alternatives --set iptables /usr/sbin/iptables-nft
#   sudo systemctl restart docker
```

Leave UFW **off** unless you have a reason. Azure NSG is the perimeter for
ports 80/3000/22. If you later enable UFW:

- Docker-published ports **bypass** UFW INPUT rules (documented Docker/UFW
  incompatibility). NSG still filters at the cloud edge.
- After `ufw enable`, run `sudo systemctl restart docker` so Docker re-inserts
  FORWARD/NAT rules (UFW’s default FORWARD policy is DROP on 24.04).
- Do not install `iptables-persistent` / `netfilter-persistent` — they snapshot
  stale Docker bridge IDs and drop forwarded traffic after reboot.

---

## 2. Install Docker Engine (official packages, not Ubuntu’s `docker.io`)

Uninstall distro packages if present, then follow Docker’s apt-repo steps for
**noble**. Install `docker-ce`, `docker-ce-cli`, `containerd.io`,
`docker-buildx-plugin`, and `docker-compose-plugin` (`docker compose`, not the
v1 `docker-compose` binary).

```bash
sudo apt update
sudo apt install --yes ca-certificates curl jq git
# then Docker’s GPG + docker.sources for $(. /etc/os-release && echo $VERSION_CODENAME)
# then:
sudo apt install --yes docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
# log out and back in before compose
sudo docker run --rm hello-world
docker compose version
```

`curl`, `jq`, and `git` are the same package names as on 22.04; `setup-onyx.sh`
needs curl/jq; cloning this fork needs git.

---

## 3. Host sysctl OpenSearch needs (not 24.04-specific, required anyway)

OpenSearch mmap-fails if the host default `vm.max_map_count` (65530) is left in place.

```bash
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf
sudo sysctl --system
sysctl vm.max_map_count   # must print 262144
```

---

## 4. Confirm before compose

| Check | Expected |
| --- | --- |
| `lsb_release -rs` | `24.04` |
| `iptables -V` | `(nf_tables)`, not `(legacy)` |
| `sysctl vm.max_map_count` | `262144` |
| `docker compose version` | Compose v2 plugin |
| `systemctl is-active docker` | `active` |
| `df -h /` | ≥20 GB free (first foss backend image build) |
| `nft list ruleset` (optional) | No hand-written `flush ruleset` workflow |

Then clone **this fork** (`ReleasedeskAU/Stafless-ai`), copy `.env` from
`deployment/releasedesk-overlay/`, **build the backend image from that
tree**, and start compose as in `README.md`. Then `setup-onyx.sh`. Do not
`compose up` against Docker Hub `onyxdotapp/onyx-backend` if the goal is a
foss MIT-only runtime.
