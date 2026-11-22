# Socialize Bot

A social and fun Discord bot in the style of hangout servers like [Socialize](https://discord.gg/vc). Every command works both as a `.` prefix command (for example `.games`) and as a slash command (`/games`).

## Features

- **Games:** trivia, rock paper scissors, would you rather, truth or dare, plus a `.games` menu to launch them. Optional counting channel.
- **Roles:** a button panel so members can pick their own roles, and mod commands to add or remove roles.
- **Levels:** XP from chatting and from time in voice (ignored when alone, AFK, or self-deafened). Rank, XP leaderboard, voice time, voice leaderboard, and automatic level roles.
- **Welcome messages** with configurable text and placeholders.
- **Join to Create voice channels:** members join a setup channel, get a personal VC, and can lock, unlock, limit, rename, kick, permit, or claim it. A button control panel is posted in the channel's chat. Temporary channels are deleted when empty.
- **Voice stats:** how many people are in voice right now.

## Setup

### 1. Create the bot application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Open the **Bot** tab and click **Add Bot** if needed.
3. Under **Privileged Gateway Intents**, turn on:
   - **Server Members Intent**
   - **Message Content Intent**
4. The bot also needs the **Voice States** intent, which is enabled in the code (it is not a privileged toggle).
5. Click **Reset Token** and copy the token. Keep it private.

### 2. Invite the bot

In **OAuth2 → URL Generator**, tick scopes `bot` and `applications.commands`. Use these permissions, or this invite URL (replace `YOUR_CLIENT_ID` with the application ID from the General Information tab):

```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=1099945077846&scope=bot%20applications.commands
```

The permission set includes: View Channel, Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions, Use External Emojis, Manage Channels, Manage Roles, Manage Messages, Connect, Move Members, Mute Members, Deafen Members, Manage Nicknames, Ban Members, Kick Members, and Moderate Members.

Put the bot's role above any roles it should assign (self-roles and level roles).

### 3. Run the bot

```bash
cd socialize-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Paste the token into .env as DISCORD_TOKEN=...
python main.py
```

Slash commands can take a minute to appear the first time the bot starts. If they are missing, the bot owner can run `.sync`.

## Quick setup in a server

| Goal | Command |
| --- | --- |
| Game menu | `.games` |
| Counting channel | `.setcounting #counting` |
| Self-role panel | `.selfrole add @Role` then `.selfrole panel` |
| Welcome messages | `.setwelcome #welcome Welcome to {server}, {mention}!` |
| Level-up channel | `.setlevelchannel #levels` |
| Level roles | `.levelrole add 5 @Regular` |
| Join to Create | `.setupjtc` |
| Voice stats | `.vcstats` |

Use `.help` or `/help` for the full list. Temporary voice owners can also use the control panel posted in their channel, or `.vc lock`, `.vc unlock`, `.vc limit`, `.vc rename`, `.vc kick`, `.vc permit`, and `.vc claim`.

Voice XP and `.voicetime` only count time spent in a voice channel with at least one other person, and not while AFK or self-deafened.

## Web dashboard

The bot also serves a web dashboard from the same process (default port `8080`, or the `PORT` environment variable). Sign in with Discord (OAuth2 scopes `identify` and `guilds`). You only see servers where you have **Manage Server**, and the bot is already a member. Servers you can manage but the bot is missing show an **Invite** button.

Panels: Overview, Channels, Levels, Self Roles, Alt Detection (including an Alt Detection Log of flagged joins with filters, search, and Kick / Ban / Timeout 1h / Mark Safe actions), Welcome, Games, Moderation, and Billing. Changes apply to the live bot immediately.

To enable login, create an OAuth2 redirect in the [Discord Developer Portal](https://discord.com/developers/applications) for this application:

1. Open the app → **OAuth2**.
2. Copy the **Client Secret**.
3. Add a redirect URL: `https://YOUR-DASHBOARD-HOST/callback` (locally: `http://127.0.0.1:8080/callback`).
4. Put these in `.env` (see `.env.example`):

```
DISCORD_CLIENT_ID=1573391890227925002
DISCORD_CLIENT_SECRET=your_client_secret
DASHBOARD_URL=https://YOUR-DASHBOARD-HOST
SESSION_SECRET=a-long-random-string
```

The bot still starts if `DISCORD_CLIENT_SECRET` is missing; dashboard login stays disabled.

## Deploying

The same process runs both the Discord bot and the dashboard, so you only start `python main.py` once. Set `PORT` if your host assigns one (Render and Railway do). Set `DASHBOARD_URL` to the public HTTPS origin, with no trailing slash, and register `DASHBOARD_URL/callback` as the OAuth2 redirect.

### Render

1. Push this repo to GitHub and create a new Web Service from it (the included `render.yaml` Blueprint also works).
2. Add environment variables: `DISCORD_TOKEN`, `DISCORD_CLIENT_SECRET`, `DISCORD_CLIENT_ID` (default is already in the Blueprint), `DASHBOARD_URL` (your `https://….onrender.com` URL), and `SESSION_SECRET`.
3. Attach a persistent disk and set `DATA_DIR` to the mount path (the Blueprint uses `/var/data`). SQLite lives in that folder as `bot.db`.
4. After the first deploy, confirm the OAuth2 redirect is exactly `DASHBOARD_URL/callback`.

Render’s free and starter filesystems are otherwise ephemeral: without a disk, the database (levels, settings, alt logs, warnings) is wiped on every deploy or restart.

### Railway

1. Create a new service from the repo. The `Procfile` starts `python main.py`. Railway injects `PORT`.
2. Set the same environment variables as above. Point `DASHBOARD_URL` at the Railway public URL, and add `/callback` in the Developer Portal.
3. Add a volume and set `DATA_DIR` to the volume mount so SQLite survives redeploys.

A `Dockerfile` is included if you prefer a container build on either host.

### Stripe (paid Premium subscriptions)

Premium is billed **per server**. Plans are **$10 USD / month** and **$100 USD / year** (the yearly plan saves about 17%). Without `STRIPE_SECRET_KEY`, the bot and dashboard still run: the [pricing page](/pricing) shows both plans with “Payments coming soon”, and the bot owner can still grant Premium by hand from `/admin` or `.premium grant`.

To take payments:

1. Create a [Stripe](https://dashboard.stripe.com/) account and copy the **Secret key** (Developers → API keys) into `STRIPE_SECRET_KEY`.
2. Optional: create subscription Prices yourself and set `STRIPE_PRICE_MONTHLY` and `STRIPE_PRICE_YEARLY`. If those are omitted, the bot creates Products/Prices at startup idempotently, using lookup keys `bot_monthly_usd` ($10 / month) and `bot_yearly_usd` ($100 / year).
3. Add a webhook endpoint: `DASHBOARD_URL/stripe/webhook` (for example `https://your-host/stripe/webhook`). Listen for `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, and `invoice.payment_failed`.
4. Copy the webhook **Signing secret** into `STRIPE_WEBHOOK_SECRET`.
5. In Stripe settings, enable the **Customer Portal** so subscribers can manage or cancel from the dashboard Billing panel.
6. Restart the bot once the env vars are set.

`PREMIUM_REQUIRED` defaults to true. Set it to `false` to turn off command gating. The application owner's own servers always stay unlocked, and existing servers the bot is already in receive a lifetime manual grant (`note: initial`) on first start with this feature. Use `/admin` (or `.premium grant <guild_id> [days] [note]`) to grant or revoke Premium without a payment.

### Important: only one running copy

The bot token can only be connected to Discord once. After you deploy to Render or Railway, **stop the copy running on this box** (or any other machine). Two processes with the same token will disconnect each other.

SQLite is fine for a single instance. If you later run more than one replica, you would need a shared database; do not point two hosts at copies of the same file.

