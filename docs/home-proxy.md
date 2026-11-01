# Home proxy for sites that block GitHub

Some agency sites block GitHub Actions' datacenter IPs but let a home internet connection through:
Pulse and Fox & Wood (Cloudflare) refuse them, and Century 21 Sutherland Shire never answers. For
those sources, the weekly run sends its requests through a small proxy on an always-on home
server, reached over [Tailscale](https://tailscale.com). Every other request still goes out
directly from GitHub.

```
GitHub Actions run ──(Tailscale, private)──► home server :8888 (tinyproxy) ──► pulseproperty.com.au
        └──────────── everything else goes direct ───────────────────────────► Ray White, Gemini, Gmail…
```

Nothing is exposed to the internet: no router ports are opened, the proxy accepts only Tailscale
clients, it forwards only to the sites on its allowlist, and Tailscale's access rules let the GitHub
run reach that one port and nothing else on your network. If the home server is down, only the
proxied sources fail that week; the digest lists them under failing sources.

Everything here is free: Tailscale's Personal plan covers it.

The steps use a Ubuntu server; any always-on Linux box works.

## 1. Install Tailscale on the server

SSH to the server, then:

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

`tailscale up` prints a login link. Open it and sign in to your Tailscale account. Then:

```sh
tailscale ip -4                       # the server's Tailscale IP, 100.x.y.z: you need it below
sudo tailscale set --auto-update      # keep Tailscale patched
```

In the [Tailscale admin console](https://login.tailscale.com/admin/machines), open the server's
**⋯** menu and choose **Disable key expiry**. Otherwise it drops off the network after 180 days.

## 2. Install and configure the proxy

```sh
sudo apt install -y tinyproxy
sudo cp /etc/tinyproxy/tinyproxy.conf /etc/tinyproxy/tinyproxy.conf.orig

sudo tee /etc/tinyproxy/tinyproxy.conf > /dev/null <<'EOF'
# property-hunter: lets GitHub Actions reach sites that block datacenter IPs. See docs/home-proxy.md.
User tinyproxy
Group tinyproxy
Port 8888
# Listens on all interfaces (binding to the Tailscale IP fails if tinyproxy starts before
# Tailscale at boot), but only Tailscale clients and this machine are allowed in.
Allow 127.0.0.1
Allow 100.64.0.0/10
# HTTPS only, and only to the sites in the allowlist.
ConnectPort 443
FilterDefaultDeny Yes
FilterType fnmatch
Filter "/etc/tinyproxy/allowed-hosts"
DisableViaHeader Yes
Timeout 120
MaxClients 20
LogFile "/var/log/tinyproxy/tinyproxy.log"
LogLevel Info
PidFile "/run/tinyproxy/tinyproxy.pid"
EOF

sudo tee /etc/tinyproxy/allowed-hosts > /dev/null <<'EOF'
# Sites the GitHub run may reach through this proxy: one domain pattern per line.
pulseproperty.com.au
*.pulseproperty.com.au
foxandwood.com.au
*.foxandwood.com.au
c21sutherlandshire.com.au
*.c21sutherlandshire.com.au
EOF

# Ubuntu's AppArmor profile lets tinyproxy read only tinyproxy.conf; without this it exits with
# "filter file: Permission denied". The local/ override survives package upgrades.
echo 'file r /etc/tinyproxy/allowed-hosts,' | sudo tee /etc/apparmor.d/local/tinyproxy
sudo apparmor_parser -r /etc/apparmor.d/tinyproxy

sudo systemctl enable tinyproxy
sudo systemctl restart tinyproxy
```

Check it from the server itself:

```sh
curl -s -o /dev/null -w "proxy=%{http_connect} site=%{http_code}\n" -x http://127.0.0.1:8888 https://www.pulseproperty.com.au/robots.txt
# proxy=200 site=200
curl -s -o /dev/null -w "proxy=%{http_connect} site=%{http_code}\n" -x http://127.0.0.1:8888 https://example.com/
# proxy=403 site=000: refused, not on the allowlist
```

Then from another computer on your home network, use the server's LAN IP (`127.0.0.1` there is that
computer itself, so curl would just print `000`):

```sh
curl -s -o /dev/null -w "proxy=%{http_connect} site=%{http_code}\n" -x http://192.168.1.100:8888 https://www.pulseproperty.com.au/robots.txt
# proxy=403 site=000: refused, only Tailscale clients are let in
```

## 3. Tailscale access rules

In the admin console, open **Access controls → JSON editor** and replace the policy with the one
below, replacing `100.x.y.z` with the server's Tailscale IP from step 1 (saving fails with
`ParseAddr("100.x.y.z")` otherwise). Compared with the default policy, it adds the `tag:ci` tag
for GitHub runs, lets those runs reach only port 8888 on the server, and keeps your own devices
able to reach everything as before (the default's `"src": ["*"]` would let GitHub runs in too).

```jsonc
{
  "hosts": {
    "home-proxy": "100.x.y.z",
  },
  "tagOwners": {
    "tag:ci": ["autogroup:admin"],
  },
  "grants": [
    // Your own devices: everything, as before.
    {"src": ["autogroup:member"], "dst": ["*"], "ip": ["*"]},
    // GitHub Actions runs: only the proxy.
    {"src": ["tag:ci"], "dst": ["home-proxy"], "ip": ["tcp:8888"]},
  ],
  "ssh": [
    {
      "action": "check",
      "src": ["autogroup:member"],
      "dst": ["autogroup:self"],
      "users": ["autogroup:nonroot", "root"],
    },
  ],
}
```

If your policy already has other rules, keep them and add only the `hosts` entry, the `tagOwners`
entry and the `tag:ci` grant, and make sure no rule with `"src": ["*"]` remains.

## 4. Credentials for GitHub

In the admin console, open **Settings → Trust credentials** (called *OAuth clients* in older
versions), create a new **OAuth** credential, give it the **Auth Keys → Write** scope with the tag
`tag:ci`, and generate it. Copy the client ID and secret; the secret is shown only once.

In the GitHub repo, **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|---|---|
| `TS_OAUTH_CLIENT_ID` | the client ID |
| `TS_OAUTH_SECRET` | the client secret |
| `HOME_PROXY_HOST` | the server's Tailscale IP, e.g. `100.101.102.103` |

The workflow skips Tailscale entirely while `HOME_PROXY_HOST` is unset.

## 5. Test

Actions → weekly → Run workflow (mode **dry-run** sends nothing). In the log:

- **Join Tailscale** succeeds, and **Check home proxy** prints `home proxy OK`.
- The Run step shows `pulse: N listing(s)` instead of `source pulse failed: … 403`.

Each run appears briefly in the Tailscale admin console as an ephemeral `tag:ci` machine and is
removed automatically afterwards.

## Sending another agency through the proxy

1. In `config/sources.yaml`, add `via_home_proxy: true` to the source.
2. On the server, add its domain to `/etc/tinyproxy/allowed-hosts` (both `example.com.au` and
   `*.example.com.au`), then `sudo systemctl restart tinyproxy`.

## Troubleshooting

| Symptom | Check |
|---|---|
| **Join Tailscale** fails with "requested tags are invalid" | `tag:ci` is missing from `tagOwners`, or the OAuth credential wasn't given that tag. |
| **Check home proxy** times out | On the server: `tailscale status` (is it online?), `systemctl status tinyproxy`. In the admin console, is the server's key expired? Is the `tag:ci` grant in the policy? |
| `curl` through the proxy prints `000` | tinyproxy isn't running: `systemctl status tinyproxy`. "filter file: Permission denied" means the AppArmor override in step 2 is missing. |
| Proxy answers 403 | The site isn't in `/etc/tinyproxy/allowed-hosts`; see `/var/log/tinyproxy/tinyproxy.log`. |
| The site still returns 403 through the proxy | The site now blocks the home IP too: test with `curl` on the server, without the proxy. |
| Local runs | `HOME_PROXY` isn't set locally, so proxied sources are fetched directly, which works from home. |
