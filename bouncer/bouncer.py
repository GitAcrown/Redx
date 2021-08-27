import asyncio
import logging
import random
import time
from copy import copy

import aiohttp
import discord
from discord import channel
from discord.errors import DiscordException
from typing import Union, List, Literal
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS

from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate
from redbot.core.data_manager import cog_data_path, bundled_data_path

BouncerImg = 'https://i.imgur.com/50xn4uS.png'

class Bouncer(commands.Cog):
    """Videur virtuel pour serveurs Discord"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)
        
        default_guild = {
            'LeaveMsgChannel': None,
            'CustomLeaveEmoji': None,
            'CustomLeaveMsg': [],
            'LeaveMsgWebhook': None
        }
        
        self.config.register_guild(**default_guild)
        
        self.default_leave_emoji = 875929277604982825
        
    @commands.group(name="leaveset")
    @checks.admin_or_permissions(manage_messages=True)
    async def leavemsg_set(self, ctx):
        """Paramètres des messages de départ des membres"""
        
    @leavemsg_set.command(name='channel')
    async def set_channel(self, ctx, channel: discord.TextChannel = None):
        """Configurer un channel écrit pour recevoir les logs des départs des membres
        
        Ne rien mettre désactive les messages de départ (sauf si un Webhook est configuré)"""
        guild = ctx.guild
        if channel:
            await self.config.guild(guild).LeaveMsgChannel.set(channel.id)
            await ctx.send(f"**Channel configuré** • Le salon #{channel.name} sera utilisé pour recevoir les messages de départ des membres")
        else:
            await self.config.guild(guild).LeaveMsgChannel.set(None)
            await ctx.send(f"**Channel retiré** • Les messages de départ des membres ne seront plus affichés")
            
    @leavemsg_set.command(name='emoji')
    async def set_custom_emoji(self, ctx, emoji: discord.Emoji = None):
        """Customiser l'emoji utilisé au début des messages de départ des membres
        
        Ne rien mettre remet l'emoji par défaut"""
        guild = ctx.guild
        if emoji:
            await self.config.guild(guild).CustomLeaveEmoji.set(emoji.id)
            await ctx.send(f"**Emoji customisé** • L'emoji {emoji} sera utilisé au début des messages de départ des membres")
        else:
            await self.config.guild(guild).CustomLeaveEmoji.set(None)
            await ctx.send(f"**Emoji retiré** • L'emoji par défaut {self.bot.get_emoji(self.default_leave_emoji)} sera utilisé au début des messages de départ des membres")
            
    @leavemsg_set.command(name='webhook')
    async def set_webhook(self, ctx, webhook_url: str = None):
        """Activer/désactiver l'utilisation d'un webhook Bouncer pour les messages de départ
        
        Si vous configurez un webhook, vous n'avez pas à configurer un channel avec `;leaveset channel` et inversement"""
        guild = ctx.guild
        if webhook_url:
            async with aiohttp.ClientSession() as session:
                try:
                    webhook = discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(session))
                    await webhook.send("Ce message a été envoyé pour tester l'URL de Webhook fournie\n"
                                                "Si ce message s'affiche correctement vous pouvez le supprimer.",
                                                username="Test", avatar_url=self.bot.user.avatar_url)
                except:
                    return await ctx.send("**Erreur** • L'URL fournie n'est pas valide, vérifiez le webhook créé.")
                else:
                    await self.config.guild(guild).LeaveMsgWebhook.set(webhook_url)
                    await ctx.send(f"**Webhook configuré** • Son URL est `<{webhook_url}>`")
        else:
            await self.config.guild(guild).LeaveMsgWebhook.set(None)
            await ctx.send(f"**Webhook retiré** • Le bot utilisera le channel configuré avec `;leaveset channel` s'il y en a un")
            
        
    @leavemsg_set.group(name='msg')
    async def edit_leave_msgs(self, ctx):
        """Modifier les messages de départ aléatoires"""
        
    @edit_leave_msgs.command(name='add')
    async def add_leave_msg(self, ctx, *, msg: str):
        """Ajouter un message de départ personnalisé aléatoire
        
        __Balises :__
        - `{user.name}` = Pseudo du membre qui quitte le serveur
        - `{user.display_name}` = Alias du membre qui quitte (s'il en avait un), sinon son pseudo
        - `{user.mention}` = Mention du membre qui quitte (peut ne pas marcher si son compte est supprimé)
        - `{user.id}` = ID du membre"""
        guild = ctx.guild
        msglist = await self.config.guild(guild).CustomLeaveMsg()
        
        if 'user' not in msg:
            return await ctx.send("**Message invalide** • Vous n'utilisez aucune balise, le membre qui quitte le serveur n'est donc même pas mentionné\nPour en savoir plus sur les balaises, faîtes `;help leaveset msg add`")
        if msg in msglist:
            return await ctx.send("**Doublon** • Ce message de départ existe déjà, vous ne pouvez pas le reproposer")
        
        async with self.config.guild(guild).CustomLeaveMsg() as clm:
            clm.append(msg)
        
        txt = "**Message ajouté** • Le texte a été ajouté aux messages personnalisés de départ"
        if not msglist:
            txt += "\nMaintenant que vous avez configuré un message personnalisé, j'utiliserai que la liste personnalisée pour les messages de départ"
        await ctx.send(txt)
    
    @edit_leave_msgs.command(name='del', aliases=['delete'])
    async def del_leave_msg(self, ctx, nbs: str = None):
        """Supprimer un message de départ personnalisé
        
        Faîtes la commande sans arguments pour voir les numéros attribués à chaque message personnalisé, puis refaîte là avec le nombre ou l'intervalle désiré (`X-Y`)"""
        guild = ctx.guild
        msglist = await self.config.guild(guild).CustomLeaveMsg()
        
        if not nbs:
            n = 1
            txt = []
            embeds = []
            for i in msglist:
                chunk = f'{n}. {i}'
                if len('\n'.join(txt)) + len(chunk) > 2000:
                    em = discord.Embed(title="Messages de départ personnalisés", description=box('\n'.join(txt)))
                    em.set_footer(text=f"Page n°{len(embeds) + 1}")
                    embeds.append(em)
                    txt = []
                    
                txt.append(chunk)
                n += 1
                
            if txt:
                em = discord.Embed(title="Messages de départ personnalisés", description=box('\n'.join(txt)))
                em.set_footer(text=f"Page n°{len(embeds) + 1}")
                embeds.append(em)
                
            if embeds:
                await menu(ctx, embeds, DEFAULT_CONTROLS)
            else:
                await ctx.send(f"**Liste vide** • Il n'y a aucun message de départ personnalisé sur ce serveur")
            return
        
        if nbs.isdigit():
            nb = int(nbs)
            if not len(msglist) >= nb:
                return await ctx.send(f"**Erreur** • Aucun message n'est associé à ce nombre, faîtes `;leaveset msg del` sans argument pour voir la liste")
            
            async with self.config.guild(guild).CustomLeaveMsg() as clm:
                clm.remove(clm[nb - 1])
            
            await ctx.send(f"**Message supprimé** • Le message n°{nb} a été supprimé avec succès")
        elif '-' in nbs:
            nbs = nbs.split('-')
            if not nbs[0].isdigit() and nbs[1].isdigit():
                return await ctx.send(f"**Erreur** • L'intervalle est invalide, vous devez donner le nombre de début (`X`) et de fin d'intervalle (`Y`) dans le format `X-Y`")
            
            start, end, *_ = [int(n) for n in nbs]
            if not 1 <= start <= len(msglist):
                return await ctx.send(f"**Erreur** • L'intervalle est invalide, le premier nombre n'est pas associé à un message personnalisé")
            if not start < end <= len(msglist):
                return await ctx.send(f"**Erreur** • L'intervalle est invalide, le deuxième nombre est soit identique au premier nombre soit dépasse la longueur de la liste des messages personnalisés")
            
            async with self.config.guild(guild).CustomLeaveMsg() as clm:
                for m in msglist:
                    if start - 1 <= msglist.index(m) <= end - 1:
                        clm.remove(m)
                
            await ctx.send(f"**Messages supprimés** • Les messages allant du n°{start} à n°{end} ont été supprimés avec succès")
        else:
            await ctx.send(f"**Erreur** • Vous devez donner un intervalle de messages (par leur numéros) ou le numéro du message que vous voulez supprimer")
            
    @edit_leave_msgs.command(name='list')
    async def list_leave_msg(self, ctx):
        """Liste les messages de départ personnalisés"""
        guild = ctx.guild
        msglist = await self.config.guild(guild).CustomLeaveMsg()
        
        n = 1
        txt = []
        embeds = []
        for i in msglist:
            chunk = f'{n}. {i}'
            if len('\n'.join(txt)) + len(chunk) > 2000:
                em = discord.Embed(title="Messages de départ personnalisés", description=box('\n'.join(txt)))
                em.set_footer(text=f"Page n°{len(embeds) + 1}")
                embeds.append(em)
                txt = []
                
            txt.append(chunk)
            n += 1
        
        if txt:
            em = discord.Embed(title="Messages de départ personnalisés", description=box('\n'.join(txt)))
            em.set_footer(text=f"Page n°{len(embeds) + 1}")
            embeds.append(em)
        
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            await ctx.send(f"**Liste vide** • Il n'y a aucun message de départ personnalisé sur ce serveur")

    async def webhook_post(self, webhook_url: str, text: str):
        try:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(session))
                return await webhook.send(content=text, username=f'{self.bot.user.name} Bouncer', avatar_url=BouncerImg, wait=True)
        except:
            raise

    @commands.Cog.listener()
    async def on_member_remove(self, user):
        if isinstance(user, discord.Member):
            guild = user.guild
            settings = await self.config.guild(guild).all()
            if not settings['LeaveMsgWebhook'] and not settings['LeaveMsgChannel']:
                return
            
            custom_list = settings['CustomLeaveMsg']
            custom_emoji = settings['CustomLeaveEmoji']
            emoji = self.bot.get_emoji(custom_emoji) if custom_emoji else self.bot.get_emoji(self.default_leave_emoji)
            msg = random.choice(custom_list) if custom_list else "{user.name} a quitté le serveur"
            msg = f'{emoji} ' + msg.format(user=user, guild=guild)
            
            if settings['LeaveMsgWebhook']:
                await self.webhook_post(settings['LeaveMsgWebhook'], msg)
            else:  
                channel = guild.get_channel(settings['LeaveMsgChannel'])
                if channel:
                    await channel.send(msg)
                