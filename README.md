# laciedc

a discord bot with auto-moderation, a ban appeal system, and manual moderation tools.

## prerequisites

- python 3.10+
- postgresql 14+

## setup

### 1. install dependencies

```bash
git clone <repository-url>
cd laciedc
pip install -r requirements.txt
```

### 2. create a postgresql database

**windows**
```cmd
psql -U postgres
CREATE DATABASE laciedc;
\q
```

**macos**
```bash
brew install postgresql
brew services start postgresql
createdb laciedc
```

**linux (ubuntu/debian)**
```bash
sudo apt install postgresql postgresql-contrib
sudo -u postgres createdb laciedc
```

### 3. configure environment

copy `.env.example` to `.env` and fill in your values:

```env
DISCORD_TOKEN=your_discord_bot_token_here
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=laciedc
```

### 4. get a discord bot token

1. go to https://discord.com/developers/applications
2. create a new application → go to the **bot** tab
3. reset and copy the token
4. enable **message content intent** under privileged gateway intents

### 5. invite the bot

use oauth2 → url generator with the `bot` scope and these permissions:
`manage messages` · `manage channels` · `ban members` · `kick members` · `mute members` · `move members`

### 6. run

```bash
python bot.py
```

tables are created automatically on first run. the bot also watches `cogs/` for file changes and reloads cogs automatically — no restart needed during development.

---

## features

### auto-moderation

detects and acts on: profanity, spam, excessive caps, discord invite links, external links, and mass mentions.

escalation per user:
```
1st warn  →  dm warning
2nd warn  →  5-minute timeout
3rd warn  →  kick
4th warn  →  permanent ban
```

moderators (manage messages permission) are exempt from all filters.

### commands

| command | description |
|---|---|
| `!ping` | check latency |
| `!reload` | reload all cogs (owner only) |
| `!purge <amount> [@user]` | delete messages |
| `!slowmode <seconds>` | set channel slowmode |
| `!lock` | lock current channel |
| `!unlock` | unlock current channel |
| `!warnings [@user]` | view warnings |
| `!clearwarnings @user` | clear all warnings |

### slash commands

| command | description |
|---|---|
| `/config show` | view server settings |
| `/config automod <on/off>` | toggle auto-mod |
| `/config maxwarns <1-10>` | set warn limit |
| `/config warnaction <action>` | set action at max warns |
| `/config filter <type> <on/off>` | toggle a filter |
| `/config threshold <type> <value>` | adjust filter sensitivity |

all `/config` commands require **manage server** permission.

### appeal system

banned users can dm the bot to submit an appeal. moderators review with:

| command | description |
|---|---|
| `!appeals` | list pending appeals |
| `!appeal <id>` | view appeal details |
| `!appeal <id> approve` | unban the user |
| `!appeal <id> deny` | deny the appeal |

---

## project structure

```
laciedc/
├── bot.py
├── colors.py
├── database.py
├── cogs/
│   ├── auto_mod.py
│   ├── appeals.py
│   ├── config.py
│   └── mod_tools.py
└── utils/
    ├── embeds.py
    └── watcher.py
```

---

## troubleshooting

**can't connect to database** — check postgresql is running and `.env` credentials are correct. verify the database exists: `CREATE DATABASE laciedc;`

**missing permissions** — re-invite the bot with the correct permissions. the bot's role must be above all user roles it needs to moderate.

---

## license

gpl v3.0 — see license file for details.