# -*- coding: utf-8 -*-
import aiohttp
import asyncio
import json
import logging
import re
from collections import namedtuple
from typing import Optional, Union
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import discord
from redbot.core import Config, commands

log = logging.getLogger("red.cbd-cogs.scrub")

__all__ = ["UNIQUE_ID", "Scrub"]

UNIQUE_ID = 0x7363727562626572
URL_PATTERN = re.compile(r'(https?://\S+)')
DEFAULT_URL = "https://rules1.clearurls.xyz/data.minify.json"


class Scrub(commands.Cog):
    """Applies a set of rules to remove undesirable elements from hyperlinks"""
    
    def __init__(self, bot: commands.Bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.conf = Config.get_conf(self,
                                    identifier=UNIQUE_ID,
                                    force_registration=True)
        self.conf.register_global(rules={},
                                  threshold=2,
                                  url=DEFAULT_URL)
        log.info("Scrub cog initialized.")  # Log cog initialization

    def clean_url(self, url: str, rules: dict, loop: bool = True):
        """Clean the given URL with the provided rules data."""
        log.debug(f"Cleaning URL: {url}")  # Log the URL before cleaning
        original_url = url  # Store original URL for comparison

        for provider_name, provider in rules.get('providers', {}).items():
            if not re.match(provider['urlPattern'], url, re.IGNORECASE):
                continue

            if provider.get('completeProvider'):
                return False

            if any(re.match(exc, url, re.IGNORECASE)
                   for exc in provider.get('exceptions', [])):
                continue

            for redir in provider.get('redirections', []):
                match = re.match(redir, url, re.IGNORECASE)
                try:
                    if match and match.group(1):
                        if loop:
                            return self.clean_url(unquote(match.group(1)), rules, False)
                        else:
                            url = unquote(match.group(1))
                except IndexError:
                    log.warning(f"Redirect target match failed [{provider_name}]: {redir}")
                    pass

            parsed_url = urlparse(url)
            query_params = parse_qsl(parsed_url.query)

            for rule in (*provider.get('rules', []), *provider.get('referralMarketing', [])):
                query_params = [
                    param for param in query_params
                    if not re.match(rule, param[0], re.IGNORECASE)
                ]

            url = urlunparse((
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                urlencode(query_params),
                parsed_url.fragment,
            ))

            for raw_rule in provider.get('rawRules', []):
                url = re.sub(raw_rule, '', url)

        if original_url != url:
            log.info(f"URL cleaned: {original_url} -> {url}")  # Log the before and after of URL scrubbing
        return url

    @commands.Cog.listener()
    async def on_message(self, message):
        if any((
            message.author.bot,
            message.guild and await self.bot.cog_disabled_in_guild(self, message.guild),
            not await self.bot.allowed_by_whitelist_blacklist(message.author),
        )):
            return

        message_location = "in DM" if message.guild is None else f"in guild {message.guild.name} (ID: {message.guild.id})"
        log.info(f"Processing message from {message.author} {message_location}")  # Log message location and author

        links = list(set(URL_PATTERN.findall(message.content)))
        if not links:
            log.debug("No URLs found in the message.")
            return

        log.debug(f"Found {len(links)} link(s) in the message: {links}")  # Log found links

        rules = await self.conf.rules() or await self._update(await self.conf.url())
        threshold = await self.conf.threshold()
        clean_links = []

        for link in links:
            clean_link = self.clean_url(link, rules)
            if ((len(link) <= len(clean_link) - threshold or
                 len(link) >= len(clean_link) + threshold) and
                 link.lower() not in (clean_link.lower(),
                                      unquote(clean_link).lower())):
                clean_links.append(clean_link)

        if not clean_links:
            log.debug("No links were scrubbed.")
            return

        plural = 'is' if len(clean_links) == 1 else 'ese'
        payload = "\n".join([f"<{link}>" for link in clean_links])
        response = f"I scrubbed th{plural} for you:\n{payload}"

        log.info(f"Sending scrubbed links: {clean_links}")  # Log the cleaned links
        await message.channel.send(content=response)

    async def view_or_set(self, attribute: str, value=None):
        config_element = getattr(self.conf, attribute)
        if value is not None:
            await config_element.set(value)
            log.info(f"Set {attribute} to {value}")  # Log setting a new value
            return f"set to {value}"
        else:
            value = await config_element()
            log.debug(f"Retrieved {attribute}: {value}")  # Log retrieving a value
            return f"is {value}"

    @commands.group()
    async def scrub(self, ctx: commands.Context):
        """Scrub tracking elements from hyperlinks."""
        pass

    @scrub.command()
    @commands.has_permissions(manage_guild=True)
    async def threshold(self, ctx: commands.Context, threshold: int = None):
        """View or set the minimum threshold for link changes."""
        action = await self.view_or_set("threshold", threshold)
        await ctx.send(f"Scrub threshold {action}")

    @scrub.command()
    @commands.has_permissions(manage_guild=True)
    async def rules(self, ctx: commands.Context, location: str = None):
        """View or set the rules file location to update from."""
        action = await self.view_or_set("url", location)
        await ctx.send(f"Scrub rules file location {action}")

    @scrub.command()
    @commands.has_permissions(manage_guild=True)
    async def update(self, ctx: commands.Context):
        """Update Scrub with the latest rules."""
        url = await self.conf.url()
        try:
            await self._update(url)
        except Exception as e:
            await ctx.send("Rules update failed (see log for details)")
            log.exception("Rules update failed", exc_info=e)  # Log the exception
            return
        await ctx.send("Rules updated")

    async def _update(self, url):
        log.debug(f'Downloading rules data from {url}')
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        log.error(f"Failed to download rules: HTTP {response.status} {response.reason}")
                        return
                    
                    # Attempt to read and parse the JSON response
                    try:
                        content = await response.read()
                        if not content:
                            log.error("Downloaded rules file is empty.")
                            return
                        
                        rules = json.loads(content)
                        await self.conf.rules.set(rules)
                        log.info(f"Rules updated successfully from {url}")
                    except json.JSONDecodeError:
                        log.error(f"Failed to decode rules JSON from {url}")
            except aiohttp.ClientError as e:
                log.error(f"Error occurred while downloading rules from {url}: {e}")
