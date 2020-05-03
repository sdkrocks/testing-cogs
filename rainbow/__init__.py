from .rainbow import Rainbow

async def setup(bot):
    bot.add_cog(Rainbow(bot))
