# Deployment: always-on macOS host

Meridian is designed to run continuously on a dedicated Apple Silicon machine (a Mac Mini is
the reference host). The core application is platform-agnostic; this document covers the
macOS-specific process management, media, and networking pieces. None of it is required to
develop or demo the system — see the [README](../README.md) quickstart and
[RUNBOOK](RUNBOOK.md) for that.

## Host preparation

Configure the machine to stay up and recover unattended:

```bash
sudo pmset -a sleep 0 disksleep 0     # never sleep
sudo pmset -a womp 1                  # wake on network
sudo pmset -a autorestart 1           # auto-restart after power loss
```

Enable auto-login for the service user and turn on FileVault. Keep all scheduling in
`America/New_York` (the code uses zoneinfo, DST-correct) with storage in UTC.

## Process management with launchd

launchd owns the process lifecycle (no container runtime for the core services — native is
lighter on the host). Three agents live in `config/launchd/`:

- `com.meridian.daemon.plist` — runs `meridiand` with `KeepAlive=true` and `RunAtLoad=true`,
  so it restarts on crash and on boot. stdout/stderr go to `~/Library/Logs/meridian/`.
- `com.meridian.watchdog.plist` — every 5 minutes it curls `/api/health`; after three
  consecutive failures it sends a P0 push through the standalone notifier CLI, which works
  even when the daemon itself is down.
- `com.meridian.backup.plist` — nightly at 02:30, runs the SQLite online backup and mirrors
  Parquet to a second location.

Install and control:

```bash
make install-launchd                                     # loads all three agents
launchctl kickstart -k gui/$(id -u)/com.meridian.daemon  # restart
launchctl bootout   gui/$(id -u)/com.meridian.daemon     # stop
tail -f ~/Library/Logs/meridian/daemon.err.log
```

## Private networking (Tailscale)

Run Tailscale on the host and on the devices that view the dashboard. Bind the daemon to the
tailnet interface only — there is no public exposure and no port forwarding. Issue a trusted
certificate with `tailscale cert` so the PWA loads over HTTPS at
`https://<host>.<tailnet>.ts.net`, and set `TAILNET_BASE_URL` in `.env` so deep links and the
podcast feed resolve to that address.

## Audio briefs (Piper TTS)

The morning brief can be synthesised to speech locally with Piper (fast on Apple Silicon,
free, private) and served as a private podcast RSS feed that a podcast app auto-downloads.
`audio.py` always writes the spoken-word script; when `piper` and `ffmpeg` are on the PATH it
also renders the audio file. Install the extras group to enable it:

```bash
uv sync --extra mac        # piper-tts + playwright
```

## Designed push cards (Playwright)

The `/og/brief/:id` route renders an Apple-styled HTML card for each brief. On the host,
Playwright screenshots that route into a PNG that is attached to the morning push, so the
notification itself looks designed. Off-host (or headless without Playwright) the push simply
sends without the image attachment — no functionality is lost.

## iMessage channel (optional)

As an optional P0 fan-out channel on macOS, the notifier can send via iMessage using
`osascript`. Set `IMESSAGE_TO` in `.env` to enable it. This is macOS-only and purely additive
to the ntfy/Pushover channels.

## Verification checklist on the host

- [ ] `kill -9` the daemon → launchd relaunches it within the throttle interval.
- [ ] Reboot → the daemon comes up via `RunAtLoad` and `/api/health` is green.
- [ ] A real P1 push lands on the phone via ntfy.
- [ ] Stop the daemon → the watchdog fires a P0 after three failed checks.
- [ ] `pmset` never-sleep + autorestart set; FileVault on; Tailscale HTTPS certificate issued.
