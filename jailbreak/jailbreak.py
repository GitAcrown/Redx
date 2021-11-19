import logging
import re
from typing import Union

import discord

import time
from datetime import datetime, timedelta

from discord.ext import tasks
from discord.ext.commands import Greedy
from redbot.core import commands, Config, checks
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
                        user = guild.get_member(int(u))
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
        else:
            return await self.jail_check_user(user)
        
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
        if seconds <= int(time.time()):
            channel = guild.get_channel(channelid)
            await self.config.guild(guild).Jail.clear_raw(str(user.id))
            try:
                await user.remove_roles(role, reason="Fin de peine")
            except:
                await self.jail_clear_userid(guild, str(user.id))
                return await channel.send(f"{cross}🔓 **Sortie de prison** · **{user}** a été sorti de force")
            
            msg = f"{check}🔓 **Sortie de prison** · Fin de peine de **{user}**"
            return await channel.send(msg)
        elif role not in user.roles:
            try:
                await self.config.guild(guild).Jail.clear_raw(str(user.id))
            except:
                pass
            channel = guild.get_channel(channelid)
            return await channel.send(f"{check}🔓 **Sortie de prison** · **{user}** a été sorti manuellement [Détection auto.]")
        
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
                msg = f"{cross}🔓 **Sortie de prison** · **{user}** n'a pu être sorti proprement\n*La raison la plus probable est que ce membre a quitté le serveur avant la fin de sa peine*"
            else:
                msg = f"{cross}🔓 **Sortie de prison** · **ID:{user_id}** n'a pu être sorti proprement\n*La raison la plus probable est que ce membre a quitté le serveur avant la fin de sa peine*"
        channel = guild.get_channel(channelid)
        return await channel.send(msg)
    
    
    def parse_timedelta(self, text: str) -> timedelta:
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
     
    @commands.command(name='prison', aliases=['p'])
    @checks.admin_or_permissions(manage_messages=True)
    async def jail_users(self, ctx, users: Greedy[discord.Member], duration: str = '', *, reason: str = ''):
        """Ajouter, retirer ou éditer une peine de prison d'un membre
        
        __**Format du temps de peine**__
        `+X` = Ajouter du temps
        `-X` = Retirer du temps
        `s/m/h/j` = **S**econdes, **M**inutes, **H**eures, **J**ours
        
        Exemples : `30m` | `+6h30m` | `-2h30`
        
        Il est possible d'ajouter une raison après le temps
        En l'absence de précision d'un format de temps, des minutes sont utilisées"""
        guild = ctx.guild
        cross = self.bot.get_emoji(812451214179434551)
        settings = await self.config.guild(guild).Settings()
        
        if not duration:
            time = f"{settings['default_time']}s"
        else:
            time = duration.lower()
        try:
            tdelta = self.parse_timedelta(time)
        except ValueError:
            return await ctx.reply(f"{cross} **Erreur** · Format du temps invalide, consultez `;help p users`")
        
        role = guild.get_role(settings['role'])
        if not role:
            return await ctx.reply(f"{cross} **Erreur** · Le rôle de prisonnier n'a pas été configuré")
    
        jail = await self.config.guild(guild).Jail()
        for user in users:
            if str(user.id) in jail and duration == '':
                seconds = 0
            elif str(user.id) in jail:
                dtime = datetime.now().fromtimestamp(jail[str(user.id)]['time'])
                seconds = (dtime + tdelta).timestamp()
            else:
                seconds = (datetime.now() + tdelta).timestamp()
                
            await self.jail_manage_user(ctx, user, seconds, reason=reason)
        
    @commands.command(name='prisonlist', aliases=['plist'])
    async def jail_list_users(self, ctx):
        """Affiche une liste des membres actuellement emprisonnés"""
        guild = ctx.guild
        em = discord.Embed(title="Membres emprisonnés", color=await ctx.embed_color())
        em.set_footer(text="Gérez les peines avec la commande ';p'")
        
        jail = await self.config.guild(guild).Jail()
        if not jail:
            em.description = box("Prison vide")
        else:
            tabl = [(guild.get_member(int(u)), datetime.now().fromtimestamp(jail[int(u)]['time']).strftime('%d/%m/%Y %H:%M')) for u in jail if guild.get_member(int(u))]
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
        
