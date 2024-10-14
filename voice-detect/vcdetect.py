import discord
from discord.ext import tasks
from redbot.core import commands
import speech_recognition as sr
import asyncio
import io

class VoiceWordListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.trigger_words = ["example", "trigger", "hello"]  # Words to trigger notification
        self.recognizer = sr.Recognizer()
        self.voice_clients = {}  # Keep track of connected voice clients

    @commands.command()
    async def join(self, ctx: commands.Context):
        """Join the voice channel"""
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            voice_client = await channel.connect()
            self.voice_clients[ctx.guild.id] = voice_client
            await ctx.send(f"Joined {channel} and listening for words!")
        else:
            await ctx.send("You need to be in a voice channel for me to join!")

    @commands.command()
    async def leave(self, ctx: commands.Context):
        """Leave the voice channel"""
        if ctx.guild.id in self.voice_clients:
            await self.voice_clients[ctx.guild.id].disconnect()
            del self.voice_clients[ctx.guild.id]
            await ctx.send("Left the voice channel.")
        else:
            await ctx.send("I'm not in a voice channel on this server.")

    async def listen_and_process(self, guild_id, ctx):
        """Listen to the voice stream and process speech"""
        voice_client = self.voice_clients.get(guild_id)
        if not voice_client:
            return

        audio_source = discord.PCMAudio(voice_client)

        with sr.AudioFile(audio_source) as source:
            try:
                audio_data = self.recognizer.record(source)
                detected_text = self.recognizer.recognize_google(audio_data)
                await self.process_speech(detected_text, guild_id, ctx)
            except sr.UnknownValueError:
                pass  # Could not understand the audio

    async def process_speech(self, detected_text, guild_id, ctx):
        """Process detected speech and notify user if a word matches"""
        detected_words = detected_text.lower().split()
        for word in detected_words:
            if word in self.trigger_words:
                await self.notify_user(word, ctx.author, ctx)
                break

    async def notify_user(self, word, user, ctx):
        """Notify the user in the text channel about the word they said"""
        await ctx.send(f"{user.mention}, you said the word '{word}'!")

    @tasks.loop(seconds=5)
    async def voice_listener(self):
        """Periodically check the voice channels for speech"""
        for guild_id in self.voice_clients.keys():
            await self.listen_and_process(guild_id)

    @voice_listener.before_loop
    async def before_voice_listener(self):
        """Wait until the bot is ready before starting the loop"""
        await self.bot.wait_until_ready()

    def cog_unload(self):
        """Clean up when the cog is unloaded"""
        self.voice_listener.cancel()

def setup(bot):
    cog = VoiceWordListener(bot)
    bot.add_cog(cog)
    cog.voice_listener.start()
