# Discord Mention Bot

A lightweight Discord moderation bot that blocks direct user mentions while allowing controlled role mentions, with per-server configuration, bypass roles, and Docker support.

## Purpose

Mention Policy Bot enforces a simple but powerful rule set inside a Discord server:

Direct user mentions are blocked.
Role mentions are allowed only if explicitly approved.
Specific roles can bypass the restriction entirely.
Short-lived notice messages explain why a message was removed.

This is useful for communities that want to prevent targeted pinging, reduce parasocial pressure, or funnel communication through structured role mentions instead of individuals.

The bot operates per server and stores configuration in a persistent JSON file.

## Features

* Blocks explicit @user mentions
* Allows only whitelisted role mentions
* Supports bypass roles for moderators or trusted members
* Admin-only slash commands for configuration
* Optional ignored channels
* Short-lived public deletion notices
* Docker-friendly configuration with persistent storage

## How It Works

The bot detects explicit user mention tokens in message content such as <@123456789> and deletes those messages unless the author has a bypass role or administrative permissions.

Role mentions are allowed only if the role ID is in the allowlist.

Replies are handled carefully so normal reply behavior does not cause false positives unless an actual user mention token is present.

Configuration is stored per guild in config.json.

## Creating the Bot in Discord Developer Portal

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Click New Application
3. Give it a name and create it
4. Go to the Bot section
5. Click Add Bot
6. Under Token, click Reset Token and copy the token
7. Under Privileged Gateway Intents, enable Message Content Intent
8. Save changes

## Inviting the Bot to Your Server

1. In the Developer Portal, go to OAuth2 then URL Generator
2. Select the following scopes:

   * bot
   * applications.commands
3. In Bot Permissions, select Administrator
4. Copy the generated URL
5. Open it in your browser and invite the bot to your server

Administrator permission is recommended so the bot can reliably delete messages across channels.

Local Setup Without Docker

## Requirements:

* Python 3.10 or newer
* pip

1. Clone the repository

2. Create a virtual environment if desired

3. Install dependencies:

   pip install -r requirements.txt

4. Create a .env file in the project root:

   DISCORD_TOKEN=your_bot_token_here

5. Run the bot:

   python mention_policy_bot.py

## Docker Setup

This project is designed to run cleanly in Docker with persistent configuration.

Folder structure example:

/DATA/AppData/Mention_Bot
mention_policy_bot.py
Dockerfile
docker-compose.yml
requirements.txt
.env

Example docker-compose.yml:

services:
mention-bot:
build: .
container_name: mention-bot
restart: unless-stopped
env_file:
- .env
environment:
- TZ=America/Chicago
- MENTION_BOT_CONFIG=/data/config.json
volumes:
- /DATA/AppData/Mention_Bot:/data
- /DATA/AppData/Mention_Bot/mention_policy_bot.py:/app/mention_policy_bot.py:ro

## Build and run:

docker compose up -d --build

The config file will be created automatically at /data/config.json and will persist across restarts.

## Configuration Commands

All configuration is done through slash commands and requires Administrator or Manage Server permission.

### Show current configuration:

/config_show

### Allow anyone to mention a role:

/mentionrole_add @RoleName

### Remove a role from the allowlist:

/mentionrole_remove @RoleName

### Add a bypass role:

/bypassrole_add @RoleName

### Remove a bypass role:

/bypassrole_remove @RoleName

### Set how long deletion notices remain visible:

/notice_ttl_set 10

### Add a channel to ignore enforcement:

/ignored_channel_add #channel

### Remove a channel from ignore list:

/ignored_channel_remove #channel

## Behavior Notes

* Roles must also be mentionable at the Discord role level if you want users to see them in autocomplete.
* The bot enforces policy after message submission, so Discord’s own role permissions still apply.
* Administrators bypass restrictions by default.
* Only explicit user mentions are blocked. Plain text like @username without selecting the mention does not trigger enforcement.

License

Apache-2.0 license
