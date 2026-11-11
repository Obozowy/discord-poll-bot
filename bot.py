import os
import asyncio
from datetime import datetime
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

TOKEN = os.getenv("DISCORD_TOKEN")

ALLOWED_ROLES = ["Zawodnik", "EU Plejer", "Testy"]
DAYS_CONFIG = {
    "poniedziałek": 0,
    "wtorek": 1,
    "środa": 2,
    "czwartek": 3,
    "piątek": 4,
    "sobota": 5,
    "niedziela": 6,
}

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

class PollView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.yes_users = set()
        self.no_users = set()

    def check_role(self, interaction: discord.Interaction) -> bool:
        user_roles = [r.name.lower() for r in interaction.user.roles]
        allowed_roles_lower = [role.lower() for role in ALLOWED_ROLES]
        return any(role in user_roles for role in allowed_roles_lower)

    def format_users_by_role(self, users_set):
        if not users_set:
            return "Brak"
        
        grouped = {role: [] for role in ALLOWED_ROLES}
        others = []

        for user in users_set:
            user_role_names = [r.name for r in user.roles]
            assigned = False
            for target_role in ALLOWED_ROLES:
                if any(target_role.lower() == r.lower() for r in user_role_names):
                    grouped[target_role].append(user.mention)
                    assigned = True
                    break
            if not assigned:
                others.append(user.mention)

        lines = []
        for role_name, mentions in grouped.items():
            if mentions:
                lines.append(f"**{role_name}:** " + ", ".join(mentions))
        if others:
            lines.append(f"**Inni:** " + ", ".join(others))

        return "\n".join(lines) if lines else "Brak"

    def generate_embed(self, title: str):
        embed = discord.Embed(title=f"📋 Ankieta: {title}", color=discord.Color.blue())
        
        yes_content = self.format_users_by_role(self.yes_users)
        no_content = self.format_users_by_role(self.no_users)
        
        embed.add_field(name=f"✅ Obecni ({len(self.yes_users)})", value=yes_content, inline=False)
        embed.add_field(name=f"❌ Nieobecni ({len(self.no_users)})", value=no_content, inline=False)
        return embed

    @discord.ui.button(label="Tak", style=discord.ButtonStyle.green, custom_id="poll_yes")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check_role(interaction):
            await interaction.response.send_message("Nie masz odpowiedniej rangi do głosowania!", ephemeral=True)
            return

        self.no_users.discard(interaction.user)
        self.yes_users.add(interaction.user)
        
        embed = self.generate_embed(interaction.message.embeds[0].title.replace("📋 Ankieta: ", ""))
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Nie", style=discord.ButtonStyle.red, custom_id="poll_no")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check_role(interaction):
            await interaction.response.send_message("Nie masz odpowiedniej rangi do głosowania!", ephemeral=True)
            return

        self.yes_users.discard(interaction.user)
        self.no_users.add(interaction.user)
        
        embed = self.generate_embed(interaction.message.embeds[0].title.replace("📋 Ankieta: ", ""))
        await interaction.response.edit_message(embed=embed, view=self)

async def create_weekly_polls():
    tz = pytz.timezone("Europe/Warsaw")
    now = datetime.now(tz)
    
    # Bezpośrednia, awaryjna metoda wyciągania dzisiejszej daty jako test
    date_str = now.strftime("%d.%m.%Y")

    for guild in bot.guilds:
        for channel in guild.text_channels:
            channel_name = channel.name.lower().strip()
            if channel_name in DAYS_CONFIG:
                try:
                    try:
                        await channel.purge(limit=5)
                    except Exception:
                        pass
                    
                    await asyncio.sleep(1)
                    
                    capitalized_day = channel_name.capitalize()
                    # Hardcoded data testowa z current_time żeby sprawdzić czy string w ogóle przechodzi do embeda
                    title = f"{capitalized_day} ({date_str}) - Zbiórka 19:50"
                    
                    view = PollView()
                    embed = view.generate_embed(title)
                    
                    role_mentions = []
                    for role_name in ALLOWED_ROLES:
                        role_insensitive = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), guild.roles)
                        if role_insensitive:
                            role_mentions.append(role_insensitive.mention)
                    
                    ping_text = " ".join(role_mentions) if role_mentions else ""
                    content = f"📢 **Nowa ankieta!** {ping_text}" if ping_text else "📢 **Nowa ankieta!**"

                    await channel.send(content=content, embed=embed, view=view)
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"Błąd na kanale {channel.name}: {e}")

@bot.tree.command(name="ankiety", description="Tworzy nowe ankiety z podziałem na rangi i datami")
async def ankiety(interaction: discord.Interaction):
    await interaction.response.send_message("Tworzę nowe ankiety z aktualnymi datami...", ephemeral=True)
    await create_weekly_polls()

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Zsynchronizowano globalnie pomyślnie {len(synced)} komend(y).")
    except Exception as e:
        print(f"Błąd synchronizacji: {e}")
        
    print(f"Zalogowano pomyślnie jako {bot.user}")
    
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Warsaw"))
    scheduler.add_job(create_weekly_polls, 'cron', day_of_week='sun', hour=0, minute=0)
    scheduler.start()

bot.run(TOKEN)
