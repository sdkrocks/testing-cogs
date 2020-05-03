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
from redbot.core import Config, bot, checks, commands

log = logging.getLogger("red.cbd-cogs.scrub")

__all__ = ["UNIQUE_ID", "Scrub"]

UNIQUE_ID = 0x7363727562626572

URL_PATTERN = re.compile(r'https?://(\S+)')


class Scrub(commands.Cog):
    """Applies a set of rules to remove undesireable elements from hyperlinks
    
    URL parsing and processing functions based on code from Uroute (https://github.com/walterl/uroute)
    
    By default, this cog uses the URL cleaning rules provided by ClearURLs (https://gitlab.com/KevinRoebert/ClearUrls)"""
    def __init__(self, bot: bot.Red, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.conf = Config.get_conf(self, identifier=UNIQUE_ID, force_registration=True)
        self.conf.register_global(rules={}, url='https://kevinroebert.gitlab.io/ClearUrls/data/data.min.json')

    def clean_url(self, url, rules):
        """Clean the given URL with the provided rules data.
        The format of `rules` is the parsed JSON found in ClearURLs's
        [`data.min.json`](https://kevinroebert.gitlab.io/ClearUrls/data/data.min.json)
        file.
        URLs matching a provider's `urlPattern` and one of that provider's
        redirection patterns, will cause the URL to be replaced with the
        match's first matched group.
        """
        for provider in rules.get('providers', {}).values():
            if not re.match(provider['urlPattern'], url, re.IGNORECASE):
                continue
            if any(
                re.match(exc, url, re.IGNORECASE)
                for exc in provider['exceptions']
            ):
                continue
            for redir in provider['redirections']:
                match = re.match(redir, url, re.IGNORECASE)
                try:
                    if match and match.group(1):
                        return unquote(match.group(1))
                except IndexError:
                    # If we get here, we got a redirection match, but no
                    # matched grouped. The redirection rule is probably
                    # faulty.
                    pass
            parsed_url = urlparse(url)
            query_params = parse_qsl(parsed_url.query)

            for rule in provider['rules']:
                query_params = [
                    param for param in query_params
                    if not re.match(rule, param[0])
                ]
            url = urlunparse((
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                urlencode(query_params),
                parsed_url.fragment,
            ))
        return url

    @commands.Cog.listener()
    async def on_message(self, message):
        rules = await self.conf.rules()
        if rules == {}:
            rules = await self.update()
        links = list(set(URL_PATTERN.findall(message.content)))
        cleaned_links = []
        for link in links:
            cleaned_link = self.clean_url(link, rules)
            if link != cleaned_link:
                cleaned_links.append(cleaned_link)
        if not len(cleaned_links):
            return
        plural = 'is' if len(cleaned_links) == 1 else 'ese'
        response = f"I scrubbed th{plural} for you:\n" + "\n".join([f"https://{link}" for link in cleaned_links])
        await self.bot.send_filtered(message.channel, content=response)

    @commands.command(name="scrubupdate")
    @checks.is_owner()
    async def scrub_update(self, ctx: commands.Context, url: str = None):
        """Update Scrub with the latest rules
        
        By default, Scrub will get rules from https://gitlab.com/KevinRoebert/ClearUrls/raw/master/data/data.min.json
        
        This can be overridden by passing a `url` to this command with an alternative compatible rules file
        """
        confUrl = await self.conf.url()
        _url = url or confUrl
        try:
            await self.update(_url)
        except:
            await ctx.send("Rules update failed")
            raise
            return
        if _url != confUrl:
            await self.conf.url.set(url)
        await ctx.send("Rules updated")
    
    async def update(self, url):
        log.debug('Downloading rules data')
        session = aiohttp.ClientSession()
        async with session.get(url) as request:
            rules = json.loads(await request.read())
        await session.close()
        await self.conf.rules.set(rules)