import asyncio
import logging
from numbers import Rational
import random
import re
import string
import time
from copy import copy
from datetime import datetime, timedelta
from typing import Any, Generator, List, Literal, Union
import statistics
import aiohttp

import discord
from discord.errors import HTTPException
from discord.ext import tasks
from discord.ext.commands.converter import MemberConverter
from discord.ext.commands.errors import CommandRegistrationError
from discord.member import Member
from redbot.core import Config, checks, commands
from redbot.core.commands.commands import Cog
from redbot.core.config import Value
from redbot.core.utils import AsyncIter
from redbot.core.utils.chat_formatting import box, humanize_number, humanize_timedelta
from redbot.core.utils.menus import (DEFAULT_CONTROLS, menu,
                                     start_adding_reactions)
from tabulate import tabulate

logger = logging.getLogger("red.RedX.Clone")


class Clone(commands.Cog):
    """Clonage de salon et de discussions"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        
        self.sessions = {}
        self.DEFAULT_SESSION = {
            'Messages': {},
            'Webhook': None,
            'Timeout': 0,
            'InputChannel': None
        }
       
        
    def init_session(self, destination_channel: discord.TextChannel, input_channel: discord.TextChannel, webhook_url:str):
        self.sessions[destination_channel.id] = self.DEFAULT_SESSION
        self.sessions[destination_channel.id]['InputChannel'] = input_channel
        self.sessions[destination_channel.id]['Webhook'] = webhook_url
        return self.sessions[destination_channel.id]
        
    def get_session(self, channel: discord.TextChannel):
        return self.sessions.get(channel.id)
        
    def fetch_input_session(self, channel: discord.TextChannel) -> discord.TextChannel:
        for destchan in self.sessions:
            if self.sessions[destchan]['InputChannel'] == channel.id:
                return self.bot.get_channel(destchan)
        return None
    
    
    async def clone_message(self, destination: discord.TextChannel, message: discord.Message):
        """Clone un message et lie le message de destination avec celui d'origine pour la session en cours"""
        session = self.get_session(destination)
        webhook_url = session['Webhook']
        msgtext = message.content
        if message.reference:
            ref = await message.channel.fetch_message(message.reference.message_id)
            msgtext = f'`> En réponse à {ref.author}`\n'
        
        async def webhook_post() -> discord.WebhookMessage:
            try:
                async with aiohttp.ClientSession() as clientsession:
                    webhook = discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(clientsession))
                    return await webhook.send(content=msgtext, 
                                              username=message.author.display_name, 
                                              avatar_url=message.author.avatar_url,
                                              wait=True)
            except:
                raise
            
        clone = await webhook_post()
        session['Messages'][clone.id] = message
        
        return clone
    
    async def send_message(self, channel: discord.TextChannel, text: str, *, reply_to: discord.Message = None):
        if reply_to:
            await reply_to.reply(text, mention_author=False)
        else:
            await channel.send(text)
        
            
    @commands.command(name="doppelganger", aliases=['dg'])
    async def new_dg_session(self, ctx, channelid: int, webhook_url: str):
        """Clone le salon visé afin de se faire passer pour le bot"""
        origin = self.bot.get_channel(channelid)
        destination = ctx.channel
        if not origin:
            return await ctx.reply("**Erreur** · Impossible d'accéder au salon demandé, vérifiez l'identifiant")
        
        session = self.init_session(destination, origin, webhook_url)
        session['Timeout'] = time.time() + 300
        await ctx.send("**Session ouverte avec le salon clone visé** · Tous les messages tapé dans ce salon seront recopiés automatiquement sur le salon cible et inversement")
        while time.time() < session['Timeout']:
            await asyncio.sleep(1)
        
        del session[destination.id]
        await ctx.send("**Session de clonage de salon expirée**")
        
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            channel = message.channel
            
            sessionchannel = self.fetch_input_session(channel)
            if sessionchannel:
                return await self.clone_message(sessionchannel, message)
            
            sess = self.get_session(channel)
            if sess:
                if message.author.bot:
                    return
                sess['Timeout'] = time.time() + 300
                if message.reference:
                    orimsg = await message.channel.fetch_message(message.reference.message_id)
                    orimsgequiv = sess['Messages'].get(orimsg.id)
                    if not orimsgequiv:
                        return await channel.send("`Impossible d'envoyer la réponse au message sur le salon cloné`")
                    return await self.send_message(sess['InputChannel'], message.content, reply_to=orimsgequiv)
                return await self.send_message(sess['InputChannel'], message.content)