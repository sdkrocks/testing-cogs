# -*- coding: utf-8 -*-
from .vcdetect import VoiceWordListener

async def setup(bot):
    """Setup function to add the vcdetect cog."""
    await bot.add_cog(VoiceWordListener(bot))
