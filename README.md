# LacieDC - Discord Bot

A production-grade Discord bot with auto-moderation, appeal system, and manual moderation tools.

## Prerequisites

- Python 3.10 or higher
- PostgreSQL 14+

## Setup

### 1. Clone and Install Dependencies

```bash
git clone <repository-url>
cd laciedc
pip install -r requirements.txt
```

### 2. Create PostgreSQL Server

#### Windows

**Option A: Interactive Installer**

1. Download PostgreSQL: https://www.postgresql.org/download/windows/
2. Run the installer
3. During setup:
   - Set password for `postgres` user (remember it)
   - Keep default port: `5432`
4. Download and install **pgAdmin 4** (optional but recommended)

**Option B: Command Line**

```cmd
# After installation, open pgAdmin or psql
# psql location: C:\Program Files\PostgreSQL\16\bin\psql.exe

# Login as postgres user
psql -U postgres

# Create user (optional - can use default postgres user)
CREATE USER myuser WITH PASSWORD 'yourpassword';
CREATE DATABASE laciedc OWNER myuser;
GRANT ALL PRIVILEGES ON DATABASE laciedc TO myuser;

\q
```

**Option C: Chocolatey**

```cmd
choco install postgresql -y
# Start service
choco install postgresql16 -y --params="/port:5432"
```

#### macOS

```bash
brew install postgresql
brew services start postgresql
createdb laciedc
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo -u postgres createuser --interactive
sudo -u postgres createdb laciedc
```

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```env
DISCORD_TOKEN=your_discord_bot_token_here
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=laciedc
```

### 4. Get Discord Bot Token

1. Go to https://discord.com/developers/applications
2. Create new application
3. Go to Bot section
4. Reset token and copy it
5. Enable **Message Content Intent** in Bot tab

### 5. Invite Bot to Server

1. Go to OAuth2 → URL Generator
2. Scopes: `bot`
3. Bot Permissions:
   - `Manage Messages`
   - `Manage Channels`
   - `Ban Members`
   - `Kick Members`
   - `Mute Members`
   - `Move Members`
4. Copy generated URL and open it

### 6. Run the Bot

```bash
python bot.py
```

The bot will automatically create database tables on first run.

## Features

### Auto-Moderation

Automatically detects and handles:
- Profanity
- Spam (repeated messages)
- Excessive caps
- Discord invite links
- External links
- Excessive mentions

**Escalation:**
```
1st warn  → Warning
2nd warn  → 5-minute timeout
3rd warn  → 30-minute timeout + kick
4th warn  → Permanent ban
```

### Manual Commands

| Command | Description |
|---------|------------|
| `!ping` | Check bot latency |
| `!purge <amount>` | Delete messages |
| `!purge @user <amount>` | Delete user's messages |
| `!slowmode <seconds>` | Set channel slowmode |
| `!lock` | Lock current channel |
| `!unlock` | Unlock current channel |
| `!warnings @user` | View user's warnings |
| `!clear-warnings @user` | Clear user's warnings |

### Slash Commands

| Command | Description |
|---------|------------|
| `/config` | View server settings |
| `/config auto-mod <on/off>` | Toggle auto-mod |
| `/config max-warns <1-10>` | Set warns before action |
| `/config filter <type> <on/off>` | Toggle specific filter |
| `/config threshold <type> <value>` | Set filter threshold |

### Appeal System

When banned, users can DM the bot to appeal. Moderators use:

| Command | Description |
|---------|------------|
| `!appeals` | List pending appeals |
| `!appeal <id>` | View appeal details |
| `!appeal <id> approve` | Approve appeal |
| `!appeal <id> deny` | Deny appeal |

## Project Structure

```
laciedc/
├── bot.py              # Main entry point
├── colors.py           # Color palette
├── database.py        # PostgreSQL connection
├── cogs/
│   ├── config.py      # Slash command config
│   ├── auto_mod.py   # Auto-moderation
│   ├── mod_tools.py # Manual commands
│   └── appeals.py   # Appeal system
└── utils/
    └── embeds.py    # Embed builder
```

## Troubleshooting

### "Could not connect to the database"

- Ensure PostgreSQL is running
- Check `.env` credentials
- Verify database exists: `CREATE DATABASE laciedc;`

### "Missing Permissions"

- Re-invite bot with correct permissions
- Bot role must be above all user roles

### "ClientException: Already has associated command tree"

- Restart the bot (clear cached tree)

## License

GPL v3.0 - See LICENSE file for details.