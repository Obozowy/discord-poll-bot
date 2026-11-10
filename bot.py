import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

TOKEN = os.getenv("DISCORD_TOKEN")

ALLOWED_ROLES = ["zawodnik", "EU Plejer", "Testy"]
DAYS_CONFIG = {
    "poniedziałek": "Poniedziałek - Zbiórka 19:50",
    "wtorek": "Wtorek - Zbiórka 19:50",
    "środa": "Środa - Zbiórka 19:50",
    "czwartek": "Czwartek - Zbiórka 19:50",
    "piątek": "Piątek - Zbiórka 19:50",
    "sobota": "Sobota - Zbiórka 19:50",
    "niedziela": "Niedziela - Zbiórka 19:50",
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
        user_roles = [r.name for r in interaction.user.roles]
        return any(role in user_roles for role in ALLOWED_ROLES)

    def generate_embed(self, title: str):
        embed = discord.Embed(title=f"📋 Ankieta: {title}", color=discord.Color.blue())
        
        yes_list = "\n".join([u.mention for u in self.yes_users]) if self.yes_users else "Brak"
        no_list = "\n".join([u.mention for u in self.no_users]) if self.no_users else "Brak"
        
        embed.add_field(name=f"✅ Obecni ({len(self.yes_users)})", value=yes_list, inline=False)
        embed.add_field(name=f"❌ Nieobecni ({len(self.no_users)})", value=no_list, inline=False)
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
    for guild in bot.guilds:
        for channel in guild.text_channels:
            channel_name = channel.name.lower()
            if channel_name in DAYS_CONFIG:
                await channel.purge(limit=10)
                title = DAYS_CONFIG[channel_name]
                view = PollView()
                embed = view.generate_embed(title)
                await channel.send(embed=embed, view=view)

# Komenda ręczna: wpisz !ankiety na Discordzie, aby od razu wygenerować ankiety
@bot.command()
async def ankiety(ctx):
    await ctx.send("Tworzę nowe ankiety...")
    await create_weekly_polls()

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Warsaw"))
    scheduler.add_job(create_weekly_polls, 'cron', day_of_week='sun', hour=0, minute=0)
    scheduler.start()

bot.run(TOKEN)