
import os
import asyncio
import sqlite3
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz


# ==========================================
# KONFIGURACJA
# ==========================================

TOKEN = os.getenv("DISCORD_TOKEN")

# Baza danych - na Railway ustaw ścieżkę /data/bot.sqlite3
DB_PATH = os.getenv("DATABASE_PATH", "bot.sqlite3")

ALLOWED_ROLES = [
    "Zawodnik",
    "EU Plejer",
    "Testy",
    "KAPITAN",
    "Asystent",
]

ALLOWED_ROLE_IDS = {
    1327076489048490025,
    1470703435589353472,
    1327076272920068177,
    1569732469408661675,
    1327076329257959445,
}

REMINDER_ROLES = {
    "zawodnik",
    "eu plejer",
    "asystent",
}

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


# ==========================================
# KONFIGURACJA DISCORDA
# ==========================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ==========================================
# BAZA DANYCH SQLITE
# ==========================================

def db_connect():
    return sqlite3.connect(DB_PATH)


def init_database():

    with db_connect() as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                created_at TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                poll_message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                choice TEXT NOT NULL,
                PRIMARY KEY (poll_message_id, user_id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS reminder_messages (
                message_id INTEGER PRIMARY KEY,
                poll_message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL
            )
        """)

        db.commit()


def register_poll(message_id, guild_id, channel_id):

    with db_connect() as db:

        db.execute("""
            INSERT OR REPLACE INTO polls
            (message_id, guild_id, channel_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            message_id,
            guild_id,
            channel_id,
            datetime.now(TZ).isoformat()
        ))

        db.commit()


def save_vote(poll_message_id, user_id, choice):

    with db_connect() as db:

        db.execute("""
            INSERT INTO votes
            (poll_message_id, user_id, choice)
            VALUES (?, ?, ?)
            ON CONFLICT(poll_message_id, user_id)
            DO UPDATE SET choice = excluded.choice
        """, (
            poll_message_id,
            user_id,
            choice
        ))

        db.commit()


def get_votes(poll_message_id):

    with db_connect() as db:

        rows = db.execute("""
            SELECT user_id, choice
            FROM votes
            WHERE poll_message_id = ?
        """, (poll_message_id,)).fetchall()

    return {
        user_id: choice
        for user_id, choice in rows
    }


def add_reminder_message(message_id, poll_message_id, channel_id):

    with db_connect() as db:

        db.execute("""
            INSERT OR REPLACE INTO reminder_messages
            (message_id, poll_message_id, channel_id)
            VALUES (?, ?, ?)
        """, (
            message_id,
            poll_message_id,
            channel_id
        ))

        db.commit()


def get_reminder_messages(poll_message_id):

    with db_connect() as db:

        return db.execute("""
            SELECT message_id, channel_id
            FROM reminder_messages
            WHERE poll_message_id = ?
        """, (poll_message_id,)).fetchall()


def remove_reminder_record(message_id):

    with db_connect() as db:

        db.execute("""
            DELETE FROM reminder_messages
            WHERE message_id = ?
        """, (message_id,))

        db.commit()


def clear_channel_data(channel_id):

    with db_connect() as db:

        poll_ids = db.execute("""
            SELECT message_id
            FROM polls
            WHERE channel_id = ?
        """, (channel_id,)).fetchall()

        for (poll_id,) in poll_ids:

            db.execute("""
                DELETE FROM votes
                WHERE poll_message_id = ?
            """, (poll_id,))

        db.execute("""
            DELETE FROM polls
            WHERE channel_id = ?
        """, (channel_id,))

        db.execute("""
            DELETE FROM reminder_messages
            WHERE channel_id = ?
        """, (channel_id,))

        db.commit()


# ==========================================
# FORMATOWANIE ANKIETY
# ==========================================

