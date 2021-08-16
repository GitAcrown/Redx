from redbot.core import data_manager
from .shift import Shift

__red_end_user_data_statement__ = 'This cog does not store personal data.'

async def setup(bot):
    shift = Shift(bot)
    data_manager.bundled_data_path(shift)
    await shift._load_bundled_data()
    bot.add_cog(shift)