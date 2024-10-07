import json
import logging
import aiohttp
import asyncio
import re
from typing import Optional
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

from redbot.core import Config, commands

log = logging.getLogger("red.cbd-cogs.scrub")

URL_PATTERN = re.compile(r'(https?://\S+)')
DEFAULT_URL = "https://kevinroebert.gitlab.io/ClearUrls/data/data.minify.json"
LOCAL_RULES_FILE_PATH = __file__.replace("scrub.py", "data.minify.json")


class Scrub(commands.Cog):
    """Applies a set of rules to remove undesirable elements from hyperlinks."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conf = Config.get_conf(self, identifier=0x7363727562626572, force_registration=True)
        self.conf.register_global(rules={}, threshold=2, url=DEFAULT_URL, openai_api_key=None)
        log.info("Scrub cog initialized.")
        asyncio.create_task(self._initialize_rules())

    async def _initialize_rules(self):
        """Initialize rules by trying to fetch them from URL first, then fallback to local file."""
        url = await self.conf.url()
        await self._update(url)

    async def _update(self, url):
        """Attempt to update rules from the URL; fallback to local if it fails."""
        log.debug(f'Downloading rules data from {url}')
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36"
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        log.error(f"Failed to download rules: HTTP {response.status} {response.reason}")
                        log.info("Attempting to load rules from local file.")
                        self._load_rules_from_file()
                        return

                    content = await response.read()
                    if not content:
                        log.error("Downloaded rules file is empty.")
                        log.info("Attempting to load rules from local file.")
                        self._load_rules_from_file()
                        return

                    rules = json.loads(content)
                    await self.conf.rules.set(rules)
                    log.info(f"Rules updated successfully from {url}")
            except (aiohttp.ClientError, json.JSONDecodeError) as e:
                log.error(f"Error occurred while updating rules: {e}")
                log.info("Attempting to load rules from local file.")
                self._load_rules_from_file()

    def _load_rules_from_file(self):
        """Load rules from a local JSON file as a fallback."""
        try:
            with open(LOCAL_RULES_FILE_PATH, 'r', encoding='utf-8') as f:
                rules = json.load(f)
            log.info(f"Rules loaded successfully from {LOCAL_RULES_FILE_PATH}")
            asyncio.create_task(self.conf.rules.set(rules))  # Use asyncio.create_task to avoid blocking
        except FileNotFoundError:
            log.error(f"Rules file not found: {LOCAL_RULES_FILE_PATH}")
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse rules JSON: {e}")

    @commands.group()
    async def scrub(self, ctx: commands.Context):
        """Scrub tracking elements from hyperlinks and generate roast messages."""
        pass

    @scrub.command()
    @commands.has_permissions(administrator=True)
    async def setapikey(self, ctx: commands.Context, api_key: str):
        """Set the OpenAI API key for generating roast messages."""
        await self.conf.openai_api_key.set(api_key)
        await ctx.send("OpenAI API key has been set successfully.")

    @commands.Cog.listener()
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
    
        links = list(set(URL_PATTERN.findall(message.content)))
        if not links:
            return
    
        rules = await self.conf.rules()
        threshold = await self.conf.threshold()
        clean_links = []
    
        for link in links:
            clean_link = self.clean_url(link, rules)
            if ((len(link) <= len(clean_link) - threshold or
                 len(link) >= len(clean_link) + threshold) and
                 link.lower() not in (clean_link.lower(),
                                      unquote(clean_link).lower())):
                clean_links.append(clean_link)
    
        if clean_links:
            # Send the cleaned links immediately
            plural = 'is' if len(clean_links) == 1 else 'ese'
            payload = "\n".join([f"<{link}>" for link in clean_links])
            response = f"I scrubbed th{plural} for you:\n{payload}"
            await message.channel.send(response)
    
            # Generate the roast message asynchronously
            asyncio.create_task(self.send_roast_message(message.channel, message.content))
    
    async def send_roast_message(self, channel, link):
        """Generate a roast message about the provided link and send it to the channel."""
        roast_message = await self.generate_roast_message(link)
        if roast_message:
            await channel.send(roast_message)

    def clean_url(self, url: str, rules: dict, loop: bool = True):
        """Clean the given URL with the provided rules data."""
        log.debug(f"Cleaning URL: {url}")  # Log the URL before cleaning
        original_url = url  # Store original URL for comparison

        for provider_name, provider in rules.get('providers', {}).items():
            if not re.match(provider['urlPattern'], url, re.IGNORECASE):
                continue

            if provider.get('completeProvider'):
                return False

            if any(re.match(exc, url, re.IGNORECASE) for exc in provider.get('exceptions', [])):
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
            log.info(f"URL cleaned: {original_url} -> {url}")
        return url
