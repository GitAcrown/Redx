from redbot.core import data_manager
from .spark import Spark

__red_end_user_data_statement__ = 'This cog does not store personal data.'

def setup(bot):
    spark = Spark(bot)
    data_manager.bundled_data_path(spark)
    spark._load_bundled_data()
    bot.add_cog(spark)