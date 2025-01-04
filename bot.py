import discord
from discord import ButtonStyle, TextStyle
from discord.ui import Button, View, Modal, TextInput
import requests
import asyncio
import os
import logging
from datetime import datetime, timedelta
from discord.ext import tasks
from dotenv import load_dotenv
import sys
import pytz
from typing import Optional
import aiohttp
import json

# Near the top of the file, add color codes
class Colors:
    HEADER = '\033[95m'    # Pink/Purple
    INFO = '\033[94m'      # Blue
    SUCCESS = '\033[92m'   # Green
    WARNING = '\033[93m'   # Yellow
    ERROR = '\033[91m'     # Red
    CYAN = '\033[96m'      # Cyan
    GRAY = '\033[90m'      # Gray
    ENDC = '\033[0m'       # Reset color
    BOLD = '\033[1m'       # Bold
    UNDERLINE = '\033[4m'  # Underline

# Create a custom formatter
class CustomFormatter(logging.Formatter):
    # Format strings for different log levels
    FORMATS = {
        logging.DEBUG: Colors.GRAY + '[{asctime}] [🔍 DEBUG] {message}' + Colors.ENDC,
        logging.INFO: Colors.CYAN + '[{asctime}] [ℹ️ INFO] {message}' + Colors.ENDC,
        logging.WARNING: Colors.WARNING + '[{asctime}] [⚠️ WARNING] {message}' + Colors.ENDC,
        logging.ERROR: Colors.ERROR + '[{asctime}] [❌ ERROR] {message}' + Colors.ENDC,
        logging.CRITICAL: Colors.ERROR + Colors.BOLD + '[{asctime}] [☠️ CRITICAL] {message}' + Colors.ENDC
    }

    def format(self, record):
        # Add color to specific keywords in the message
        if 'success' in record.msg.lower():
            record.msg = Colors.SUCCESS + record.msg + Colors.ENDC
        elif 'failed' in record.msg.lower():
            record.msg = Colors.ERROR + record.msg + Colors.ENDC
        elif 'ban' in record.msg.lower():
            record.msg = Colors.CYAN + record.msg + Colors.ENDC

        # Get the base format for this log level
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, style='{', datefmt='%Y-%m-%d %H:%M:%S')
        
        return formatter.format(record)

