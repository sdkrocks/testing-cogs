# -*- coding: utf-8 -*-
from .vcdetect import vcdetect

async def setup(bot):
    """Setup function to add the vcdetect cog."""
    await bot.add_cog(vcdetect(bot))
