
import os
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz


# =========================
# KONFIGURACJA
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")

ALLOWED_ROLES = [
    "Zawodnik",
    "EU Plejer",
    "Testy",
    "KAPITAN",
    "Asystent"
]

ALLOWED_ROLE_IDS = [
    1327076489048490025,  # KAPITAN
    1470703435589353472,  # Asystent
    1327076272920068177,  # Zawodnik
    1569732469408661675,  # EU Plejer
    1327076329257959445   # Testy
]

DAYS_CONFIG = {
    "poniedziałek": 0,
    "wtorek": 1,
    "środa": 2,
    "czwartek": 3,
    "piątek": 4,
    "sobota": 5,
    "niedziela": 6,
}

TZ = pytz.timezone("Europe/Warsaw")


# =========================
# BOT
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# ANKIETY
# =========================

class PollView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.yes_users = set()
        self.no_users = set()

    # Sprawdzanie uprawnień do głosowania
    def check_role(self, interaction: discord.Interaction) -> bool:

        # Właściciel serwera zawsze może głosować
        if (
            interaction.guild
            and interaction.user.id == interaction.guild.owner_id
        ):
            return True

        # Pobieranie ID rang użytkownika
        user_role_ids = [
            role.id
            for role in interaction.user.roles
        ]

        # Sprawdzanie, czy użytkownik ma jedną z dozwolonych rang
        return any(
            role_id in user_role_ids
            for role_id in ALLOWED_ROLE_IDS
        )

    # Grupowanie użytkowników według rang
    def format_users_by_role(self, users_set):

        if not users_set:
            return "Brak"

        grouped = {
            role: []
            for role in ALLOWED_ROLES
        }

        others = []

        for user in users_set:

            user_role_names = [
                role.name.strip().lower()
                for role in user.roles
            ]

            assigned = False

            for target_role in ALLOWED_ROLES:

                if target_role.strip().lower() in user_role_names:
                    grouped[target_role].append(user.mention)
                    assigned = True
                    break

            if not assigned:
                others.append(user.mention)

        lines = []

        for role_name, mentions in grouped.items():

            if mentions:
                lines.append(
                    f"**{role_name}:** " + ", ".join(mentions)
                )

        if others:
            lines.append(
                "**Inni:** " + ", ".join(others)
            )

        return "\n".join(lines) if lines else "Brak"

    # Tworzenie wyglądu ankiety
    def generate_embed(self, title: str):

        embed = discord.Embed(
            title=f"📋 Ankieta: {title}",
            color=discord.Color.blue()
        )

        yes_content = self.format_users_by_role(
            self.yes_users
        )

        no_content = self.format_users_by_role(
            self.no_users
        )

        embed.add_field(
            name=f"✅ Obecni ({len(self.yes_users)})",
            value=yes_content,
            inline=False
        )

        embed.add_field(
            name=f"❌ Nieobecni ({len(self.no_users)})",
            value=no_content,
            inline=False
        )

        return embed

    # PRZYCISK TAK
    @discord.ui.button(
        label="Tak",
        style=discord.ButtonStyle.green,
        custom_id="poll_yes"
    )
    async def yes_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not self.check_role(interaction):
            await interaction.response.send_message(
                "Nie masz odpowiedniej rangi do głosowania!",
                ephemeral=True
            )
            return

        self.no_users.discard(interaction.user)
        self.yes_users.add(interaction.user)

        title = interaction.message.embeds[0].title.replace(
            "📋 Ankieta: ", ""
        )

        embed = self.generate_embed(title)

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # PRZYCISK NIE
    @discord.ui.button(
        label="Nie",
        style=discord.ButtonStyle.red,
        custom_id="poll_no"
    )
    async def no_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not self.check_role(interaction):
            await interaction.response.send_message(
                "Nie masz odpowiedniej rangi do głosowania!",
                ephemeral=True
            )
            return

        self.yes_users.discard(interaction.user)
        self.no_users.add(interaction.user)

        title = interaction.message.embeds[0].title.replace(
            "📋 Ankieta: ", ""
        )

        embed = self.generate_embed(title)

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


# =========================
# DATY
# =========================

def get_next_date(now, target_weekday):

    days_ahead = (
        target_weekday - now.weekday()
    ) % 7

    return now + timedelta(days=days_ahead)


# =========================
# TWORZENIE ANKIET
# =========================

async def create_weekly_polls():

    now = datetime.now(TZ)

    for guild in bot.guilds:

        for channel in guild.text_channels:

            channel_name = channel.name.lower().strip()

            if channel_name not in DAYS_CONFIG:
                continue

            try:

                target_weekday = DAYS_CONFIG[channel_name]

                poll_date = get_next_date(
                    now,
                    target_weekday
                )

                date_str = poll_date.strftime("%d.%m.%Y")

                capitalized_day = channel_name.capitalize()

                title = (
                    f"{capitalized_day} "
                    f"({date_str}) - Zbiórka 19:50"
                )

                # Usuwanie poprzednich wiadomości
                try:
                    await channel.purge(limit=5)

                except discord.Forbidden:
                    print(
                        f"Brak uprawnień do czyszczenia: "
                        f"{channel.name}"
                    )

                await asyncio.sleep(1)

                view = PollView()
                embed = view.generate_embed(title)

                # Oznaczanie odpowiednich rang
                role_mentions = []

                for role_name in ALLOWED_ROLES:

                    role = discord.utils.find(
                        lambda r: (
                            r.name.lower() == role_name.lower()
                        ),
                        guild.roles
                    )

                    if role:
                        role_mentions.append(role.mention)

                ping_text = " ".join(role_mentions)

                if ping_text:
                    content = (
                        f"📢 **Nowa ankieta!** {ping_text}"
                    )
                else:
                    content = "📢 **Nowa ankieta!**"

                await channel.send(
                    content=content,
                    embed=embed,
                    view=view
                )

                print(
                    f"Utworzono ankietę: "
                    f"{channel.name} - {title}"
                )

                await asyncio.sleep(1)

            except Exception as e:

                print(
                    f"Błąd na kanale {channel.name}: {e}"
                )


# =========================
# KOMENDA /ANKIETY
# =========================

@bot.tree.command(
    name="ankiety",
    description="Tworzy nowe ankiety z datami"
)
async def ankiety(interaction: discord.Interaction):

    await interaction.response.send_message(
        "Tworzę nowe ankiety z aktualnymi datami...",
        ephemeral=True
    )

    await create_weekly_polls()


# =========================
# URUCHOMIENIE
# =========================

@bot.event
async def on_ready():

    try:

        synced = await bot.tree.sync()

        print(
            f"Zsynchronizowano {len(synced)} komend."
        )

    except Exception as e:

        print(
            f"Błąd synchronizacji: {e}"
        )

    print(f"Zalogowano jako {bot.user}")

    if not hasattr(bot, "scheduler"):

        bot.scheduler = AsyncIOScheduler(
            timezone=TZ
        )

        bot.scheduler.add_job(
            create_weekly_polls,
            "cron",
            day_of_week="sun",
            hour=0,
            minute=0
        )

        bot.scheduler.start()

        print(
            "Harmonogram ankiet uruchomiony."
        )


# =========================
# SPRAWDZENIE TOKENA
# =========================

if not TOKEN:

    raise ValueError(
        "Nie znaleziono zmiennej DISCORD_TOKEN!"
    )


# =========================
# START BOTA
# =========================

bot.run(TOKEN)
