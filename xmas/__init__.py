from redbot.core import data_manager
from .xmas import XMas

__red_end_user_data_statement__ = 'This cog does not store personal data.'

def setup(bot):
    xmas = XMas(bot)
    data_manager.bundled_data_path(xmas)
    xmas._load_bundled_data()
    bot.add_cog(xmas)