def format_users_by_role(guild, user_ids):

    if not user_ids:
        return "Brak"

    grouped = {
        role_name: []
        for role_name in ALLOWED_ROLES
    }

    others = []

    for user_id in user_ids:

        member = guild.get_member(user_id)

        mention = f"<@{user_id}>"

        if member is None:
            others.append(mention)
            continue

        member_roles = {
            role.name.strip().lower()
            for role in member.roles
        }

        assigned = False

        for role_name in ALLOWED_ROLES:

            if role_name.lower() in member_roles:

                grouped[role_name].append(mention)
                assigned = True
                break

        if not assigned:
            others.append(mention)

    lines = []

    for role_name, mentions in grouped.items():

        if mentions:

            lines.append(
                f"**{role_name}:** " + ", ".join(mentions)
            )

    if others:
        lines.append("**Inni:** " + ", ".join(others))

    result = "\n".join(lines) if lines else "Brak"

    if len(result) > 1000:
        result = result[:950] + "\n... więcej osób"

    return result


def generate_embed(guild, title, votes):

    yes_users = [
        user_id for user_id, choice in votes.items()
        if choice == "yes"
    ]

    no_users = [
        user_id for user_id, choice in votes.items()
        if choice == "no"
    ]

    embed = discord.Embed(
        title=f"📋 Ankieta: {title}",
        color=discord.Color.blue()
    )

    embed.add_field(
        name=f"✅ Obecni ({len(yes_users)})",
        value=format_users_by_role(guild, yes_users),
        inline=False
    )

    embed.add_field(
        name=f"❌ Nieobecni ({len(no_users)})",
        value=format_users_by_role(guild, no_users),
        inline=False
    )

    return embed


# ==========================================
# AUTOMATYCZNA AKTUALIZACJA PRZYPOMNIEŃ
# ==========================================

async def update_reminders_after_vote(
    channel,
    poll_message_id,
    user_id
):

    reminder_records = get_reminder_messages(
        poll_message_id
    )

    for reminder_id, channel_id in reminder_records:

        try:

            reminder = await channel.fetch_message(
                reminder_id
            )

            new_lines = []

            for line in reminder.content.splitlines():

                # Usuwamy tylko wzmiankę osoby,
                # która właśnie zagłosowała.

                if line.strip() in (
                    f"<@{user_id}>",
                    f"<@!{user_id}>"
                ):
                    continue

                new_lines.append(line)

            new_content = "\n".join(new_lines)

            # Sprawdzamy, czy zostały jeszcze jakieś osoby

            import re

            remaining = re.findall(
                r"<@!?(\\d+)>",
                new_content
            )

            if not remaining:

                await reminder.delete()

                remove_reminder_record(reminder_id)

            else:

                await reminder.edit(
                    content=new_content
                )

        except discord.NotFound:

            remove_reminder_record(reminder_id)

        except discord.Forbidden:

            print(
                f"Brak uprawnień do edycji przypomnienia {reminder_id}"
            )

        except Exception as error:

            print(
                f"Błąd aktualizacji przypomnienia: {error}"
            )


# ==========================================
# WIDOK ANKIETY
# ==========================================

