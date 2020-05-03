# -*- coding: utf-8 -*-
from .scrub import Scrub

async def setup(bot):
    bot.add_cog(Scrub(bot))