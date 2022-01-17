import asyncio
import logging
import time
import aiohttp

import discord
from discord import webhook
from redbot.core import checks, commands
from typing import List

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
            'InputChannel': None,
            'Member': None
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
            if self.sessions[destchan]['InputChannel'] == channel:
                return self.bot.get_channel(destchan)
        return None
    
    
    async def clone_message(self, destination: discord.TextChannel, message: discord.Message):
        """Clone un message et lie le message de destination avec celui d'origine pour la session en cours"""
        session = self.get_session(destination)
        webhook_url = session['Webhook']
        msgtext = message.content
        if message.reference:
            ref = await message.channel.fetch_message(message.reference.message_id)
            msgtext = f'`> En réponse à {ref.author}`\n' + msgtext
        
        async def webhook_post() -> discord.WebhookMessage:
            try:
                async with aiohttp.ClientSession() as clientsession:
                    webhook = discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(clientsession))
                    uname = message.author.display_name if message.author != self.bot.user else f'{message.author.display_name} [Vous]'
                    attachs = [await a.to_file() for a in message.attachments] if message.attachments else None
                    return await webhook.send(content=msgtext, 
                                              username=uname, 
                                              avatar_url=message.author.avatar_url,
                                              files=attachs,
                                              wait=True)
            except:
                raise
            
        clone = await webhook_post()
        session['Messages'][clone.id] = message
        
        return clone
    
    async def send_message(self, channel: discord.TextChannel, text: str, *, files: List[discord.File] = None, reply_to: discord.Message = None):
        sessionchannel = self.fetch_input_session(channel)
        session = self.get_session(sessionchannel)
        async with channel.typing():
            await asyncio.sleep(len(text) / 10)
        if reply_to and not session['Member']:
            await reply_to.reply(text, mention_author=False, files=files)
        elif session['Member']:
            webhooks =  [u for u in await channel.webhooks() if not u.url.endswith('None')]
            if webhooks:
                webhook_url = webhooks[0].url
                try:
                    async with aiohttp.ClientSession() as clientsession:
                        webhook = discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(clientsession))
                        author = session['Member']
                        uname = f'{author.display_name} [Vous]'
                        attachs = files
                        return await webhook.send(content=text, 
                                                username=uname, 
                                                avatar_url=author.avatar_url,
                                                files=attachs,
                                                wait=True)
                except:
                    await channel.send(text, files=files)
            else:
                await channel.send(text, files=files)
        else:
            await channel.send(text, files=files)
        
            
    @commands.command(name="doppelganger", aliases=['dg'])
    @commands.guild_only()
    @checks.is_owner()
    async def new_dg_session(self, ctx, channelid: int, as_member: int = None):
        """Clone le salon visé afin de se faire passer pour le bot"""
        origin = self.bot.get_channel(channelid)
        destination = ctx.channel
        if not origin:
            return await ctx.reply("**Erreur** · Impossible d'accéder au salon demandé, vérifiez l'identifiant")
        
        member = None
        if as_member:
            member = origin.guild.get_member(as_member)
            if not member:
                return await ctx.reply("**Erreur** · Membre visé inaccessible")
            
        
        webhooks = [u for u in await destination.webhooks() if not u.url.endswith('None')]
        if not webhooks:
            return await ctx.reply("**Erreur** · Aucun webhook n'a été créé sur ce channel")
        webhook_url = webhooks[0].url
        
        await asyncio.sleep(0.5)
        session = self.init_session(destination, origin, webhook_url)
        session['Timeout'] = time.time() + 300
        session['Member'] = member
        await ctx.send("**Session ouverte avec le salon clone visé** · Tous les messages tapé dans ce salon seront recopiés automatiquement sur le salon cible et inversement")
        while time.time() < session['Timeout']:
            await asyncio.sleep(1)
        
        try:
            del session[destination.id]
        except:
            pass
        await ctx.send("**Session de clonage de salon expirée**")
        
    @commands.command(name="doppelstop", aliases=['dgstop'])
    @commands.guild_only()
    @checks.is_owner()
    async def stop_dg_session(self, ctx):
        """Arrête toutes les sessions doppelganger en cours sur ce salon"""
        if ctx.channel.id in self.sessions:
            self.sessions[ctx.channel.id]['Timeout'] = 0
            await asyncio.sleep(2)
            try:
                del self.sessions[ctx.channel.id]
            except:
                pass
        else:
            await ctx.send("**Aucune session à arrêter**")
        
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            channel = message.channel
            attachs = [await a.to_file() for a in message.attachments] if message.attachments else None
            
            sessionchannel = self.fetch_input_session(channel)
            if sessionchannel:
                return await self.clone_message(sessionchannel, message)
            
            sess = self.get_session(channel)
            if sess:
                if message.author.bot:
                    return
                if message.content.startswith(';'):
                    return
                sess['Timeout'] = time.time() + 300
                if message.reference:
                    orimsg = await message.channel.fetch_message(message.reference.message_id)
                    orimsgequiv = sess['Messages'].get(orimsg.id)
                    if not orimsgequiv:
                        return await channel.send("`Impossible d'envoyer la réponse au message sur le salon cloné`")
                    return await self.send_message(sess['InputChannel'], message.content, files=attachs, reply_to=orimsgequiv)
                return await self.send_message(sess['InputChannel'], message.content, files=attachs)