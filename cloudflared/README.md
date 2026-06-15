# Cloudflare Tunnel — quick reference

This directory contains a config file you can use with the `cloudflared`
Docker sidecar (defined in `docker-compose.yml` under the `cloudflared`
service) or with a host-installed `cloudflared` binary.

## Setup

1. **Create a tunnel** in the Cloudflare Zero Trust dashboard:
   - Go to https://one.dash.cloudflare.com → Zero Trust → Networks → Tunnels
   - Click "Create a tunnel" → choose "Cloudflared"
   - Name it `mirrorself`
   - Copy the **TUNNEL_TOKEN** that gets shown

2. **Add hostnames** to route traffic:
   - `mirrorself.example.com` → `http://frontend:3000`
   - `api.example.com` → `http://backend:8000`
   - (or edit `config.yml` to match the hostnames you own)

3. **Put the token in `.env`:**
   ```env
   TUNNEL_TOKEN=eyJhIjoiN...
   ```

4. **Start the stack with the tunnel profile:**
   ```bash
   docker compose --profile tunnel up -d
   ```

## Standalone use

If you'd rather run `cloudflared` on the host (not in Docker):

```bash
# One-time login
cloudflared tunnel login

# Run with the config in this directory
cloudflared tunnel --config cloudflared/config.yml run
```

Make sure the hostnames in `config.yml` are reachable from the host where
`cloudflared` runs (use `localhost:3000` / `localhost:8000` if running the
stack locally without Docker).

## Notes

- Don't commit the tunnel credentials JSON (`<TUNNEL_ID>.json`).
- Use `cloudflared tunnel info mirrorself` to confirm the tunnel is up.
- Logs are at `cloudflared` if running in Docker: `docker compose logs cloudflared`.
