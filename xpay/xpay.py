import asyncio
import logging
from numbers import Rational
import random
import re
import string
import time
import uuid
from copy import copy
from datetime import datetime, timedelta
from typing import Generator, List, Literal, Union
import statistics

import discord
from discord.errors import HTTPException
from discord.ext import tasks
from discord.ext.commands.converter import MemberConverter
from discord.member import Member
from redbot.core import Config, checks, commands
from redbot.core.config import Value
from redbot.core.utils import AsyncIter
from redbot.core.utils.chat_formatting import box, humanize_number, humanize_timedelta
from redbot.core.utils.menus import (DEFAULT_CONTROLS, menu,
                                     start_adding_reactions)
from tabulate import tabulate

logger = logging.getLogger("red.RedX.XPay")

LOGS_EXPIRATION = 604800 # 7 jours

MEDALS = {
    1: '🥇',
    2: '🥈',
    3: '🥉'
}


class Account:
    def __init__(self, member: discord.Member, data: dict):
        self.member = member
        
        self.balance = data['Balance']
        self.logs = data['Logs']
        self.config = data['Config']
        
        self.__dict__.update(data)

    def __str__(self):
        return self.member
    
    def __int__(self):
        return self.balance
    
    def __eq__(self, other: object):
        return self.member.id == other.member.id
    
    def humanize_balance(self):
        return humanize_number(self.balance)


class Transaction:
    def __init__(self, member: discord.Member, data):
        self.member = member
        self._raw = data
        
        self.delta = data['delta']
        self.timestamp = data['timestamp']
        
        self.__dict__.update(data)

    def __str__(self):
        return self.id
    
    def __getattr__(self, attr):
        return None
    
    @property
    def id(self):
        return f'{str(int(self.timestamp * 100))}{self.delta:+}'
    
    @property
    def description(self):
        poss_desc = [k for k in self.__dict__ if k in ('description', 'desc', 'reason')]
        if poss_desc:
            return self._raw[poss_desc[0]]
        return '...'
    
    def ftimestamp(self, fmt: str = '%d/%m/%Y %H:%M'):
        return datetime.now().fromtimestamp(self.timestamp).strftime(fmt)
    