# Set up logging
def setup_logger():
    logger = logging.getLogger('BanBot')
    logger.setLevel(logging.INFO)
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CustomFormatter())
    
    # File handler without colors (plain text)
    file_handler = logging.FileHandler('banbot.log', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '[{asctime}] [{levelname}] {message}',
        style='{',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    # Disable other loggers
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
    logging.getLogger('discord.gateway').setLevel(logging.WARNING)
    
    return logger

# Create logger instance
logger = setup_logger()

# Load environment variables
load_dotenv()

# Constants
BATTLEMETRICS_API_KEY = os.getenv('BATTLEMETRICS_API_KEY')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
BATTLEMETRICS_ORG_ID = os.getenv('BATTLEMETRICS_ORG_ID')
BATTLEMETRICS_BANLIST_ID = os.getenv('BATTLEMETRICS_BANLIST_ID')
ADMIN_MAPPINGS = json.loads(os.getenv('ADMIN_MAPPINGS', '{}'))

class BanEmbed:
    @staticmethod
    def create_ban_embed(ban_data: dict) -> discord.Embed:
        try:
            # Extract data from ban_data
            attributes = ban_data.get('attributes', {})
            relationships = ban_data.get('relationships', {})
            included = ban_data.get('included', [])
            ban_id = ban_data.get('id', 'unknown')  # Get the ban ID
            
            # Create embed
            embed = discord.Embed(
                title="NEW BAN REPORT",
                color=0x2B2D31
            )
            
            # Set author with ban ID in URL
            embed.set_author(
                name="BattleMetrics Ban",
                icon_url="https://www.battlemetrics.com/favicon.ico",
                url=f"https://www.battlemetrics.com/rcon/bans/edit/{ban_id}"
            )
            
            # Get player info
            player_name = 'Unknown'
            if 'player' in relationships:
                player_id = relationships['player'].get('data', {}).get('id')
                if player_id:
                    for inc in included:
                        if inc.get('type') == 'player' and inc.get('id') == player_id:
                            player_name = inc.get('attributes', {}).get('name', 'Unknown')
                            break

            # Get Steam ID
            steam_id = 'Unknown'
            for identifier in attributes.get('identifiers', []):
                if identifier.get('type') == 'steamID':
                    steam_id = identifier.get('identifier', 'Unknown')
                    break

            # Get server info
            server_name = 'Unknown'
            if 'server' in relationships:
                server_id = relationships['server'].get('data', {}).get('id')
                if server_id:
                    for inc in included:
                        if inc.get('type') == 'server' and inc.get('id') == server_id:
                            server_name = inc.get('attributes', {}).get('name', 'Unknown')
                            break

            # Format fields
            embed.add_field(
                name="Offenders Name:",
                value=player_name,
                inline=True
            )
            embed.add_field(
                name="Offenders SteamID:",
                value=steam_id,
                inline=True
            )

            # Add Steam Profile link if available
            steam_profile = f"https://steamcommunity.com/profiles/{steam_id}"
            embed.add_field(
                name="Offenders Steam Profile:",
                value=f"[Click Here]({steam_profile})",
                inline=False
            )

            # Add BattleMetrics Profile link if available
            if 'player' in relationships:
                player_id = relationships['player'].get('data', {}).get('id')
                if player_id:
                    battlemetrics_profile = f"https://www.battlemetrics.com/players/{player_id}"
                    embed.add_field(
                        name="Offenders BattleMetrics Profile:",
                        value=f"[Click Here]({battlemetrics_profile})",
                        inline=False
                    )

            embed.add_field(
                name="Server:",
                value=server_name,
                inline=False
            )

            # Add reason
            reason = attributes.get('reason', 'No reason provided')
            embed.add_field(
                name="Reason:",
                value=reason,
                inline=False
            )

            # Add expiration
            expires = attributes.get('expires')
            if expires:
                try:
                    expire_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                    expiry = expire_dt.strftime("%B %d, %Y %I:%M %p")
                    relative = f"(in {(expire_dt - datetime.now(pytz.UTC)).days} days)"
                    expires_text = f"{expiry}\n{relative}"
                except (ValueError, AttributeError):
                    expires_text = "Invalid date"
            else:
                expires_text = "Permanent"

            embed.add_field(
                name="Expires:",
                value=expires_text,
                inline=True
            )

            # Add banned by
            banner = 'Unknown'
            # Get admin from user relationship
            if 'user' in relationships:
                user_id = relationships['user'].get('data', {}).get('id')
                if user_id:
                    for inc in included:
                        if inc.get('type') == 'user' and inc.get('id') == user_id:
                            banner = inc.get('attributes', {}).get('nickname', 'Unknown')
                            break
            
            banner_id = ADMIN_MAPPINGS.get(banner)
            banner_text = f"{banner} (<@{banner_id}>)" if banner_id else banner
            
            # Debug log
            logger.info(f"[BanEmbed] User relationship: {relationships.get('user')}")
            logger.info(f"[BanEmbed] Banner: {banner}, Banner ID: {banner_id}")

            embed.add_field(
                name="Banned by:",
                value=banner_text,
                inline=True
            )

            # Add evidence
            embed.add_field(
                name="Evidence:",
                value="[Link1](https://example.com)",
                inline=False
            )

            # Add brief explanation
            embed.add_field(
                name="Brief explanation of what happened:",
                value=attributes.get('note', 'No additional notes'),
                inline=False
            )

            # Set footer
            embed.set_footer(text="Controls below are for staff members only.")

            # Set thumbnail (you can customize this)
            embed.set_thumbnail(url="https://www.battlemetrics.com/favicon.ico")

            # Add this before creating the embed field
            logger.info(f"Admin data from API: {attributes.get('admin')}")

            return embed
            
        except Exception as e:
            logger.error(f"Error creating ban embed: {str(e)}", exc_info=True)
            raise

class EvidenceModal(Modal):
    def __init__(self):
        super().__init__(title="Add Evidence Link")
        
        # Add text input for evidence link
        self.evidence_link = TextInput(
            label="Evidence Link",
            placeholder="Paste your evidence link here...",
            style=TextStyle.short,
            required=True,
            min_length=5,
            max_length=200
        )
        self.add_item(self.evidence_link)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Get the original message
            message = interaction.message
            
            # Get the current embed
            embed = message.embeds[0]
            
            # Find the Evidence field
            for i, field in enumerate(embed.fields):
                if field.name == "Evidence:":
                    # Update the evidence field with the new link
                    current_value = field.value
                    if current_value == "[Link1](https://example.com)":
                        # If it's the default value, replace it
                        new_value = f"[Link1]({self.evidence_link.value})"
                    else:
                        # Add new link to existing ones
                        link_number = len(current_value.split('\n')) + 1
                        new_value = f"{current_value}\n[Link{link_number}]({self.evidence_link.value})"
                    
                    embed.set_field_at(i, name="Evidence:", value=new_value, inline=False)
                    break
            
            # Update the message with the new embed
            await message.edit(embed=embed)
            
            # Send confirmation
            await interaction.response.send_message("Evidence link added successfully!", ephemeral=True)
            
        except Exception as e:
            error_msg = f"Please Report this to Puvify: {str(e)}"
            logger.error(f"Error adding evidence: {str(e)}", exc_info=True)
            await interaction.response.send_message(error_msg, ephemeral=True)

class BanView(View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # Add Evidence button
        add_evidence = Button(
            style=ButtonStyle.primary,
            label="Add Evidence",
            custom_id="add_evidence",
            emoji="📎"
        )
        add_evidence.callback = self.add_evidence_callback
        self.add_item(add_evidence)
        
        # Unban button
        unban = Button(
            style=ButtonStyle.success,
            label="Unban",
            custom_id="unban",
            emoji="🔓"
        )
        unban.callback = self.unban_callback
        self.add_item(unban)
        
        # Refresh button
        refresh = Button(
            style=ButtonStyle.secondary,
            label="Refresh",
            custom_id="refresh",
            emoji="🔄"
        )
        refresh.callback = self.refresh_callback
        self.add_item(refresh)

    async def add_evidence_callback(self, interaction: discord.Interaction):
        modal = EvidenceModal()
        await interaction.response.send_modal(modal)

    async def unban_callback(self, interaction: discord.Interaction):
        confirm_view = UnbanConfirmView(self)
        await interaction.response.send_message(
            "Are you sure you want to remove this ban?",
            view=confirm_view,
            ephemeral=True
        )

    async def process_unban(self, interaction: discord.Interaction):
        try:
            # Get the original message and its embed
            if not interaction.message.reference:
                await interaction.response.send_message(
                    "Please Report this to Puvify: Could not find the original ban message.",
                    ephemeral=True
                )
                return

            # Get the original ban message
            original_message = await interaction.channel.fetch_message(
                interaction.message.reference.message_id
            )

            if not original_message.embeds:
                await interaction.response.send_message(
                    "Please Report this to Puvify: Original message has no embed.",
                    ephemeral=True
                )
                return

            # Get the ban ID from the embed URL
            embed = original_message.embeds[0]
            if not embed.author or not embed.author.url:
                await interaction.response.send_message(
                    "Please Report this to Puvify: Could not find ban information in the embed.",
                    ephemeral=True
                )
                return
                
            ban_id = embed.author.url.split('/')[-1]
            
            # Prepare the API request
            headers = {
                'Authorization': f'Bearer {BATTLEMETRICS_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            # Get current time and add 5 seconds
            current_time = datetime.now(pytz.UTC)
            expires_time = current_time + timedelta(seconds=5)
            
            # Set ban to expire in 5 seconds
            data = {
                "data": {
                    "type": "ban",
                    "id": ban_id,
                    "attributes": {
                        "expires": expires_time.isoformat()
                    }
                }
            }
            
            # Make the PATCH request to update the ban
            response = requests.patch(
                f'https://api.battlemetrics.com/bans/{ban_id}',
                headers=headers,
                json=data
            )
            
            # Check for both 200 and 204 status codes as success
            if response.status_code in [200, 204]:
                # Update the embed to show the ban is unbanned
                for field in embed.fields:
                    if field.name == "Expires:":
                        embed.set_field_at(
                            embed.fields.index(field),
                            name="Expires:",
                            value="Unbanned",
                            inline=True
                        )
                        break
                
                # Get the original message and update it
                original_message = await interaction.channel.fetch_message(interaction.message.reference.message_id)
                await original_message.edit(embed=embed)
                
                # Send confirmation
                await interaction.response.send_message(
                    "✅ Ban has been removed!",
                    ephemeral=True
                )
                
                # Log the unban
                logger.info(f"Ban {ban_id} has been removed by {interaction.user}")
                
            else:
                error_msg = f"Failed to update ban duration. Status code: {response.status_code}"
                if response.text:
                    try:
                        error_data = response.json()
                        error_msg += f"\nError: {error_data}"
                    except:
                        error_msg += f"\nResponse: {response.text}"
                
                logger.error(error_msg)
                await interaction.response.send_message(
                    f"Please Report this to Puvify: {error_msg}",
                    ephemeral=True
                )
                
        except Exception as e:
            error_msg = f"Please Report this to Puvify: {str(e)}"
            logger.error(f"Error in process_unban: {str(e)}", exc_info=True)
            await interaction.response.send_message(error_msg, ephemeral=True)

    async def refresh_callback(self, interaction: discord.Interaction):
        try:
            # Get ban ID from embed URL
            embed = interaction.message.embeds[0]
            if not embed.author or not embed.author.url:
                await interaction.response.send_message(
                    "Could not find ban information in the embed.",
                    ephemeral=True
                )
                return
            
            ban_id = embed.author.url.split('/')[-1]
            
            # Fetch latest ban data
            headers = {
                'Authorization': f'Bearer {BATTLEMETRICS_API_KEY}',
                'Accept': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f'https://api.battlemetrics.com/bans/{ban_id}',
                    headers=headers,
                    params={'include': 'server,player,banList,user'}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        ban = data['data']
                        attributes = ban.get('attributes', {})
                        
                        # Update expiration field
                        expires = attributes.get('expires')
                        if expires:
                            try:
                                expire_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                                expiry = expire_dt.strftime("%B %d, %Y %I:%M %p")
                                relative = f"(in {(expire_dt - datetime.now(pytz.UTC)).days} days)"
                                expires_text = f"{expiry}\n{relative}"
                            except (ValueError, AttributeError):
                                expires_text = "Invalid date"
                        else:
                            expires_text = "Permanent"
                            
                        # Update the fields
                        for field in embed.fields:
                            if field.name == "Expires:":
                                embed.set_field_at(
                                    embed.fields.index(field),
                                    name="Expires:",
                                    value=expires_text,
                                    inline=True
                                )
                                break
                        
                        # Update the message with refreshed embed
                        await interaction.message.edit(embed=embed)
                        await interaction.response.send_message(
                            "✅ Ban information refreshed!",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"Failed to refresh ban information. Status code: {response.status}",
                            ephemeral=True
                        )
                        
        except Exception as e:
            logger.error(f"Error in refresh_callback: {e}")
            await interaction.response.send_message(
                f"Please Report this to Puvify: Error refreshing ban information - {str(e)}",
                ephemeral=True
            )

class UnbanConfirmView(View):
    def __init__(self, original_view: BanView):
        super().__init__(timeout=60)
        self.original_view = original_view

    @discord.ui.button(label="Confirm Unban", style=ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        await self.original_view.process_unban(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Unban cancelled.", ephemeral=True)
        self.stop()

class BanBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        super().__init__(
            intents=intents,
            reconnect=True,  # Enable auto-reconnect
            heartbeat_timeout=150.0,  # Increase heartbeat timeout
            guild_ready_timeout=5.0  # Reduce guild ready timeout
        )
        self.last_ban_id = None
        self.start_timestamp = datetime.now(pytz.UTC)
        self.tree = discord.app_commands.CommandTree(self)
        self.is_first_ready = True  # Track first ready event

    async def setup_hook(self):
        try:
            self.check_bans.start()
            await self.tree.sync()
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
            
    async def on_ready(self):
        try:
            logger.info(f'Bot logged in as {self.user}')
            
            if self.is_first_ready:
                channel = self.get_channel(DISCORD_CHANNEL_ID)
                if channel:
                    try:
                        await channel.send("🟢 BattleMetrics Ban Bot is now online!")
                        self.is_first_ready = False
                    except Exception as e:
                        logger.error(f"Failed to send startup message: {e}")
        except Exception as e:
            logger.error(f"Error in on_ready: {e}")

    async def on_disconnect(self):
        logger.warning("Bot disconnected from Discord")

    async def on_resume(self):
        logger.info("Bot resumed connection to Discord")

    async def on_error(self, event, *args, **kwargs):
        logger.error(f"Error in event {event}", exc_info=True)

    @tasks.loop(seconds=5)
    async def check_bans(self):
        try:
            # Add rate limiting
            await asyncio.sleep(1)  # Prevent hitting rate limits
            
            headers = {
                'Authorization': f'Bearer {BATTLEMETRICS_API_KEY}',
                'Accept': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://api.battlemetrics.com/bans',
                    headers=headers,
                    params={
                        'include': 'server,player,banList,user',
                        'sort': '-timestamp',
                        'filter[expired]': 'false',
                        'filter[organization]': BATTLEMETRICS_ORG_ID,
                        'filter[banList]': BATTLEMETRICS_BANLIST_ID,
                        'page[size]': 1
                    },
                    timeout=aiohttp.ClientTimeout(total=10)  # 10 second timeout
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('data'):
                            ban = data['data'][0]  # Get most recent ban
                            
                            # Check if this is a new ban and after bot start time
                            ban_timestamp = datetime.fromisoformat(
                                ban['attributes'].get('timestamp', '').replace('Z', '+00:00')
                            )
                            
                            if (self.last_ban_id != ban.get('id') and 
                                ban_timestamp > self.start_timestamp):
                                ban['included'] = data.get('included', [])
                                
                                channel = self.get_channel(DISCORD_CHANNEL_ID)
                                if channel:
                                    embed = BanEmbed.create_ban_embed(ban)
                                    view = BanView()
                                    ban_message = await channel.send(embed=embed, view=view)
                                    
                                    # Create thread for this ban
                                    try:
                                        # Get player name from included data
                                        player_name = 'Unknown'
                                        if 'player' in ban.get('relationships', {}):
                                            player_id = ban['relationships']['player'].get('data', {}).get('id')
                                            if player_id:
                                                for inc in ban.get('included', []):
                                                    if inc.get('type') == 'player' and inc.get('id') == player_id:
                                                        player_name = inc.get('attributes', {}).get('name', 'Unknown')
                                                        break
                                        
                                        thread = await ban_message.create_thread(
                                            name=f"Ban Discussion - {player_name}",
                                            auto_archive_duration=1440
                                        )
                                        
                                        # Get banner info for mention
                                        banner_name = 'Unknown'
                                        if 'user' in ban.get('relationships', {}):
                                            user_id = ban['relationships']['user'].get('data', {}).get('id')
                                            if user_id:
                                                for inc in ban.get('included', []):
                                                    if inc.get('type') == 'user' and inc.get('id') == user_id:
                                                        banner_name = inc.get('attributes', {}).get('nickname', 'Unknown')
                                                        break
                                        
                                        banner_id = ADMIN_MAPPINGS.get(banner_name)
                                        banner_text = f"{banner_name} (<@{banner_id}>)" if banner_id else banner_name
                                        
                                        mention = f"<@{banner_id}> " if banner_id else ""
                                        
                                        await thread.send(
                                            f"{mention}Please discuss this ban here. If you have any videos or screenshots as evidence, please share them here."
                                        )
                                    except Exception as e:
                                        logger.error(f"Failed to create thread: {e}")
                                    
                                    # Update last ban ID after successful send
                                    self.last_ban_id = ban.get('id')
                                    logger.info(f"New ban processed: {ban.get('id')}")
                            
                    else:
                        logger.error(f"BattleMetrics API error: {response.status}")
                        
        except Exception as e:
            logger.error(f"Ban check error: {e}")
        finally:
            # Ensure we don't spam the API on errors
            await asyncio.sleep(5)

    @check_bans.before_loop
    async def before_check_bans(self):
        await self.wait_until_ready()

    @check_bans.error
    async def check_bans_error(self, error):
        logger.error(f"Ban check task error: {error}")

    async def on_message(self, message):
        try:
            # Log message details, handling DM channels
            channel_name = getattr(message.channel, 'name', 'DM Channel')
            logger.info(f"Message received in {channel_name} ({message.channel.id})")
            logger.info(f"Is thread: {isinstance(message.channel, discord.Thread)}")
            
            # Only delete messages in the main channel, not in threads
            if message.channel.id == DISCORD_CHANNEL_ID and not isinstance(message.channel, discord.Thread):
                # Delete messages that aren't from the bot or don't have embeds
                if not message.author.bot or not message.embeds:
                    try:
                        await message.delete()
                        logger.info(f"Deleted message in main channel")
                    except discord.errors.NotFound:
                        logger.warning("Message was already deleted")
                    except discord.errors.Forbidden:
                        logger.error("Bot lacks permission to delete message")
                    except Exception as e:
                        logger.error(f"Failed to delete message: {e}")
                else:
                    logger.info("Message kept (from bot with embeds)")
        except Exception as e:
            logger.error(f"Error in on_message: {e}", exc_info=True)

def main():
    try:
        # Validate environment variables
        required_vars = {
            'BATTLEMETRICS_API_KEY': BATTLEMETRICS_API_KEY,
            'DISCORD_TOKEN': DISCORD_TOKEN,
            'DISCORD_CHANNEL_ID': DISCORD_CHANNEL_ID,
            'BATTLEMETRICS_ORG_ID': BATTLEMETRICS_ORG_ID,
            'BATTLEMETRICS_BANLIST_ID': BATTLEMETRICS_BANLIST_ID
        }

        for var_name, var_value in required_vars.items():
            if not var_value:
                logger.critical(f"Missing required environment variable: {var_name}")
                sys.exit(1)

        # Validate API key
        try:
            response = requests.get(
                'https://api.battlemetrics.com/bans',
                headers={'Authorization': f'Bearer {BATTLEMETRICS_API_KEY}'},
                params={'page[size]': 1}
            )

            if response.status_code != 200:
                logger.critical(f"Invalid BattleMetrics API key (Status code: {response.status_code})")
                sys.exit(1)

            data = response.json()
            if 'data' not in data:
                logger.critical("API response missing 'data' field")
                sys.exit(1)
                
            logger.info("BattleMetrics API key validated successfully")
            
        except Exception as e:
            logger.critical(f"Failed to validate BattleMetrics API key: {str(e)}")
            sys.exit(1)

        # Initialize and run bot
        client = BanBot()
        logger.info("Starting bot...")
        client.run(DISCORD_TOKEN, log_handler=None)

    except Exception as e:
        logger.critical(f"Fatal error during bot startup: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 