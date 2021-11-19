import logging
import random
import re
from typing import List, Union

import discord

import time
from datetime import datetime, timedelta

from discord.ext import tasks
from discord.ext.commands import Greedy
from redbot.core import commands, Config, checks
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import box
from discord.utils import get as discord_get
from tabulate import tabulate

logger = logging.getLogger("red.RedX.Jailbreak")


class JailbreakError(Exception):
    pass

class JailRoleError(JailbreakError):
    pass
    

class Jailbreak(commands.Cog):
    """Système de prison"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)
        
        default_guild = {
            'Jail': {},
            'Settings': {
                'role': None,
                'default_time': 600,
                'exclude_channels': []
            }
        }
        self.config.register_guild(**default_guild)
        
        self.cache = {}
        
        self.jailbreak_checks.start()
        
        
# CHECKS______________________________________________________

    @tasks.loop(seconds=30.0)
    async def jailbreak_checks(self):
        all_guilds = await self.config.all_guilds()
        for g in all_guilds:
            jail = await self.config.guild_from_id(g).Jail()
            if jail:
                guild = self.bot.get_guild(g)
                for u in jail:
                    try:
                        user = guild.get_member(u)
                    except:
                        await self.jail_clear_userid(u)
                    else:
                        await self.jail_check_user(user)
                

    @jailbreak_checks.before_loop
    async def before_jailbreak_checks(self):
        logger.info('Lancement de jailbreak_checks...')
        await self.bot.wait_until_ready()
        
        
# FONCTIONS___________________________________________________

    async def jail_manage_user(self, ctx: commands.Context, user: discord.Member, seconds: int, *, reason: str = ''):
        guild = user.guild
        author, channel = ctx.author, ctx.channel
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        settings = await self.config.guild(guild).Settings()
        role = guild.get_role(settings['role'])
        if not role:
            raise ValueError("Le rôle prisonnier n'a pas été configuré")
        
        try:
            await user.add_roles(role, reason=f"Par {author} | {'« ' + reason + ' »' if reason else 'Raison inconnue'}") 
        except:
            return await channel.send(f"{cross}🔒 **Prison** · Impossible d'ajouter **{user}** à la prison")
        else:
            await self.config.guild(guild).Jail.set_raw(user.id, value={'time': seconds, 'channel': channel.id})
        
        dtime = datetime.now().fromtimestamp(seconds)
        if seconds > time.time():
            if dtime.day != datetime.now().day:
                msg = f"{check}🔒 **Prison** · Sortie de {user.mention} prévue le **{dtime.strftime('%d/%m/%Y à %H:%M')}**"
            else:
                msg = f"{check}🔒 **Prison** · Sortie de {user.mention} prévue à **{dtime.strftime('%H:%M')}**"
            if reason:
                msg += f"\n__Raison :__ `{reason}`"
        
        return await ctx.reply(msg, mention_author=False)
    
    async def jail_check_user(self, user: discord.Member):
        guild = user.guild
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        settings = await self.config.guild(guild).Settings()
        role = guild.get_role(settings['role'])
        if not role:
            raise ValueError("Le rôle prisonnier n'a pas été configuré")
        
        try:
            data = await self.config.guild(guild).Jail.get_raw(str(user.id))
        except KeyError:
            return
        
        seconds, channelid = data.values()
        if seconds >= int(time.time()):
            channel = guild.get_channel(channelid)
            await self.jail_clear_userid(guild, str(user.id))
            try:
                await user.remove_roles(role, reason="Fin de peine")
            except:
                return await channel.send(f"{cross}🔓 **Prison** · **{user}** a été sorti de force")
            
            msg = f"{check}🔓 **Prison** · Fin de peine de **{user}**"
            return await channel.send(msg)
        
    async def jail_clear_userid(self, guild: discord.Guild, user_id: str):
        cross = self.bot.get_emoji(812451214179434551)
        try:
            channelid = await self.config.guild(guild).Jail.get_raw(user_id, 'channel')
            await self.config.guild(guild).Jail.clear_raw(user_id)
        except KeyError:
            return
        else:
            user = self.bot.get_user(int(user_id))
            if user:
                msg = f"{cross}🔓 **Prison** · **{user}** n'a pu être sorti proprement\n*La raison la plus probable est que ce membre a quitté le serveur avant la fin de sa peine*"
            else:
                msg = f"{cross}🔓 **Prison** · **ID:{user_id}** n'a pu être sorti proprement\n*La raison la plus probable est que ce membre a quitté le serveur avant la fin de sa peine*"
        channel = guild.get_channel(channelid)
        return await channel.send(msg)
    
    
    def parse_timedelta(self, text: str) -> timedelta:
        text = text.lower()
        result = re.compile(r'([+-])?(?:(\d+)([smhj]?))', re.DOTALL | re.IGNORECASE).findall(text)
        if not result:
            raise ValueError("Le texte ne contient aucune indication de temps")
        
        fmtmap = {'s': 'seconds', 'm': 'minutes', 'h': 'hours', 'j': 'days'}
        args = {}
        for oper, value, fmt in result:
            fmtname = fmtmap.get(fmt, 'minutes')
            value = -int(value) if oper == '-' else int(value)
            args[fmtname] = args.get(fmtname, 0) + value
        
        return timedelta(**args)
        
# COMMANDES____________________________________________________
        
    @commands.group(name='jail', aliases=['p'], invoke_without_command=True)
    @checks.admin_or_permissions(manage_messages=True)
    async def jail_main(self, ctx, source: str = None):
        """Commandes de gestion de la prison"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.jail_users, source=source)
    
    @jail_main.commands(name='users', aliases=['user'])
    async def jail_users(self, ctx, users: Greedy[discord.Member], time: str = '', *, reason: str = ''):
        """Ajouter, retirer ou éditer une peine de prison d'un membre
        
        __**Format du temps de peine**__
        `+X` = Ajouter du temps
        `-X` = Retirer du temps
        `s/m/h/j` = **S**econdes, **M**inutes, **H**eures, **J**ours
        
        Exemples : `30m` | `+6h30m` | `-2h30`
        
        Il est possible d'ajouter une raison après le temps
        En l'absence de précision d'un format de temps, les *minutes* sont utilisées"""
        guild = ctx.guild
        cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        settings = await self.config.guild(guild).Settings()
        if not time:
            time = f"{settings['default_time']}s"
        
        try:
            tdelta = self.parse_timedelta(time)
        except ValueError:
            return await ctx.reply(f"{cross} **Erreur** · Format du temps invalide, consultez `;help p users`")
        
        role = guild.get_role(settings['role'])
        if not role:
            return await ctx.reply(f"{cross} **Erreur** · Le rôle de prisonnier n'a pas été configuré")
    
        seconds = (datetime.now() + tdelta).timestamp()
        for user in users:
            await self.jail_manage_user(ctx, user, seconds, reason=reason)
        
    @jail_main.commands(name='list', aliases=['liste'])
    async def jail_list(self, ctx):
        """Affiche une liste des membres actuellement emprisonnés"""
        guild = ctx.guild
        em = discord.Embed(title="Membres emprisonnés", color=await ctx.embed_color())
        em.set_footer(text="Gérez les peines avec la commande ';p'")
        
        jail = await self.config.guild(guild).Jail()
        if not jail:
            em.description = box("Prison vide")
        else:
            tabl = [(guild.get_member(u), datetime.now().fromtimestamp(jail[u]).strftime('%d/%m/%Y %H:%M')) for u in jail if guild.get_member(u)]
            em.description = box(tabulate(tabl, headers=('Membre', 'Sortie')))
        return await ctx.reply(embed=em, mention_author=False)
    
    
