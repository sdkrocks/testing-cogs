# -*- coding: utf-8 -*-
from .scrub import Scrub

async def setup(bot):
    """Setup function to add the Scrub cog."""
    await bot.add_cog(Scrub(bot))
