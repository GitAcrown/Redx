from .fetcher import Fetcher

__red_end_user_data_statement__ = 'This cog does not store personal data.'

def setup(bot):
    bot.add_cog(Fetcher(bot))