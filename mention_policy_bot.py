import os
import json
import asyncio
import re
from typing import Dict, Any, Set, Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN. Put it in a .env file or environment variable.")

# Always use an absolute config path in Docker.
# Default: /data/config.json (matches your bind mount /DATA/AppData/Mention_Bot -> /data)
CONFIG_FILE = os.getenv("MENTION_BOT_CONFIG", "/data/config.json")

# Match ONLY explicit user mention tokens that actually ping:
# <@123> or <@!123>
# (Role mentions are <@&123> and will not match this regex.)
USER_MENTION_RE = re.compile(r"<@!?\d+>")


def _default_guild_config() -> Dict[str, Any]:
    return {
        "mentionable_role_ids": [],  # roles anyone can mention
        "bypass_role_ids": [],       # roles that bypass mention restrictions
        "notice_ttl_seconds": 10,    # seconds before notice auto-deletes
        "ignored_channel_ids": [],   # channels to ignore enforcement
    }


class ConfigStore:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {"guilds": {}}

    def load(self) -> None:
        # Ensure directory exists
        cfg_dir = os.path.dirname(self.path) or "."
        os.makedirs(cfg_dir, exist_ok=True)

        if not os.path.exists(self.path):
            self.data = {"guilds": {}}
            self.save()
            return

        with open(self.path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        if "guilds" not in self.data or not isinstance(self.data["guilds"], dict):
            self.data["guilds"] = {}
            self.save()

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def get_guild(self, guild_id: int) -> Dict[str, Any]:
        gid = str(guild_id)
        if gid not in self.data["guilds"]:
            self.data["guilds"][gid] = _default_guild_config()
            self.save()
        return self.data["guilds"][gid]

    def set_guild(self, guild_id: int, new_cfg: Dict[str, Any]) -> None:
        self.data["guilds"][str(guild_id)] = new_cfg
        self.save()


intents = discord.Intents.default()
intents.message_content = True  # Required to read message content and detect mention tokens

bot = commands.Bot(command_prefix="!", intents=intents)
store = ConfigStore(CONFIG_FILE)


def is_adminish(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild


def member_has_any_role(member: discord.Member, role_ids: Set[int]) -> bool:
    return any(r.id in role_ids for r in member.roles)


async def send_temporary_notice(
    channel: discord.abc.Messageable,
    content: str,
    ttl_seconds: int,
) -> None:
    """Public notice that auto-deletes (closest thing to ephemeral for non-interaction messages)."""
    try:
        msg = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        return

    if ttl_seconds <= 0:
        return

    async def _cleanup():
        await asyncio.sleep(ttl_seconds)
        try:
            await msg.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

    asyncio.create_task(_cleanup())


def summarize_config(guild: discord.Guild, cfg: Dict[str, Any]) -> str:
    mentionable = []
    for rid in cfg.get("mentionable_role_ids", []):
        role = guild.get_role(rid)
        mentionable.append(role.mention if role else f"`{rid}`")

    bypass = []
    for rid in cfg.get("bypass_role_ids", []):
        role = guild.get_role(rid)
        bypass.append(role.mention if role else f"`{rid}`")

    ignored = [f"`{cid}`" for cid in cfg.get("ignored_channel_ids", [])]

    return (
        f"**Mention Policy Config**\n"
        f"- Anyone-can-mention roles: {', '.join(mentionable) if mentionable else '*(none)*'}\n"
        f"- Bypass roles: {', '.join(bypass) if bypass else '*(none)*'}\n"
        f"- Notice TTL: `{cfg.get('notice_ttl_seconds', 10)}` seconds\n"
        f"- Ignored channels: {', '.join(ignored) if ignored else '*(none)*'}\n"
        f"- Config file: `{store.path}`"
    )


@bot.event
async def on_ready():
    # Sync slash commands (global). May take a bit to propagate sometimes.
    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Command sync failed: {e}")

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Config file path: {store.path}")
    print(f"Loaded guild configs: {len(store.data.get('guilds', {}))}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore bots and DMs
    if message.author.bot or not message.guild:
        return

    cfg = store.get_guild(message.guild.id)

    ignored_channels = set(cfg.get("ignored_channel_ids", []))
    if message.channel.id in ignored_channels:
        return

    # Only enforce for normal members
    if not isinstance(message.author, discord.Member):
        return

    bypass_role_ids = set(cfg.get("bypass_role_ids", []))
    mentionable_role_ids = set(cfg.get("mentionable_role_ids", []))
    notice_ttl = int(cfg.get("notice_ttl_seconds", 10))

    # Admin-ish users bypass by default (per your earlier requirements)
    author_is_bypassed = member_has_any_role(message.author, bypass_role_ids) or is_adminish(message.author)

    # IMPORTANT: Only explicit user mentions in message content.
    # This prevents replies from being treated as mentions unless they truly ping.
    has_explicit_user_mentions = USER_MENTION_RE.search(message.content) is not None

    # Role mentions are explicit and safe to check via role_mentions.
    mentioned_roles = set(message.role_mentions)

    reasons = []

    if has_explicit_user_mentions and not author_is_bypassed:
        reasons.append("Direct `@user` mentions are not allowed here. Use `@role` mentions instead.")

    if mentioned_roles and not author_is_bypassed:
        not_allowed = [r for r in mentioned_roles if r.id not in mentionable_role_ids]
        if not_allowed:
            role_names = ", ".join(f"`@{r.name}`" for r in not_allowed)
            reasons.append(f"Those role mentions are not allowed: {role_names}. Please use approved `@role`s.")

    if reasons:
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return

        notice = f"{message.author.mention} Message deleted: " + " ".join(reasons)
        await send_temporary_notice(message.channel, notice, notice_ttl)
        return

    await bot.process_commands(message)


# -------------------------
# Slash Commands (Admin-only)
# -------------------------

def _ensure_admin(interaction: discord.Interaction) -> Optional[discord.Member]:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return None
    if not is_adminish(interaction.user):
        return None
    return interaction.user


@bot.tree.command(name="config_show", description="Show the mention policy config for this server.")
async def config_show(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    await interaction.response.send_message(summarize_config(interaction.guild, cfg), ephemeral=True)


@bot.tree.command(name="mentionrole_add", description="Allow anyone to mention this role (whitelist).")
@app_commands.describe(role="Role that anyone may mention")
async def mentionrole_add(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    ids = set(cfg.get("mentionable_role_ids", []))
    ids.add(role.id)
    cfg["mentionable_role_ids"] = sorted(ids)
    store.set_guild(interaction.guild.id, cfg)

    await interaction.response.send_message(f"Added {role.mention} to anyone-can-mention whitelist.", ephemeral=True)


@bot.tree.command(name="mentionrole_remove", description="Remove a role from the anyone-can-mention whitelist.")
@app_commands.describe(role="Role to remove")
async def mentionrole_remove(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    ids = set(cfg.get("mentionable_role_ids", []))
    ids.discard(role.id)
    cfg["mentionable_role_ids"] = sorted(ids)
    store.set_guild(interaction.guild.id, cfg)

    await interaction.response.send_message(f"Removed {role.mention} from whitelist.", ephemeral=True)


@bot.tree.command(name="bypassrole_add", description="Allow members with this role to bypass mention restrictions.")
@app_commands.describe(role="Role whose members may @user mention and mention any roles")
async def bypassrole_add(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    ids = set(cfg.get("bypass_role_ids", []))
    ids.add(role.id)
    cfg["bypass_role_ids"] = sorted(ids)
    store.set_guild(interaction.guild.id, cfg)

    await interaction.response.send_message(f"Added {role.mention} as a bypass role.", ephemeral=True)


@bot.tree.command(name="bypassrole_remove", description="Remove a role from bypass list.")
@app_commands.describe(role="Role to remove from bypass")
async def bypassrole_remove(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    ids = set(cfg.get("bypass_role_ids", []))
    ids.discard(role.id)
    cfg["bypass_role_ids"] = sorted(ids)
    store.set_guild(interaction.guild.id, cfg)

    await interaction.response.send_message(f"Removed {role.mention} from bypass roles.", ephemeral=True)


@bot.tree.command(name="notice_ttl_set", description="Set how long the bot's deletion notice stays visible (seconds).")
@app_commands.describe(seconds="Seconds before the notice is deleted (0 disables notices)")
async def notice_ttl_set(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 120]):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    cfg["notice_ttl_seconds"] = int(seconds)
    store.set_guild(interaction.guild.id, cfg)

    await interaction.response.send_message(f"Notice TTL set to `{seconds}` seconds.", ephemeral=True)


@bot.tree.command(name="ignored_channel_add", description="Ignore mention enforcement in this channel.")
@app_commands.describe(channel="Channel to ignore")
async def ignored_channel_add(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    ids = set(cfg.get("ignored_channel_ids", []))
    ids.add(channel.id)
    cfg["ignored_channel_ids"] = sorted(ids)
    store.set_guild(interaction.guild.id, cfg)

    await interaction.response.send_message(f"Added {channel.mention} to ignored channels.", ephemeral=True)


@bot.tree.command(name="ignored_channel_remove", description="Stop ignoring mention enforcement in this channel.")
@app_commands.describe(channel="Channel to un-ignore")
async def ignored_channel_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
    if not is_adminish(interaction.user):
        return await interaction.response.send_message("Admins only.", ephemeral=True)

    cfg = store.get_guild(interaction.guild.id)
    ids = set(cfg.get("ignored_channel_ids", []))
    ids.discard(channel.id)
    cfg["ignored_channel_ids"] = sorted(ids)
    store.set_guild(interaction.guild.id, cfg)

    await interaction.response.send_message(f"Removed {channel.mention} from ignored channels.", ephemeral=True)


@bot.tree.command(name="invite", description="Generate an invite link for this bot with Administrator permissions.")
async def invite(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Use this in a server.", ephemeral=True)

    app_id = bot.user.id if bot.user else None
    if not app_id:
        return await interaction.response.send_message("Bot not ready yet.", ephemeral=True)

    url = (
        f"https://discord.com/api/oauth2/authorize?"
        f"client_id={app_id}&permissions=8&scope=bot%20applications.commands"
    )
    await interaction.response.send_message(f"Invite link (Administrator):\n{url}", ephemeral=True)


if __name__ == "__main__":
    store.load()
    bot.run(TOKEN)