# -*- coding: utf-8 -*-
from .scrub import Scrub

async def setup(bot: commands.Bot):
    """Setup function to add the Scrub cog."""
    await bot.add_cog(Scrub(bot))
