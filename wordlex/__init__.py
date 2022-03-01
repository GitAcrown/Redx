from redbot.core import data_manager
from .wordlex import WordleX

__red_end_user_data_statement__ = 'This cog does not store personal data.'

def setup(bot):
    wordlex = WordleX(bot)
    data_manager.bundled_data_path(wordlex)
    wordlex._load_bundled_data()
    bot.add_cog(wordlex)