class PollView(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=None)

    def check_role(self, interaction):

        if (
            interaction.guild
            and interaction.user.id == interaction.guild.owner_id
        ):
            return True

        user_role_ids = {
            role.id
            for role in interaction.user.roles
        }

        return bool(
            user_role_ids.intersection(ALLOWED_ROLE_IDS)
        )

    async def register_vote(
        self,
        interaction,
        choice
    ):

        if not self.check_role(interaction):

            await interaction.response.send_message(
                "❌ Nie masz odpowiedniej rangi do głosowania!",
                ephemeral=True
            )

            return

        poll_message_id = interaction.message.id

        save_vote(
            poll_message_id,
            interaction.user.id,
            choice
        )

        votes = get_votes(poll_message_id)

        embed = generate_embed(
            interaction.guild,
            interaction.message.embeds[0].title.replace(
                "📋 Ankieta: ", ""
            ),
            votes
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

        # Aktualizacja przypomnienia po zagłosowaniu

        await update_reminders_after_vote(
            interaction.channel,
            poll_message_id,
            interaction.user.id
        )

    @discord.ui.button(
        label="Tak",
        style=discord.ButtonStyle.green,
        custom_id="poll_yes"
    )
    async def yes_button(
        self,
        interaction,
        button
    ):

        await self.register_vote(
            interaction,
            "yes"
        )

    @discord.ui.button(
        label="Nie",
        style=discord.ButtonStyle.red,
        custom_id="poll_no"
    )
    async def no_button(
        self,
        interaction,
        button
    ):

        await self.register_vote(
            interaction,
            "no"
        )


# ==========================================
# WYLICZANIE DATY
# ==========================================

def get_next_date(now, target_weekday):

    days_ahead = (
        target_weekday - now.weekday()
    ) % 7

    return now + timedelta(days=days_ahead)


# ==========================================
# USUWANIE STARYCH PRZYPOMNIEŃ
# ==========================================

async def cleanup_channel_reminders(channel):

    with db_connect() as db:

        records = db.execute("""
            SELECT message_id
            FROM reminder_messages
            WHERE channel_id = ?
        """, (channel.id,)).fetchall()

    for (message_id,) in records:

        try:

            message = await channel.fetch_message(
                message_id
            )

            await message.delete()

        except discord.NotFound:
            pass

        except discord.Forbidden:
            print(
                f"Brak uprawnień do usunięcia przypomnienia na {channel.name}"
            )

        except Exception as error:
            print(
                f"Błąd usuwania przypomnienia: {error}"
            )

        finally:
            remove_reminder_record(message_id)


# ==========================================
# TWORZENIE ANKIET
# ==========================================

async def create_weekly_polls():

    now = datetime.now(TZ)

    for guild in bot.guilds:

        for channel in guild.text_channels:

            channel_name = channel.name.lower().strip()

            if channel_name not in DAYS_CONFIG:
                continue

            try:

                # Usuwanie starych przypomnień

                await cleanup_channel_reminders(channel)

                # Usuwamy stare dane ankiety z bazy

                clear_channel_data(channel.id)

                target_weekday = DAYS_CONFIG[channel_name]

                poll_date = get_next_date(
                    now,
                    target_weekday
                )

                date_str = poll_date.strftime(
                    "%d.%m.%Y"
                )

                capitalized_day = channel_name.capitalize()

                title = (
                    f"{capitalized_day} "
                    f"({date_str}) - Zbiórka 19:50"
                )

                # Czyszczenie kanału

                try:

                    await channel.purge(limit=5)

                except discord.Forbidden:

                    print(
                        f"Brak uprawnień do czyszczenia: {channel.name}"
                    )

                await asyncio.sleep(1)

                # Tworzenie ankiety

                view = PollView()

                embed = generate_embed(
                    guild,
                    title,
                    {}
                )

                role_mentions = []

                for role_name in ALLOWED_ROLES:

                    role = discord.utils.find(
                        lambda r: r.name.strip().lower()
                        == role_name.strip().lower(),
                        guild.roles
                    )

                    if role is not None:
                        role_mentions.append(role.mention)

                ping_text = " ".join(role_mentions)

                content = (
                    f"📢 **Nowa ankieta!** {ping_text}"
                    if ping_text
                    else "📢 **Nowa ankieta!**"
                )

                message = await channel.send(
                    content=content,
                    embed=embed,
                    view=view
                )

                register_poll(
                    message.id,
                    guild.id,
                    channel.id
                )

                print(
                    f"Utworzono ankietę: {channel.name} - {title}"
                )

                await asyncio.sleep(1)

            except Exception as error:

                print(
                    f"Błąd na kanale {channel.name}: {error}"
                )


# ==========================================
# KOMENDA /ANKIETY
# ==========================================

@bot.tree.command(
    name="ankiety",
    description="Tworzy nowe ankiety z datami"
)
@app_commands.guild_only()
async def ankiety(interaction: discord.Interaction):

    await interaction.response.send_message(
        "Tworzę nowe ankiety z aktualnymi datami...",
        ephemeral=True
    )

    await create_weekly_polls()


# ==========================================
# KOMENDA /PRZYPOMNIJ
# ==========================================

@bot.tree.command(
    name="przypomnij",
    description="Oznacza osoby, które nie zaznaczyły ankiety"
)
@app_commands.guild_only()
async def przypomnij(interaction: discord.Interaction):

    channel = interaction.channel
    guild = interaction.guild

    channel_name = channel.name.lower().strip()

    if channel_name not in DAYS_CONFIG:

        await interaction.response.send_message(
            "❌ Użyj tej komendy na kanale z ankietą danego dnia!",
            ephemeral=True
        )

        return

    await interaction.response.defer()

    # Szukamy najnowszej ankiety

    poll_message = None

    async for message in channel.history(limit=30):

        if message.author.id != bot.user.id:
            continue

        if not message.embeds:
            continue

        embed = message.embeds[0]

        if (
            embed.title
            and embed.title.startswith("📋 Ankieta:")
        ):

            poll_message = message
            break

    if poll_message is None:

        await interaction.followup.send(
            "❌ Nie znaleziono ankiety na tym kanale."
        )

        return

    # Sprawdzamy zapisane głosy

    votes = get_votes(poll_message.id)

    voted_users = set(votes.keys())

    # Pobieramy członków serwera

    try:

        members = [
            member
            async for member in guild.fetch_members(
                limit=None
            )
        ]

    except discord.Forbidden:

        await interaction.followup.send(
            "❌ Nie można pobrać listy członków serwera. "
            "Sprawdź Server Members Intent."
        )

        return

    # Wyszukujemy osoby bez głosu

    missing_users = []

    for member in members:

        if member.bot:
            continue

        member_roles = {
            role.name.strip().lower()
            for role in member.roles
        }

        if not member_roles.intersection(REMINDER_ROLES):
            continue

        if member.id in voted_users:
            continue

        missing_users.append(member.mention)

    # Usuwamy poprzednie przypomnienie dla tej ankiety

    old_records = get_reminder_messages(
        poll_message.id
    )

    for reminder_id, channel_id in old_records:

        try:

            old_message = await channel.fetch_message(
                reminder_id
            )

            await old_message.delete()

        except discord.NotFound:
            pass

        except discord.Forbidden:
            pass

        finally:
            remove_reminder_record(reminder_id)

    if not missing_users:

        await interaction.followup.send(
            "✅ Wszystkie osoby z rangami "
            "**Zawodnik, EU Plejer i Asystent** "
            "zaznaczyły ankietę!"
        )

        return

    # Przygotowanie wiadomości

    header = (
        f"📢 **Przypomnienie – {channel_name.capitalize()}!**\n"
        f"Osoby, które nie zaznaczyły ankiety "
        f"({len(missing_users)}):\n\n"
    )

    current_message = header

    # Wysyłanie oznaczeń w częściach

    chunks = []

    for mention in missing_users:

        if len(current_message) + len(mention) + 1 > 1900:

            chunks.append(current_message)
            current_message = header

        current_message += mention + "\n"

    if current_message:
        chunks.append(current_message)

    # Wysyłamy i zapisujemy wiadomości przypominające

    for chunk in chunks:

        reminder = await interaction.followup.send(
            chunk,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            ),
            wait=True
        )

        add_reminder_message(
            reminder.id,
            poll_message.id,
            channel.id
        )

    print(
        f"Przypomnienie {channel_name}: "
        f"{len(missing_users)} osób"
    )


# ==========================================
# START I HARMONOGRAM
# ==========================================

@bot.event
async def on_ready():

    if not getattr(bot, "initialized", False):

        init_database()

        # Odtwarzanie obsługi przycisków
        # po restarcie bota

        bot.add_view(PollView())

        try:

            synced = await bot.tree.sync()

            print(
                f"Zsynchronizowano {len(synced)} komend."
            )

        except Exception as error:

            print(
                f"Błąd synchronizacji: {error}"
            )

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

        bot.initialized = True

    print(f"Zalogowano jako {bot.user}")


# ==========================================
# URUCHOMIENIE
# ==========================================

if not TOKEN:

    raise ValueError(
        "Nie znaleziono DISCORD_TOKEN w Railway Variables!"
    )

bot.run(TOKEN)
