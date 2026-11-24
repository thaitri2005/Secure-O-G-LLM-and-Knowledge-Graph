# The shared server: setup and use

**Owner:** Hung (Track C) · **Plan task:** B1 · **Work list:** [note of 24 November, Task 1](note-from-track-B-2026-11-24.md#task-1-b1-put-the-stores-on-a-shared-server)

The server hosts PostgreSQL with pgvector and Neo4j for the whole team. It runs Docker only. The loading scripts run on our own computers and reach the databases through an SSH tunnel, so the server needs no Python and no model.

| Thing | Value |
|---|---|
| Provider, region, size | *to fill in:* DigitalOcean, Singapore, 4 vCPU / 8 GB / 80 GB, Ubuntu 24.04 LTS |
| Address | *to fill in* |
| Login | `ssh kg@<address>`, SSH keys only |
| Open ports | 22 (SSH) and 443 (HTTPS, for the application later). The databases listen on the server's `127.0.0.1` only |
| Repository on the server | `/srv/kg/repo` (public clone of `main`) |
| K1 releases | `/srv/k1/<release>/` |
| Backups | `/srv/backups/kg-<UTC time>.dump`, nightly, 7 days kept |
| Passwords | In `/srv/kg/repo/platform/.env` on the server only. Never in the repository, which is public |

## 0. For now: a team machine over Tailscale (no budget yet)

There is no money for a server yet (Track C log C-D06). Until a free one is found (student credits, the school, a free tier), one team machine hosts the stores and the others reach it over **Tailscale**, a free private network between our computers. Nothing is opened to the internet. Proposed host: Tri's desktop, which is on most often and runs the engine; **Tri has to agree**.

| | Interim (Tailscale) | Later (cloud server, sections 1 to 8) |
|---|---|---|
| Up | When the host machine is on | Always |
| Reached by | Tailscale address of the host, e.g. `tri-desktop` or `100.x.y.z` | SSH tunnel to the server |
| Cost | US$0 | Student credits, or the contingency in the resource request |
| Good for | Tasks 3 and 4, Khai's releases, one shared copy of the data | Also the demo application (Task 5) |

**Set up, once:**

1. Everyone installs Tailscale (tailscale.com/download) and signs in. The host's owner creates the network (tailnet) and invites the other two; the free personal plan should cover three people (check the current plan limits).
2. On the host: Docker running, then in the repository `git pull`, `platform/.env` from `platform/.env.example` with long random passwords, and `docker compose -f platform/docker-compose.yml up -d`.
3. Still on the host, share the two database ports with the tailnet only. The compose file keeps them on `127.0.0.1`; Tailscale forwards to them:

   ```bash
   tailscale serve --bg --tcp 5434 tcp://127.0.0.1:5434
   tailscale serve --bg --tcp 7687 tcp://127.0.0.1:7687
   tailscale serve --bg --tcp 7474 tcp://127.0.0.1:7474
   tailscale serve status
   ```

   If the command is refused, check `tailscale serve --help` for the installed version. Never change the compose file to `0.0.0.0`.
4. Give the passwords to the team privately.

**Use, from any team machine** (Tailscale on), with the host's name from `tailscale status`:

```bash
export SERVER_PG="postgresql://kg:<POSTGRES_PASSWORD>@<host>:5434/kg"
export SERVER_NEO4J_PASSWORD="<NEO4J_PASSWORD>"
.venv/bin/python platform/k1_store.py --dsn "$SERVER_PG" compare data/interim/k1/ak3-k1v1-proposed
.venv/bin/python platform/load_facts_neo4j.py --uri bolt://<host>:7687 --password "$SERVER_NEO4J_PASSWORD"
```

The loaders in section 6 work the same way with these addresses. Neo4j Browser: `http://<host>:7474`.

**Backups:** PostgreSQL holds the K1 release and its vectors, both rebuilt from the release folder by `load_k1.py` and `embed_k1.py`, and Neo4j is rebuilt by its loaders. Run `platform/server/backup.sh` with `OUT=<folder>` after each load (Git Bash or WSL on Windows) rather than nightly.

**Done when:** from a second machine, `k1_store.py compare` reports every chunk identical through the Tailscale address. When a cloud server arrives, follow sections 1 to 8 and load the same release there.

## 1. Before: an SSH key and the credit

1. On your computer, if `ls ~/.ssh/*.pub` shows nothing, make a key: `ssh-keygen -t ed25519 -C "<your name>"`. Give it a passphrase. Your **public** key is `~/.ssh/id_ed25519.pub`; the other file is private and never leaves your computer.
2. Redeem the GitHub Student Developer Pack's DigitalOcean offer and add the public key in DigitalOcean (Settings, Security, SSH keys).

## 2. Create the server

In DigitalOcean: Create, Droplets. Ubuntu 24.04 (LTS) x64; Singapore; Basic, Regular, 4 vCPU / 8 GB / 160 GB or the nearest size; authentication by **SSH key** (the one you added). Name it `kg-platform`. Write the address in the table above.

## 3. First setup, as root

From the repository folder on your computer:

```bash
scp platform/server/setup.sh root@<address>:
ssh root@<address> "bash setup.sh"
```

Then, **in a second terminal**, check `ssh kg@<address>` works. Only then close the root session: [`setup.sh`](../../../platform/server/setup.sh) turns off root and password logins.

## 4. The stores

As `kg` on the server:

```bash
git clone https://github.com/thaitri2005/Secure-O-G-LLM-and-Knowledge-Graph.git /srv/kg/repo
cd /srv/kg/repo
cp platform/.env.example platform/.env
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|; s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=$(openssl rand -hex 24)|" platform/.env
chmod 600 platform/.env
docker compose -f platform/docker-compose.yml up -d
docker compose -f platform/docker-compose.yml ps
```

Give the two passwords to the team privately (not in chat logs that are committed, not in the repository): `cat platform/.env`.

Nightly backup: `crontab -e` and add

```
15 3 * * * /srv/kg/repo/platform/server/backup.sh >> /srv/backups/backup.log 2>&1
```

Run `platform/server/backup.sh` once by hand to check it.

## 5. Reaching the databases: the tunnel

On your computer. Local Docker already uses ports 5434, 7474 and 7687, so the tunnel uses 1xxxx ports:

```bash
ssh -N -L 15434:127.0.0.1:5434 -L 17474:127.0.0.1:7474 -L 17687:127.0.0.1:7687 kg@<address>
```

Leave it running. Then, in another terminal, set the passwords from the server's `platform/.env`:

```bash
export SERVER_PG="postgresql://kg:<POSTGRES_PASSWORD>@127.0.0.1:15434/kg"
export SERVER_NEO4J_PASSWORD="<NEO4J_PASSWORD>"
```

Neo4j Browser: http://127.0.0.1:17474, connect to `bolt://127.0.0.1:17687` as `neo4j`.

## 6. Loading a release

Copy the K1 release to the server, so the team has one copy:

```bash
rsync -av data/interim/k1/ak3-k1v1-proposed/ kg@<address>:/srv/k1/ak3-k1v1-proposed/
```

Then load from your computer through the tunnel, with the project's `.venv` and the embedding model running for step 2 ([graphrag/README.md](../../../graphrag/README.md)):

```bash
.venv/bin/python platform/load_k1.py data/interim/k1/ak3-k1v1-proposed --dsn "$SERVER_PG"
.venv/bin/python platform/embed_k1.py embed --dsn "$SERVER_PG"
.venv/bin/python platform/embed_k1.py check --dsn "$SERVER_PG"
.venv/bin/python platform/load_events_neo4j.py --uri bolt://127.0.0.1:17687 --password "$SERVER_NEO4J_PASSWORD"
.venv/bin/python platform/load_facts_neo4j.py --uri bolt://127.0.0.1:17687 --password "$SERVER_NEO4J_PASSWORD"
```

Each script checks its own result and rolls back on a difference; read its last lines.

## 7. Done when

From Tri's computer, through the tunnel:

```bash
python platform/k1_store.py --dsn "$SERVER_PG" compare <package>
```

reports every chunk identical, and Khai can connect too. Record the provider, address, release loaded and the check in the [Track C log](log.md). No password there.

## 8. Giving someone access

They send their **public** key (`~/.ssh/id_ed25519.pub`). On the server, as `kg`, add it as one line to `~/.ssh/authorized_keys`. To remove someone, delete their line.

## If something goes wrong

| Symptom | Likely cause |
|---|---|
| `required variable POSTGRES_PASSWORD is missing` | No `platform/.env` next to the compose file |
| Password refused after changing `.env` | PostgreSQL and Neo4j read the password only on their first start with an empty volume. Change it inside the database, or delete the volume (`down -v`, **erases the data**) |
| `ssh: connect ... Connection refused` on the tunnel | The tunnel's terminal was closed, or the server is off |
| `Address already in use` when opening the tunnel | Another tunnel is still running; close it |
| Restore a backup | `docker compose -f platform/docker-compose.yml exec -T postgres pg_restore -U kg -d kg --clean < /srv/backups/kg-<time>.dump` |
