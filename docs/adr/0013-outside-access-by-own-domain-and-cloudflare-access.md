# Outside access goes through the owner's domain, Cloudflare Tunnel and Cloudflare Access, set up with the NAS

Status: accepted

ADR 0006 left open how the app opens outside the home once the NAS appears: Tailscale for free, or Cloudflare Tunnel with the owner's own domain shared with the owner's other apps. Stage 7.1's description (decision 2, 2026-11-07) chose Tailscale and wanted it on the PC in stage 7.2, before the NAS. On 2026-11-15 the owner decided otherwise (`.scratch/7-2-access-phone/description.md`, decision 1): their own domain (~$10 a year), Cloudflare Tunnel to reach the app without opening a port of the router, and **Cloudflare Access** in front — Cloudflare asks for a one-time code sent to the owner's mail before any request reaches the app, so strangers never see even the login page. The owner moves this app and another one to the NAS in a separate Claude Code project, which sets up one domain and one tunnel for both; this project only makes the app ready to stand behind them and documents what it needs. Until the NAS the app stays on the PC and the home network (ADR 0006, 0008).

Considered and rejected:
- Tailscale (7.1's choice): free and private, but every device needs the Tailscale app switched on, links from Telegram fail without it, and the address is `*.ts.net`, not shared with the owner's other app.
- Domain and tunnel without Cloudflare Access: the login page open to the whole internet; the password and the lockout (5 tries, 15 minutes) are the only guard, and anyone can keep the owner locked out.
- Setting up the tunnel on the PC now, in this project: the phone would work everywhere already in stage 9, but the NAS project would set it up again for two apps; the owner prefers one setup.

## Consequences

- Until the NAS the phone opens the app only at home, by the PC's address (`WEB_HOST=0.0.0.0`, `http`); installing it as an app on the phone (needs `https`) is checked by the NAS project.
- The app gets an address setting (the base of the links in bot messages) and must work behind a proxy: the real client address and `https` come in headers it trusts only from the proxy; it answers only to its own host names (KI-12).
- The login is hardened before the app reaches the internet (stage 7.2: KI-7, KI-8, KI-13, «Выйти на всех устройствах», a Telegram message on every login), even though Cloudflare Access stands in front.
- The Google Drive sign-in keeps returning to `localhost` (ADR 0012): it is made from a browser on the machine that runs the app; the token file moves with `data`.
- Stage 7.3 of this project shrinks to «NAS readiness and the move guide»; the move itself and the tunnel belong to the NAS project.
- The GitHub template (stage 8) works without a domain: the address setting is empty by default and the bot then behaves as before.
