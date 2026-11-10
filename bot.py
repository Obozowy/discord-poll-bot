import os
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Zalogowano pomyślnie jako {bot.user}")

@bot.command()
async def test(ctx):
    await ctx.send("Bot działa poprawnie!")

bot.run(TOKEN)