class XPay(commands.Cog):
    """Système d'économie virtuelle"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {
            'Balance': 0,
            'Logs': [],
            'Config': {
                'day': '',
                'week': datetime.now().strftime('%V%Y'),
                'transfer_count': 0
            }
        }

        default_guild = {
            'Currency': 'C',
            'Income': {
                'Base': 100,
                'BaseLimit': 100000,
                'Booster': 50,
                'LowBalance': 50,
                'LowBalanceLimit': 1000},
            'Giftcodes': {},
            'Settings': {
                'FreeTransfersPerWeek': 3,
                'TransferFee': 0.05}
        }

        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        
        
# META >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>><
    
    async def migrate_from_alteco(self):
        """Tente l'importation des données depuis l'ancien module économique AltEco"""
        try:
            alteco_conf = Config.get_conf(None, identifier=736144321857978388, cog_name="AltEco")
            guilds = self.bot.guilds
            n = 1
            for guild in guilds:
                logger.info(msg=f"{n} Importation des données AltEco de : {guild.name}")
                old_data = await alteco_conf.guild(guild).all()
                await self.config.guild(guild).Currency.set(old_data['Currency']['string'])
                await self.config.guild(guild).Income.set_raw('Base', value=old_data['DailyBonus']['base'])

                for member in guild.members:
                    user_old = await alteco_conf.member(member).all()
                    await self.config.member(member).Balance.set(user_old['balance'])
                n += 1
        except Exception as e:
            logger.error(e, exc_info=True)
            raise
        return True
    
    
# BANQUE -----------------------------------------------

    async def get_currency(self, guild: discord.Guild):
        return await self.config.guild(guild).Currency()
    
    async def get_leaderboard(self, guild: discord.Guild, top_cutoff: int = None) -> List[Account]:
        """Renvoie le top des membres les plus riches du serveur (liste d'objets AltEcoAccount) des plus riches aux moins riches

        Renvoie une liste vide si aucun top n'est générable"""
        users = await self.config.all_members(guild)
        sorted_users = sorted(list(users.items()), key=lambda u: u[1]['Balance'], reverse=True)
        top = []
        for uid, acc in sorted_users:
            user = guild.get_member(uid)
            if user:
                top.append(await self.get_account(user))
        return top[:top_cutoff] if top_cutoff else top
    
    async def get_leaderboard_member_rank(self, member: discord.Member) -> int:
        """Renvoie la position du membre dans le classement de son serveur

        Renvoie la dernière place du classement si le membre n'est pas trouvé"""
        top = await self.get_leaderboard(member.guild)
        for acc in top:
            if acc.member == member:
                return top.index(acc) + 1
        return len(top)

    async def guild_total_credits(self, guild: discord.Guild) -> int:
        """Renvoie la valeur totale des crédits en circulation sur le serveur visé"""
        users = await self.config.all_members(guild)
        return sum([users[u]['Balance'] for u in users])
    
    async def guild_average_balance(self, guild: discord.Guild) -> int:
        usersraw = await self.config.all_members(guild)
        return statistics.mean([usersraw[u]['Balance'] for u in usersraw if usersraw[u]['Balance'] > 0])
    
    async def guild_balance_standard_deviation(self, guild: discord.Guild) -> int:
        usersraw = await self.config.all_members(guild)
        return statistics.stdev([usersraw[u]['Balance'] for u in usersraw if usersraw[u]['Balance'] > 0])
        
    
# COMPTE -----------------------------------------------

    async def get_account(self, member: discord.Member) -> Account:
        raw = await self.config.member(member).all()
        return Account(member, raw)
    
    async def get_balance(self, member: discord.Member) -> int:
        return await self.config.member(member).Balance()
    
    async def balance_variation(self, member: discord.Member, 
                                start: float = time.time() - LOGS_EXPIRATION,
                                end: float = time.time()) -> int:
        totaldelta = 0
        logs = await self.member_logs(member)
        for log in logs:
            if start <= log.timestamp <= end:
                totaldelta += log.delta
                
        return totaldelta
    
    async def check_balance(self, member: discord.Member, cost: int) -> int:
        return await self.get_balance(member) >= cost
    
    async def set_balance(self, member: discord.Member, value: int, **attachments) -> Transaction:
        if value < 0:
            raise ValueError("La valeur du solde ne peut être négative")
        
        current = await self.get_balance(member)
        await self.config.member(member).Balance.set(value)
        
        return await self.register_log(member, value - current, **attachments)
    
    async def deposit_credits(self, member: discord.Member, amount: int, **attachments) -> Transaction:
        if amount < 0:
            raise ValueError("Impossible d'ajouter une valeur négative au solde")
        
        current = await self.get_balance(member)
        return await self.set_balance(member, current + amount, **attachments)
    
    async def withdraw_credits(self, member: discord.Member, amount: int, **attachments) -> Transaction:
        amount = abs(amount)
        
        current = await self.get_balance(member)
        return await self.set_balance(member, current - amount, **attachments)
    
    async def refund_credits(self, log: Transaction) -> Transaction:
        member = log.member
        if log.refund:
            raise ValueError(f"Impossible de rembourser un remboursement ({log.id})")
        amount = -log.delta
        current = await self.get_balance(member)
        return await self.set_balance(member, current + amount, refund=log.id)
    

# TRANSACTIONS -----------------------------------------

    async def member_logs(self, member: discord.Member) -> List[Transaction]:
        raw = await self.config.member(member).Logs()
        logs = []
        for l in raw:
            logs.append(Transaction(member, l))
        return logs

    async def get_log(self, member: discord.Member, id: str) -> Transaction:
        for log in await self.member_logs(member):
            if log.id == id:
                return log
        return None
    
    async def register_log(self, member: discord.Member, delta: int, **attachments) -> Transaction:
        log = {'delta': delta, 'timestamp': time.time()}
        log.update(attachments)
        async with self.config.member(member).Logs() as logs:
            logs.append(log)
        
        return Transaction(member, log)
    
    async def delete_log(self, member: discord.Member, log: Transaction):
        async with self.config.member(member).logs() as logs:
            try:
                logs.remove(log._raw)
            except ValueError:
                raise
            
    async def clear_logs(self, member: discord.Member) -> dict:
        clean = await self.config.member(member).Logs()
        for log in await self.member_logs(member):
            if log.timestamp + LOGS_EXPIRATION <= time.time():
                clean.remove(log._raw)
        
        await self.config.member(member).Logs.set(clean)
        return clean
    

# CODES ------------------------------------------------

    async def get_giftcode(self, guild: discord.Guild, code: str) -> int:
        codes = await self.config.guild(guild).Giftcodes()
        if code not in codes:
            raise KeyError(f"'{code}' n'existe pas dans les codes cadeaux sur {guild.name}")
        
        return codes[code]
    
    async def create_giftcode(self, guild: discord.Guild, code: str, value: int) -> str:
        if await self.get_giftcode(guild, code):
            raise KeyError(f"'{code}' existe déjà dans les codes cadeaux sur {guild.name}")
        
        await self.config.guild(guild).Giftcodes.set_raw(code, value=value)
        return code
    
    async def delete_giftcode(self, guild: discord.Guild, code: str):
        if not await self.get_giftcode(guild, code):
            raise KeyError(f"'{code}' n'existe pas dans les codes cadeaux sur {guild.name}")
        
        await self.config.guild(guild).Giftcodes.clear_raw(code)


# CONFIG -----------------------------------------------

    async def wipe_member_logs(self, member: discord.Member) -> None:
        """Supprime tous les logs d'un membre"""
        await self.config.member(member).clear_raw('Logs')

    async def wipe_guild(self, guild: discord.Guild) -> None:
        """Supprime les données bancaires des membres d'un serveur"""
        await self.config.clear_all_members(guild)

    async def wipe_account(self, member: discord.Member) -> None:
        """Supprime les données bancaires d'un membre"""
        await self.config.member(member).clear()

    async def delete_account_id(self, user_id: int, guild: discord.Guild) -> None:
        """Supprime un compte bancaire par ID du membre"""
        await self.config.member_from_ids(guild.id, user_id).clear()

    async def red_delete_data_for_user(
        self, *, requester: Literal["discord", "owner", "user", "user_strict"], user_id: int
    ):
        await self.config.user_from_id(user_id).clear()
        all_members = await self.config.all_members()
        async for guild_id, guild_data in AsyncIter(all_members.items(), steps=100):
            if user_id in guild_data:
                await self.config.member_from_ids(guild_id, user_id).clear()
          
                
# UTILS -------------------------------------------------

    async def utils_parse_timedelta(self, time_string: str) -> timedelta:
        """Renvoie un objet *timedelta* à partir d'un str contenant des informations de durée (Xj Xh Xm Xs)"""
        if not isinstance(time_string, str):
            raise TypeError("Le texte à parser est invalide, {} != str".format(type(time_string)))

        regex = re.compile('^((?P<days>[\\.\\d]+?)j)? *((?P<hours>[\\.\\d]+?)h)? *((?P<minutes>[\\.\\d]+?)m)? *((?P<seconds>[\\.\\d]+?)s)? *$')
        sch = regex.match(time_string)
        if not sch:
            raise ValueError("Aucun timedelta n'a pu être déterminé des valeurs fournies")

        parsed = sch.groupdict()
        return timedelta(**{i: int(parsed[i]) for i in parsed if parsed[i]})


# COMMANDES ++++++++++++++++++++++++++++++++++++++++++++

    @commands.command(name='account', aliases=['b'])
    @commands.guild_only()
    async def account_info(self, ctx, user: discord.Member = None):
        """Afficher ses informations de compte bancaire virtuel
        
        Mentionner un autre membre avec la commande permet de consulter son compte"""
        user = user if user else ctx.author
        guild = ctx.guild
        account = await self.get_account(user)
        currency = await self.get_currency(guild)
        
        em = discord.Embed(color=user.color)
        em.set_author(name=f'{user.name}' if user != ctx.author else "Votre compte", icon_url=user.avatar_url)
        
        em.add_field(name="Solde", value=box(f"{account.humanize_balance()}{currency}"))
        
        var = await self.balance_variation(user, time.time() - 86400)
        original = account.balance - var if account.balance != var else account.balance
        if original != 0:
            prc = round((var / original) * 100, 2)
        else:
            prc = 0.0
        em.add_field(name=f"Variation sur 24h", value=box(f"{var:+} ({prc:+}%)", lang='fix' if var < 0 else 'css'))
        
        rank = await self.get_leaderboard_member_rank(user)
        medal = f' {MEDALS[rank]}' if rank in MEDALS else ''
        em.add_field(name="Rang", value=box(f"#{rank}{medal}", lang='css'))
        
        logs = await self.member_logs(user)
        if logs:
            txt = "\n".join([f"{log.delta:+}{'ʳ' if log.refund else ''} · {log.description[:50]}" for log in logs][::-1][:5])
            em.add_field(name=f"Historique", value=box(txt), inline=False)
            
        em.set_footer(text=f"Compte bancaire – {guild.name}")
        await ctx.reply(embed=em, mention_author=False)
        
    @commands.command(name='bankinfo')
    @commands.guild_only()
    async def bank_info(self, ctx):
        """Affiche un récapitulatif d'informations importantes sur la banque de ce serveur"""
        guild = ctx.guild
        currency = await self.get_currency(guild)
        data = await self.config.guild(guild).all()
        
        em = discord.Embed(color=await ctx.embed_color())
        em.set_thumbnail(url=guild.icon_url)
        em.set_footer(text=f"¹Réinitialisation tous les lundis\n²Prélevée sur la somme transférée si les fonds sont insuffisants")
        
        stats = f"**Crédits en circulation** · {humanize_number(await self.guild_total_credits(guild))}{currency}\n"
        stats += f"**Solde moyen** (>0{currency}) · {round(await self.guild_average_balance(guild), 2)}{currency}\n"
        stats += f"**Écart type du solde** (>0{currency}) · {round(await self.guild_balance_standard_deviation(guild), 2)}\n"
        em.add_field(name="Statistiques", value=stats)
        
        income = data['Income']
        incometxt = f"**Base d'aide** · {income['Base']}{currency}\n"
        if income['BaseLimit']:
            incometxt += f"› Solde maximal pour son attribution · {income['BaseLimit']}{currency}\n"
        incometxt += f"**Booster du serveur** · {income['Booster']}{currency}\n"
        incometxt += f"**Solde faible** · {income['LowBalance']}{currency}\n"
        incometxt += f"› Solde considéré comme faible · Inf. à {income['LowBalanceLimit']}{currency}"
        em.add_field(name="Aides journalières", value=incometxt)
        
        setts = data['Settings']
        trstxt = f"**Transferts offerts** · {setts['FreeTransfersPerWeek']}x par semaine¹\n"
        trstxt += f"**Frais de transfert** · {round(setts['TransferFee'] * 100, 1)}% de la somme²"
        em.add_field(name="Transferts", value=trstxt)
        
        await ctx.send(embed=em)
        
    @commands.command(name="history")
    @commands.guild_only()
    async def account_history(self, ctx, user: discord.Member = None):
        """Afficher l'historique du compte bancaire virtuel
        
        Mentionner un autre membre avec la commande permet de consulter son historique"""
        user = user if user else ctx.message.author
        
        logs = await self.member_logs(user)
        if not logs:
            return await ctx.reply(f"**Aucune opération dans l'historique** • Il n'y a aucune opération enregistrée sur ce compte",
                                   mention_author=False)
        
        embeds = []
        tabl = []
        for log in logs[::-1]:
            if len(tabl) < 25:
                fmt = '%d/%m/%Y %H:%M' if log.ftimestamp('%d/%m/%Y') != datetime.now().strftime('%d/%m/%Y') else '%H:%M'
                tabl.append((log.ftimestamp(fmt), f"{log.delta:+}{'ʳ' if log.refund else ''}", f"{log.description[:50]}"))
            else:
                em = discord.Embed(color=user.color, description=box(tabulate(tabl, headers=["Date/Heure", "Opération", "Description"])))
                em.set_author(name=f'{user.name}', icon_url=user.avatar_url)
                em.set_footer(text=f"Historique – {ctx.guild.name}")
                embeds.append(em)
                tabl = []
        if tabl:
            em = discord.Embed(color=user.color, description=box(tabulate(tabl, headers=["Date/Heure", "Opération", "Description"])))
            em.set_author(name=f'{user.name}', icon_url=user.avatar_url)
            em.set_footer(text=f"Historique – {ctx.guild.name}")
            embeds.append(em)
        
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply(f"**Aucune opération dans l'historique** • Il n'y a aucune opération enregistrée sur ce compte",
                                   mention_author=False)
            
    @commands.command(name="give")
    @commands.guild_only()
    async def give_credits(self, ctx, member: discord.Member, sum: int, *, reason: str = ''):
        """Transférer des crédits au membre visé 
        
        Il est possible de préciser une raison au transfert après la somme
        Les frais de transfert qui ne peuvent être xpayés sont prélevés sur la somme transférée"""
        author = ctx.author
        guild = ctx.guild
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        if sum < 0:
            return await ctx.reply(f"{stop} **Impossible** • Vous ne pouvez pas transférer une somme négative")
        
        currency = await self.get_currency(guild)
        reasonstring = f'{author.name} › {reason}' if reason else f'Don reçu de {author.name}'
        
        settings = await self.config.guild(guild).Settings()
        
        trscount = await self.config.member(author).Config.get_raw('transfer_count')
        userweek = await self.config.member(author).Config.get_raw('week')
        
        if userweek != datetime.now().strftime('%V%Y'):
            trscount = 0
        
        fee = 0
        if trscount >= settings['FreeTransfersPerWeek']:
            fee = round(sum * settings['TransferFee'])
            fee = fee if fee else 1
            if not await self.check_balance(member, fee + sum):
                sum -= fee
                
        try:
            await self.withdraw_credits(author, fee + sum, desc=f'Don à {member.name}')
        except:
            return await ctx.reply(f"{stop} **Fonds insuffisants** • Vous n'avez pas cette somme sur votre compte")
        else:
            await self.deposit_credits(member, sum, desc=reasonstring)
            
            txt = f"{conf} **Don effectué** • {member.mention} a reçu {humanize_number(sum)}{currency} de votre part"
            if fee:
                txt += f" [Frais · -{fee}{currency}]"
            if reason:
                txt += f"\n**Raison** · `{reason}`"
            
            trscount += 1
            await self.config.member(author).Config.set_raw('transfer_count', value=trscount)
            if userweek != datetime.now().strftime('%V%Y'):
                await self.config.member(author).Config.set_raw('week', value=datetime.now().strftime('%V%Y'))

            await ctx.reply(txt)
        
    @commands.command(name="bonus", aliases=['rj'])
    @commands.guild_only()
    async def get_daily_income(self, ctx):
        """Récupérer son revenu hebdomadaire"""
        author = ctx.author
        guild = ctx.guild
        today = datetime.now().strftime("%Y%m%d")
        account = await self.get_account(author)
        currency = await self.get_currency(ctx.guild)
        
        income = await self.config.guild(guild).Income()
        total = 0
        text = ''

        if account.config['day'] == today:
            em = discord.Embed(description="**Vous n'avez plus aucune aide à récupérer pour aujourd'hui**\nRevenez demain !", color=author.color)
            em.set_author(name="Vos aides journalières", icon_url=author.avatar_url)
            return await ctx.reply(embed=em, mention_author=False)
        
        if income['BaseLimit'] and account.balance > income['BaseLimit']:
            text += f"+0 · Base d'aide journalière (Solde trop élevé)\n"
        else:
            total += income['Base']
            text += f"+{income['Base']} · Base d'aide journalière\n"
        
        if ctx.author.premium_since:
            total += income['Booster']
            text += f"+{income['Booster']} · Booster du serveur\n"
        
        if account.balance < income['LowBalanceLimit']:
            total += income['LowBalance']
            text += f"+{income['LowBalance']} · Majoration solde faible\n"
        
        if text:
            text += f'————————————\n={total}{currency}'
            await self.config.member(author).Config.set_raw('day', value=today)
            await self.deposit_credits(author, total, desc='Aides journalières')
            em = discord.Embed(description=box(text), color=author.color)
            em.set_author(name="Vos aides journalières", icon_url=author.avatar_url)
            em.set_footer(text=f"Nouveau solde · {await self.get_balance(author)}{currency}")
        else:
            em = discord.Embed(description="**Vous n'avez aucune aide à récupérer**", color=author.color)
            em.set_author(name="Vos aides journalières", icon_url=author.avatar_url)
        await ctx.reply(embed=em, mention_author=False)
    
    @commands.command(name="leaderboard", aliases=["lb"])
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def display_leaderboard(self, ctx, top: int = 20):
        """Affiche le top des membres les plus riches du serveur

        Vous pouvez modifier la longueur du top en précisant le paramètre `top`"""
        lbd = await self.get_leaderboard(ctx.guild, top)
        if lbd:
            tbl = []
            found = False
            mn = 1
            for acc in lbd:
                rankn = str(mn) if mn not in MEDALS else f'{mn} {MEDALS[mn]}'
                tbl.append([rankn, str(acc.member.display_name), acc.balance])
                if acc.member == ctx.author:
                    found = True
                mn += 1
            em = discord.Embed(color=await self.bot.get_embed_color(ctx.channel),
                               description=box(tabulate(tbl, headers=["Rang", "Membre", "Solde"])))
            if not found:
                em.add_field(name="Votre rang",
                             value=box("#" + str(await self.get_leaderboard_member_rank(ctx.author)) +
                                       f" ({int(await self.get_account(ctx.author))})"))
            em.set_author(name=f"Top des plus riches de {ctx.guild.name}", icon_url=ctx.guild.icon_url)
            em.set_footer(text=f"Crédits en circulation : {await self.guild_total_credits(ctx.guild)}{await self.get_currency(ctx.guild)}")
            try:
                await ctx.send(embed=em)
            except HTTPException:
                await ctx.send("**Erreur** • Le top est trop grand pour être affiché, utilisez une "
                               "valeur de `top` plus réduite")
        else:
            await ctx.send("Il n'y a aucun top à afficher car aucun membre ne possède de crédits.")
    
    @commands.command(name="redeem")
    @commands.guild_only()
    async def redeem_code(self, ctx, code: str):
        author, guild = ctx.author, ctx.guild
        currency = await self.get_currency(ctx.guild)
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        try:
            value = await self.get_giftcode(guild, code)
        except:
            return await ctx.send("**Code invalide** • Ce code n'est pas valide sur ce serveur")
        else:
            async with ctx.typing():
                await ctx.message.delete()
                
                em = discord.Embed(title="Contenu du code", description=box(humanize_number(value) + currency, lang='css'), color=author.color)
                em.set_footer(text="› Récupérer ?")
                msg = await ctx.send(embed=em)
            
            emojis = [conf, stop]

            start_adding_reactions(msg, emojis)
            try:
                react, _ = await self.bot.wait_for("reaction_add",
                                                        check=lambda r, u: u == ctx.author and r.message.id == msg.id,
                                                        timeout=30)
            except asyncio.TimeoutError:
                emoji = stop
            else:
                emoji = react.emoji
                
            if emoji == conf:
                await self.delete_giftcode(guild, code)
                await self.deposit_credits(author, value, desc="Code cadeau récupéré")
                em.set_footer(text=f"{value}{currency} ont été transférés sur votre compte")
                await msg.edit(embed=em)
            
            else:
                em.set_footer(text=f"Le contenu n'a pas été transféré sur votre compte")
                await msg.edit(embed=em)
                await msg.delete(delay=10)
                
    @commands.command(name='giftcode')
    @checks.admin_or_permissions(manage_messages=True)
    async def create_code(self, ctx, value: int, codename: str = None):
        """Créer un code de récompense de crédits
        
        Si aucun nom pour le code n'est donné, génère un code aléatoire de 8 caractères"""
        guild = ctx.guild
        currency = await self.get_currency(ctx.guild)
        codename = codename if codename else ''.join(random.sample(string.ascii_letters + string.digits, k=8))
        try:
            await self.get_giftcode(guild, codename)
        except:
            pass
        else:
            return await ctx.send("**Code préexistant** • Un code actif identique existe déjà")
        
        code = await self.create_giftcode(ctx.guild, codename, value)
        em = discord.Embed(description=f"**Code :** ||{code}||\n__Contient :__ {value:+}{currency}", timestamp=ctx.message.created_at)
        em.set_footer(text="Un membre peut en récupérer le contenu avec ;redeem")
        try:
            await ctx.author.send(embed=em)
        except:
            await ctx.reply(embed=em)
        else:
            await ctx.reply("**Code créé** • Le reçu vous a été envoyé par MP pour raisons de sécurité")
        
    @commands.command(name='editbalance', aliases=['bedit'])
    @checks.admin_or_permissions(manage_messages=True)
    async def edit_balance(self, ctx, member: discord.Member, modif: str = None, *, reason: str = None):
        """Modifier manuellement le solde d'un membre
        
        Ne rien mettre permet de consulter le solde du membre
        
        __Opérations :__
        `X` = Mettre le solde du membre à X
        `+X` = Ajouter X crédits au solde du membre
        `-X` = Retirer X crédits au solde du membre"""
        if not modif:
            return await ctx.send(f"**Info** • Le solde de {member.name} est de **{await self.get_balance(member)}**{await self.get_currency(ctx.guild)}")
        
        reason = f'Mod. {ctx.author.name} › {reason}' if reason else f'Modification par {ctx.author.name}'
        adding = modif[0] == '+'
        try:
            val = int(modif)
        except:
            return await ctx.send("**Valeur invalide** • Le solde doit être un nombre entier")
            
        if val < 0:
            try:
                await self.withdraw_credits(member, val, desc=reason)
            except:
                return await ctx.send("**Erreur** • Le membre ne possède pas autant de crédits")
        elif adding:
            try:
                await self.deposit_credits(member, val, desc=reason)
            except:
                return await ctx.send("**Erreur** • Impossible d'ajouter cette somme au solde du membre")
        else:
            await self.set_balance(member, val, desc=reason)
        
        await ctx.reply(f"**Solde de {member.mention} modifié** · {modif}{await self.get_currency(ctx.guild)}", mention_author=False)
        
        
# PARAMETRES ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    @commands.group(name="bankset", aliases=["bset"])
    async def bank_settings(self, ctx):
        """Paramètres de l'économie virtuelle du serveur"""
        
    @bank_settings.command(name='currency', aliases=['monnaie'])
    @checks.admin_or_permissions(manage_messages=True)
    async def set_bank_currency(self, ctx, monnaie: str):
        """Changer le symbole utilisé pour la monnaie sur le serveur"""
        guild = ctx.guild
        try:
            await self.config.guild(guild).Currency.set_raw(monnaie)
        except ValueError as e:
            await ctx.send(f"**Erreur** • `{e}`")
        else:
            await ctx.send(f"**Changement réalisé** • Le nouveau symbole de la monnaie sera \"{monnaie}\"")
            
    @bank_settings.command(name='incomebase')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_income_base(self, ctx, value: int = 100):
        """Modifier la base d'aide journalière"""
        guild = ctx.guild
        if value >= 0:
            await self.config.guild(guild).Income.set_raw('Base', value=value)
            curr = await self.get_currency(guild)
            if value > 0:
                await ctx.send(f"**Somme modifiée** • L'aide de base est désormais de {value}{curr} par jour")
            else:
                await ctx.send(
                    "**Bonus désactivé** • Les membres ne pourront plus demander un bonus quotidien de crédits")
        else:
            await ctx.send(
                "**Impossible** • La valeur du bonus doit être positif, ou nulle si vous voulez désactiver la fonctionnalité")
    
    @bank_settings.command(name='baselimit')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_income_limit(self, ctx, limite: int = 100000):
        """Modifier la limite au delà de laquelle le bot ne donnera plus l'aide de base au membre"""
        guild = ctx.guild
        if limite >= 0:
            await self.config.guild(guild).Income.set_raw('BaseLimit', value=limite)
            if limite > 0:
                await ctx.send(f"**Limite modifiée** • Les membres seront au dessus de {limite} crédits n'auront plus l'aide journalière de base")
            else:
                await ctx.send(
                    "**Limite désactivé** • Les revenus seront distribués à tous les membres peu importe leur richesse")
        else:
            await ctx.send(
                "**Impossible** • La valeur de la limite doit être positive, ou nulle si vous voulez désactiver la fonctionnalité")
            
    @bank_settings.command(name='incomeboost')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_income_boost(self, ctx, value: int = 50):
        """Modifier le bonus attribué aux boosters du serveur"""
        guild = ctx.guild
        if value >= 0:
            await self.config.guild(guild).Income.set_raw('Booster', value=value)
            curr = await self.get_currency(guild)
            if value > 0:
                await ctx.send(f"**Somme modifiée** • L'aide bonus pour les boosters est désormais de {value}{curr} par jour")
            else:
                await ctx.send(
                    "**Bonus désactivé** • Les boosters du serveur n'auront pas de crédits supplémentaires")
        else:
            await ctx.send(
                "**Impossible** • La valeur du bonus doit être positif, ou nulle si vous voulez désactiver la fonctionnalité")
            
    @bank_settings.command(name='incomelow')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_income_low_balance(self, ctx, value: int = 50):
        """Modifier le bonus attribué aux membres aux soldes faibles"""
        guild = ctx.guild
        if value >= 0:
            await self.config.guild(guild).Income.set_raw('LowBalance', value=value)
            curr = await self.get_currency(guild)
            if value > 0:
                await ctx.send(f"**Somme modifiée** • L'aide bonus pour les membres aux soldes faibles est désormais de {value}{curr} par jour")
            else:
                await ctx.send(
                    "**Bonus désactivé** • Les membres aux soldes faibles du serveur n'auront pas de crédits supplémentaires")
        else:
            await ctx.send(
                "**Impossible** • La valeur du bonus doit être positif, ou nulle si vous voulez désactiver la fonctionnalité")
            
    @bank_settings.command(name='lowlimit')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_income_low_limit(self, ctx, limite: int = 1000):
        """Modifier la limite au delà de laquelle le bot ne donnera plus de bonus de solde faible"""
        guild = ctx.guild
        if limite >= 0:
            await self.config.guild(guild).Income.set_raw('LowBalanceLimit', value=limite)
            if limite > 0:
                await ctx.send(f"**Limite modifiée** • Les membres seront considérés de soldes faibles lorsqu'ils seront en dessous de {limite} crédits")
            else:
                await ctx.send(
                    "**Bonus désactivé** • Les membres aux soldes faibles ne pourront plus obtenir un bonus quotidien supplémentaire")
        else:
            await ctx.send(
                "**Impossible** • La valeur de la limite doit être positive, ou nulle si vous voulez désactiver la fonctionnalité")
            
            
    @bank_settings.command(name='transferfee')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_transfer_fee(self, ctx, ratio: float = 0.05):
        """Modifier le % (entre 0 et 1 non compris) que représente les frais sur un transfert lorsqu'il n'est pas offert"""
        guild = ctx.guild
        if 0 <= ratio < 1:
            await self.config.guild(guild).Settings.set_raw('TransferFee', value=ratio)
            if ratio > 0:
                await ctx.send(f"**Frais modifiés** • Les transferts seront taxés de {round(ratio * 100, 1)}%")
            else:
                await ctx.send(
                    "**Frais désactivés** • Les transferts ne seront jamais taxés")
        else:
            await ctx.send(
                "**Impossible** • Le ratio doit être positif, ou nulle si vous voulez désactiver la fonctionnalité")
            
    @bank_settings.command(name='freetransfers')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_transfer_free(self, ctx, value: int = 3):
        """Modifier le nombre de transferts offerts par semaine"""
        guild = ctx.guild
        if 0 <= value:
            await self.config.guild(guild).Settings.set_raw('FreeTransfersPerWeek', value=value)
            if value > 0:
                await ctx.send(f"**Fonctionnalité modifiée** • Il y aura {value} transferts offerts par semaine [Lundi - Dimanche]")
            else:
                await ctx.send(
                    "**Fonctionnalitée désactivée** • Les transferts seront toujours taxés")
        else:
            await ctx.send(
                "**Impossible** • Le nombre doit être positif, ou nul si vous voulez désactiver la fonctionnalité")
        
        
    @bank_settings.command(name="resetuser")
    @checks.admin_or_permissions(manage_messages=True)
    async def _bank_reset_account(self, ctx, user: discord.Member):
        """Reset les données bancaires d'un membre (cache compris)"""
        await self.config.member(user).clear()
        await ctx.send(f"**Succès** • Le compte de {user.mention} a été réinitialisé")
        
    @bank_settings.command(name="resetday")
    @checks.admin_or_permissions(manage_messages=True)
    async def _bank_reset_income_day(self, ctx, user: discord.Member):
        """Reset seulement les données du jour de récolte du revenu"""
        await self.config.member(user).Config.clear_raw('day')
        await ctx.send(f"**Succès** • Le jour de récolte du revenu de {user.mention} a été réinitialisé")
        
    @bank_settings.command(name="resetweek")
    @checks.admin_or_permissions(manage_messages=True)
    async def _bank_reset_income_day(self, ctx, user: discord.Member):
        """Reset seulement les données de semaine du calcul des frais de transfert"""
        await self.config.member(user).Config.clear_raw('week')
        await ctx.send(f"**Succès** • La semaine de transferts offerts de {user.mention} a été réinitialisée")

    @bank_settings.command(name="resetcache")
    @checks.admin_or_permissions(manage_messages=True)
    async def _bank_reset_account_cache(self, ctx, user: discord.Member):
        """Reset les données du cache du compte bancaire du membre

        Cela réinitialise les bonus et malus"""
        await self.config.member(user).Config.clear()
        await ctx.send(f"**Succès** • Le cache du compte de {user.mention} a été réinitialisé")

    