# PARAMETRES_______________________________________________________

    @commands.group(name="jailset", aliases=['pset'])
    @checks.admin_or_permissions(manage_messages=True)
    async def jail_settings(self, ctx):
        """Paramètres de la prison"""

    @jail_settings.command(name="role")
    async def jail_role(self, ctx, role: Union[discord.Role, bool] = None):
        """Définir le rôle de la prison

        Si aucun rôle n'est donné, celui-ci est créé automatiquement (si non déjà présent)
        Mettre 'False' désactive la prison"""
        guild = ctx.guild
        jail = await self.config.guild(guild).Settings()
        if type(role) == discord.Role:
            jail["role"] = role.id
            await ctx.send(f"**Rôle modifié** » Le rôle {role.mention} sera désormais utilisé pour la prison\n"
                           f"Faîtes `[p]pset check` pour régler automatiquement les permissions. "
                           f"Sachez que vous devez manuellement monter le rôle à sa place appropriée dans la hiérarchie.")
        elif role != False:
            maybe_role = discord_get(guild.roles, name="Prisonnier")
            if maybe_role:
                jail["role"] = maybe_role.id
                await ctx.send(
                    f"**Rôle détecté** » Le rôle {maybe_role.mention} sera désormais utilisé pour la prison\n"
                    f"Sachez que vous devez manuellement monter le rôle à sa place appropriée dans la hiérarchie.")
            else:
                role = await guild.create_role(name="Prisonnier", color=discord.Colour.default(),
                                               reason="Création auto. du rôle de prisonnier")
                jail["role"] = role.id
                await ctx.send(f"**Rôle créé** » Le rôle {role.mention} sera désormais utilisé pour la prison\n"
                               f"Sachez que vous devez manuellement monter le rôle à sa place appropriée dans la hiérarchie.")
        else:
            jail['role'] = None
            await ctx.send(f"**Rôle retiré** » La prison a été désactivée.")
        await self.config.guild(guild).Settings.set(jail)
        
    @jail_settings.command(name="delay")
    async def jail_default_delay(self, ctx, val: int = 600):
        """Règle le délai par défaut (en secondes) de la prison si aucune durée n'est spécifiée

        Doit être supérieur à 30 et inférieur à 86400 (1 jour)
        Par défaut 600s (10 minutes)"""
        guild = ctx.guild
        jail = await self.config.guild(guild).Settings()
        if 30 <= val <= 86400:
            jail["default_time"] = val
            await ctx.send(
                f"**Délai modifié** » Par défaut les prisonniers seront emprisonnés {val} secondes")
            await self.config.guild(guild).jail_settings.set(jail)
        else:
            await ctx.send(
                f"**Délai invalide** » La valeur du délai doit se situer entre 30 et 86400 secondes")
        
