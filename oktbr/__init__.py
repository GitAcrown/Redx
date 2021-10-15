from redbot.core import data_manager
from .oktbr import Oktbr

__red_end_user_data_statement__ = 'This cog does not store personal data.'

def setup(bot):
    oktbr = Oktbr(bot)
    data_manager.bundled_data_path(oktbr)
    oktbr._load_bundled_data()
    bot.add_cog(oktbr)