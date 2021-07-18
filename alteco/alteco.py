import logging
import random
import asyncio
import time
import string
from copy import copy
from datetime import datetime, timedelta
import re

import discord
from discord.errors import HTTPException
from typing import Union, List, Literal

from redbot.core import Config, commands, checks
from redbot.core.utils import AsyncIter
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box, humanize_number
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate

logger = logging.getLogger("red.RedX.AltEco")


class AltEcoAccount:
    def __init__(self, member: discord.Member, balance: int, logs: list, config: dict):
        self.member, self.guild = member, member.guild
        self.balance = balance
        self.logs = logs
        self.config = config

    def __str__(self):
        return self.user.mention

    def __int__(self):
        return self.balance


class AltEcoOperation:
    def __init__(self, member: discord.Member, delta: int, timestamp: Union[float, int], **info):
        self.member = member
        self.guild = member.guild
        self.delta = delta
        self.timestamp = timestamp
        self.info = info

    def __str__(self):
        return self.description

    def __int__(self):
        return self.delta

    def formatted_date(self):
        return datetime.now().fromtimestamp(self.timestamp).strftime('%d/%m/%Y %H:%M')

    def formatted_time(self):
        return datetime.now().fromtimestamp(self.timestamp).strftime('%H:%M')
    
    @property
    def uid(self):
        return f'{int(self.timestamp)}{self.delta:+}'
    
    @property
    def description(self):
        poss_desc = [k for k in self.info if k in ('description', 'desc', 'reason')]
        if poss_desc:
            return self.info[poss_desc[0]]
        return '...'
    

class AltEco(commands.Cog):
    """Système d'économie virtuelle alternatif"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {'balance': 0,
                          'logs': [],
                          'config': {
                              'logs_expiration': 86400,
                              'variation_period': 86400,
                              'bonus_base': '',
                              'bonus_boost': '',
                              'bonus_beginner': ''
                              },
                          }

        default_guild = {'Currency': {'string': 'C',
                                      'emoji': None},
                         'DailyBonus': {'base': 100,
                                        'boost': 100},
                         'Redeemables': {}}
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        
    
    async def migrate_from_finance(self):
        """Tente l'importation des données depuis l'ancien module économique Finance"""
        try:
            finance_config = Config.get_conf(None, identifier=736144321857978388, cog_name="Finance")
            guilds = self.bot.guilds
            n = 1
            for guild in guilds:
                logger.info(msg=f"{n} Importation des données Finance de : {guild.name}")
                old_data = await finance_config.guild(guild).all()
                await self.config.guild(guild).Currency.set_raw('string', value=old_data['currency'])
                await self.config.guild(guild).DailyBonus.set({'base': old_data['daily_bonus'], 'boost': old_data['booster_bonus']})

                for member in guild.members:
                    user_old = await finance_config.member(member).all()
                    await self.config.member(member).balance.set(user_old['balance'])
                    await self.config.member(member).config.set_raw('bonus_base', value=user_old['config']['daily_bonus'])
                    await self.config.member(member).config.set_raw('bonus_boost', value=user_old['config']['daily_bonus'])

                n += 1
        except:
            return False
        return True
        

# Banque et serveur ---------------------

    async def get_currency(self, guild: discord.Guild):
        """Renvoie les informations de monnaie du serveur"""
        return await self.config.guild(guild).Currency.get_raw('string') #TODO : Support de l'emoji
    
    async def get_leaderboard(self, guild: discord.Guild, top_cutoff: int = None) -> List[AltEcoAccount]:
        """Renvoie le top des membres les plus riches du serveur (liste d'objets AltEcoAccount)

        Renvoie une liste vide si aucun top n'est générable"""
        users = await self.config.all_members(guild)
        sorted_users = sorted(list(users.items()), key=lambda u: u[1]['balance'], reverse=True)
        top = []
        for uid, acc in sorted_users:
            user = guild.get_member(uid)
            if user:
                top.append(AltEcoAccount(user, **acc))
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
        return sum([users[u]['balance'] for u in users])

    
# Compte personnel ----------------------

    async def get_account(self, member: discord.Member) -> AltEcoAccount:
        """Renvoie les informations bancaires d'un membre"""
        raw = await self.config.member(member).all()
        return AltEcoAccount(member, **raw)
    
    async def get_balance(self, member: discord.Member) -> int:
        """Renvoie le solde brut d'un membre"""
        return await self.config.member(member).get_raw('balance')
    
    async def check_balance(self, member: discord.Member, cost: int) -> bool:
        """Vérifie si une opération est faisable"""
        return await self.get_balance(member) >= cost
    
    async def set_balance(self, member: discord.Member, value: int, **info) -> int:
        """Modifie le solde du membre"""
        if value < 0:
            raise ValueError("La valeur du solde ne peut être négative")
        
        current = await self.get_balance(member)
        await self.config.member(member).balance.set(value)
        
        await self.attach_log(member, value - current, **info)
        
        return value
    
    async def deposit_credits(self, member: discord.Member, value: int, **info) -> int:
        """Ajouter des crédits au solde d'un membre"""
        if value < 0:
            raise ValueError("Impossible d'ajouter une valeur négative au solde")
        
        current = await self.get_balance(member)
        return await self.set_balance(member, current + value, **info)
    
    async def withdraw_credits(self, member: discord.Member, value: int, **info) -> int:
        """Retirer des crédits du solde d'un membre"""
        value = abs(value)
        
        current = await self.get_balance(member)
        return await self.set_balance(member, current - value, **info)
    
    async def get_balance_variation(self, member: discord.Member, period: int = None) -> int:
        """Calculer la variation du solde sur une période"""
        if not period:
            period = await self.config.member(member).config.get_raw('variation_period')
        
        diff = time.time() - period
        logs = await self.config.member(member).logs()
        delta = 0
        for l in logs:
            if l['timestamp'] >= diff: 
                delta += l['delta']
                
        return delta
        
        
# Logging ------------------------------
    
    async def get_logs(self, member: discord.Member) -> List[AltEcoOperation]:
        """Renvoie les logs formattés d'un membre"""
        raw = await self.clear_logs(member)
        logs = []
        for l in raw:
            logs.append(AltEcoOperation(member, **l))
        return logs

    async def attach_log(self, member: discord.Member, delta: int, **info) -> AltEcoOperation:
        """Ajouter un log d'une opération"""
        log = {'delta': delta, 'timestamp': time.time()}
        log.update(info)
        
        async with self.config.member(member).logs() as logs:
            logs.append(log)
        await self.clear_logs(member)
        
        return AltEcoOperation(member, **log)
    
    async def remove_log(self, member: discord.Member, uid: str) -> None:
        """Retire un log à partir de son UID"""
        logs = await self.clear_logs(member)
        async with self.config.member(member).logs() as raw_logs:
            for l in logs:
                if f"{l['timestamp']}{l['delta']:+}" == uid:
                    raw_logs.remove(l)
    
    async def clear_logs(self, member: discord.Member, exp: int = None) -> list:
        """Supprime les logs du membre ayant expiré"""
        if not exp:
            exp = await self.config.member(member).config.get_raw('logs_expiration')
        
        current_logs = await self.config.member(member).logs()
        new_logs = copy(current_logs)
        for l in current_logs:
            if l['timestamp'] + exp <= time.time():
                new_logs.remove(l)
        
        await self.config.member(member).logs.set(new_logs)
        return new_logs
    
    
# Codes ---------------------------------------
    
    def get_random_code(self, n: int = 8):
        return ''.join(random.sample(string.ascii_letters + string.digits, k=n))
    
    async def create_redeemable(self, guild: discord.Guild, code: str = None, **content):
        """Créer un code échangeable contre un contenu"""
        redms = await self.config.guild(guild).Redeemables()
        code = code if code else self.get_random_code()
        
        if code in redms:
            raise ValueError(f"Le code {code} existe déjà dans les redeemables de ce serveur")
        await self.config.guild(guild).Redemmables.set_raw(code, value=content)
        return code
    
    async def delete_redeemable(self, guild: discord.Guild, code: str):
        """Effacer un code échangeable"""
        redms = await self.config.guild(guild).Redeemables()
        
        if code not in redms:
            raise ValueError(f"Le code {code} n'existe pas dans les redeemables de ce serveur")
        await self.config.guild(guild).Redemmables.clear_raw(code)
    
    async def get_redeemable(self, guild: discord.Guild, code: str, *, delete_after_use: bool = False):
        """Récupérer un code échangeable"""
        redms = await self.config.guild(guild).Redeemables()
        
        if code not in redms:
            raise ValueError(f"Le code {code} n'existe pas dans les redeemables de ce serveur")
        
        content = redms[code]
        if delete_after_use:
            await self.delete_redeemable(guild, code)
            
        return content
    
    
# Reset Config ------------------------------------
    
    async def wipe_logs(self, member: discord.Member) -> None:
        """Supprime tous les logs d'un membre"""
        await self.config.member(member).clear_raw('logs')

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
                
                
    # Utiles --------------------------------------
    
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
    
                
# Commandes principales ---------------------------

    @commands.command(name="bank", aliases=['b'])
    @commands.guild_only()
    async def account_info(self, ctx, member: discord.Member = None):
        """Afficher un récapitulatif de ses informations bancaires
        
        Le temps sur lequel est calculé la variation ainsi que la durée de conservation des logs est modifiable avec le groupe de commandes `bset`"""
        user = member if member else ctx.author
        guild = ctx.guild
        account = await self.get_account(user)
        currency = await self.get_currency(guild)
        
        em = discord.Embed(color=user.color, timestamp=ctx.message.created_at)
        if user == member:
            em.set_author(name=f"Votre compte", icon_url=user.avatar_url)
        else:
            em.set_author(name=f"Compte de {user.name}", icon_url=user.avatar_url)
            
        fmt_balance = humanize_number(account.balance)
        em.add_field(name="Solde", value=box(f"{fmt_balance} {currency}"))
        
        var = await self.get_balance_variation(user)
        vartime = round(await self.config.member(user).config.get_raw('variation_period') / 3600)
        em.add_field(name=f"Variation ({vartime}h)", value=box(f"{var:+}", lang='fix' if var < 0 else 'css'))
        
        rank = await self.get_leaderboard_member_rank(user)
        em.add_field(name="Rang", value=box(f"#{rank}", lang='css'))
        
        logs = await self.get_logs(user)
        if logs:
            txt = "\n".join([f"{log.delta:+} · {log.description[:50]}" for log in logs][::-1][:5])
            em.add_field(name=f"Dernières opérations", value=box(txt), inline=False)
        
        em.set_footer(text=f"Sur {guild.name}")
        await ctx.reply(embed=em, mention_author=False)
        
    @commands.command(name="give")
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.member)
    async def give_credits(self, ctx, member: discord.Member, sum: int, *, reason: str = ''):
        """Donner des crédits au membre visé
        
        Une raison peut être précisée après la somme"""
        author = ctx.author
        guild = ctx.guild
        currency = await self.get_currency(guild)
        
        try:
            await self.withdraw_credits(author, sum, desc=f'Don à {member.name}')
        except:
            return await ctx.reply(f"**Don impossible** • Vous n'avez pas {sum}{currency} sur votre compte")
        else:
            await self.deposit_credits(member, sum, desc=f'Don reçu de {author.name}' if not reason else f'{author.name} > {reason}')
            await ctx.reply(f"**Don effectué** • {member.mention} a reçu {sum}{currency} de votre part")
                
    @commands.command(name="operations", aliases=['opes'])
    @commands.guild_only()
    async def display_account_operations(self, ctx, member: discord.Member = None):
        """Affiche les logs du compte du membre, ou vous-même à défaut
        
        Les logs sans description s'afficheront avec `...`
        La durée de conservation des logs est modifiable avec le groupe de commandes `bset`"""
        user = member if member else ctx.message.author

        logs = await self.get_logs(user)
        periode = await self.config.member(user).config.get_raw('variation_period')
        if not logs:
            return await ctx.reply(f"**Aucune opération** • Il n'y a aucune opération enregistrée sur ce compte dans les dernières {round(periode / 3600)} heures",
                                   mention_author=False)

        embeds = []
        tabl = []
        for log in logs[::-1]:
            if len(tabl) < 20:
                tabl.append((log.formatted_time(), f"{log.delta:+}", f"{log.description[:50]}"))
            else:
                em = discord.Embed(color=user.color, description=box(tabulate(tabl, headers=["Heure", "Opération", "Description"])))
                em.set_author(name=f"Historique des opérations de {user.name}", icon_url=user.avatar_url)
                em.set_footer(text=f"Période : dernières {round(periode / 3600)}h")
                embeds.append(em)
                tabl = []

        if tabl:
            em = discord.Embed(color=user.color, description=box(tabulate(tabl, headers=["Heure", "Opération", "Description"])))
            em.set_author(name=f"Historique des opérations de {user.name}", icon_url=user.avatar_url)
            em.set_footer(text=f"Période : dernières {round(periode / 3600)}h")
            embeds.append(em)

        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply(f"**Aucune opération** • Il n'y a aucune opération enregistrée sur ce compte dans les dernières {round(periode / 3600)} heures",
                                   mention_author=False)
            
    @commands.command(name="bonus", aliases=['rj'])
    @commands.guild_only()
    async def get_daily_bonus(self, ctx):
        """Recevoir ses revenus journaliers
        
        __**Revenus possibles**__
        - Revenu de base : pour tous, défini par les modérateurs
        - Revenu de boost : pour les boosters du serveur, défini par les modérateurs
        - Revenu d'aide : pour ceux qui ont un solde <= revenu de base * 5, moitié d'un revenu de base"""
        author = ctx.author
        today = datetime.now().strftime("%Y.%m.%d")
        account = await self.get_account(author)
        currency = await self.get_currency(ctx.guild)
        
        txt = ''
        total = 0
        bonus = await self.config.guild(ctx.guild).DailyBonus()
        if bonus['base'] and account.config['bonus_base'] != today:
            await self.config.member(author).config.set_raw('bonus_base', value=today)
            total += bonus['base']
            txt += f"+{bonus['base']} · Base de revenu journalier\n"
            
        if bonus['boost'] and account.config['bonus_boost'] != today:
            await self.config.member(author).config.set_raw('bonus_boost', value=today)
            total += bonus['boost']
            txt += f"+{bonus['boost']} · Revenu lié au statut de booster du serveur\n"
            
        if account.balance <= (bonus['base'] * 5) and account.config['bonus_beginner'] != today:
            await self.config.member(author).config.set_raw('bonus_beginner', value=today)
            total += round(bonus['base'] / 2)
            txt += f"+{round(bonus['base'] / 2)} · Revenu supp. d'aide aux soldes faibles\n"
        
        if total: 
            txt += f'————————————\n= {total}{currency}'
            await self.deposit_credits(author, total, desc='Récupération des revenus journaliers')
            em = discord.Embed(description=box(txt), color=author.color)
            em.set_author(name="Vos revenus journaliers", icon_url=author.avatar_url)
            em.set_footer(text=f"Vous avez désormais {await self.get_balance(author)}{currency}")
        else:
            em = discord.Embed(description="**Vous n'avez plus aucun revenu à récupérer pour aujourd'hui**\nRevenez demain !", color=author.color)
            em.set_author(name="Vos revenus journaliers", icon_url=author.avatar_url)
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
            for acc in lbd:
                tbl.append([str(acc.member.display_name), acc.balance])
                if acc.member == ctx.author:
                    found = True
            em = discord.Embed(color=await self.bot.get_embed_color(ctx.channel),
                               description=box(tabulate(tbl, headers=["Membre", "Solde"])))
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
        """Récupérer le contenu d'un code d'économie virtuelle"""
        author, guild = ctx.author, ctx.guild
        
        ContentTrads = {
            'credits' : "Crédits"
        }
        
        try:
            content = await self.get_redeemable(guild, code)
        except:
            return await ctx.send("**Code invalide** • Ce code n'est pas valable sur ce serveur ou provient d'un autre module incompatible")
        else:
            async with ctx.typing():
                await ctx.message.delete()
                txt = ''
                for k in content:
                    txt += f'{ContentTrads[k] if k in ContentTrads else k.title()} · {content[k]}\n'
                    
                em = discord.Embed(title="Contenu du code", description=box(txt), color=author.color)
                em.set_footer(text="🎁 Prendre • ❌ Refuser")
                msg = await ctx.send(embed=em)
            
            emojis = ["🎁", "❌"]

            start_adding_reactions(msg, emojis)
            try:
                react, user = await self.bot.wait_for("reaction_add",
                                                        check=lambda r, u: u == ctx.author and r.message.id == msg.id,
                                                        timeout=30)
            except asyncio.TimeoutError:
                emoji = '❌'
            else:
                emoji = react.emoji
                
            if emoji == '🎁':
                await self.delete_redeemable(guild, code)
                em.set_footer("✅ Le contenu du code a été transféré sur votre compte")
                await msg.edit(embed=em)
            
            else:
                em.set_footer("❌ Le contenu n'a pas été transféré sur votre compte")
                await msg.edit(embed=em)
                await msg.delete(delay=15)
                
    @commands.command(name='giftcode')
    @checks.admin_or_permissions(manage_messages=True)
    async def create_code(self, ctx, value: int, opt_code: str = None):
        """Créer un code de récompense de crédits
        
        Si aucun nom pour le code n'est donné, génère un code aléatoire de 8 caractères"""
        if opt_code:
            try:
                await self.get_redeemable(ctx.guild, opt_code)
            except:
                pass
            else:
                return await ctx.send("**Code préexistant** • Un code actif identique existe déjà")
        
        code = await self.create_redeemable(ctx.guild, opt_code if opt_code else None, credits=value)
        em = discord.Embed(title="Code créé", description=box(str(code)), timestamp=ctx.message.created_at)
        em.add_field(name="Contenu", value=box(f"Crédits : {value:+}"))
        em.set_footer(text="Un membre peut en récupérer le contenu avec ;redeem")
        await ctx.author.send(embed=em)
                
                
    @commands.command(name='editbalance', aliases=['editb'])
    @checks.admin_or_permissions(manage_messages=True)
    async def edit_balance(self, ctx, member: discord.Member, modif: str = None):
        """Modifier manuellement le solde d'un membre
        
        Ne rien mettre permet de consulter le solde du membre
        
        __Opérations :__
        `X` = Mettre le solde du membre à X
        `+X` = Ajouter X crédits au solde du membre
        `-X` = Retirer X crédits au solde du membre"""
        if not modif:
            return await ctx.send(f"**Info** • Le solde de {member.name} est de **{await self.get_balance(member)}**{await self.get_currency(ctx.guild)}")
        
        adding = modif[0] == '+'
        try:
            val = int(modif)
        except:
            return await ctx.send("**Valeur invalide** • Le solde doit être un nombre entier")
            
        if val < 0:
            try:
                await self.withdraw_credits(member, val, desc=f"Modification de solde par {ctx.author}")
            except:
                return await ctx.send("**Erreur** • Le membre ne possède pas autant de crédits")
        elif adding:
            try:
                await self.deposit_credits(member, val, desc=f"Modification de solde par {ctx.author}")
            except:
                return await ctx.send("**Erreur** • Impossible d'ajouter cette somme au solde du membre")
        else:
            await self.set_balance(member, val, desc=f"Modification de solde par {ctx.author}")
        
        await ctx.reply(f"Le solde de {member.mention} a été modifié : **{modif}**{await self.get_currency(ctx.guild)}", mention_author=False)
    
    
    
# Commandes de paramètres -------------------------
        
    @commands.group(name="bankset", aliases=["bset"])
    async def eco_settings(self, ctx):
        """Commandes de gestion de l'économie virtuelle du serveur"""
        
    @eco_settings.command(name='logsexp')
    async def set_logs_life(self, ctx, hours: int = 24):
        """Modifie le nombre d'heures que les logs sont conservées, min 1h - max 72h
        
        Par défaut 24h"""
        if hours < 1:
            return await ctx.send("**Invalide** • Les logs doivent être conservés au minimum 1h")
        if hours > 72:
            return await ctx.send("**Invalide** • Les logs ne peuvent être conservés qu'au maximum 72h")
        
        secs = hours * 3600
        await self.config.member(ctx.author).config.set_raw('logs_expiration', value=secs)
        await ctx.reply(f"**Modifiée** • Vos logs seront désormais conservés {hours}h", mention_author=False)
    
    @eco_settings.command(name='varperiod')
    async def set_variation_period(self, ctx, hours: int = 24):
        """Modifie le temps (en heures) sur lequel est calculé la variation de votre solde
        
        Ceci se base sur les logs, si la valeur est supérieure à l'expiration de ceux-ci les résultats seront systématiquement incomplets
        Par défaut 24h"""
        if hours < 1:
            return await ctx.send("**Invalide** • La variation ne peut être calculée au minimum sur une période d'une heure")
        if hours > 72:
            return await ctx.send("**Invalide** • La variation du solde ne peut être calculée sur plus de 72h")
        
        secs = hours * 3600
        await self.config.member(ctx.author).config.set_raw('variation_period', value=secs)
        await ctx.reply(f"**Modifiée** • La variation de votre solde sur votre profil bancaire sera calculée sur {hours}h", mention_author=False)
        
    @eco_settings.command(name='currency', aliases=['monnaie'])
    @checks.admin_or_permissions(manage_messages=True)
    async def set_bank_currency(self, ctx, monnaie: str):
        """Changer le symbole utilisé pour la monnaie sur le serveur"""
        guild = ctx.guild
        try:
            await self.config.guild(guild).Currency.set_raw('string', monnaie)
        except ValueError as e:
            await ctx.send(f"**Erreur** • `{e}`")
        else:
            await ctx.send(f"**Changement réalisé** • Le nouveau symbole de la monnaie sera \"{monnaie}\"")
            
    @eco_settings.command(name='dailybase')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_dailybonus_base(self, ctx, value: int = 100):
        """Modifier les crédits donnés avec le bonus quotidien"""
        guild = ctx.guild
        if value >= 0:
            await self.config.guild(guild).DailyBonus.set_raw('base', value=value)
            curr = await self.get_currency(guild)
            if value > 0:
                await ctx.send(f"**Somme modifiée** • Les membres auront le droit à {value}{curr} par jour")
            else:
                await ctx.send(
                    "**Bonus désactivé** • Les membres ne pourront plus demander un bonus quotidien de crédits")
        else:
            await ctx.send(
                "**Impossible** • La valeur du bonus doit être positif, ou nulle si vous voulez désactiver la fonctionnalité")
            
    @eco_settings.command(name='dailyboost')
    @checks.admin_or_permissions(manage_messages=True)
    async def set_dailybonus_boost(self, ctx, value: int = 100):
        """Modifier les crédits donnés en supplément avec le bonus quotidien pour les boosters du serveur"""
        guild = ctx.guild
        if value >= 0:
            await self.config.guild(guild).DailyBonus.set_raw('boost', value=value)
            curr = await self.get_currency(guild)
            if value > 0:
                await ctx.send(f"**Somme modifiée** • Les boosters du serveur auront le droit à {value}{curr} en plus par jour")
            else:
                await ctx.send(
                    "**Bonus désactivé** • Les boosters ne pourront plus obtenir un bonus quotidien supplémentaire")
        else:
            await ctx.send(
                "**Impossible** • La valeur du bonus doit être positif, ou nulle si vous voulez désactiver la fonctionnalité")
        
    @eco_settings.command(name="resetuser")
    @checks.admin_or_permissions(manage_messages=True)
    async def _bank_reset_account(self, ctx, user: discord.Member):
        """Reset les données bancaires d'un membre (cache compris)"""
        await self.config.member(user).clear()
        await ctx.send(f"**Succès** • Le compte de {user.mention} a été réinitialisé")

    @eco_settings.command(name="resetcache")
    @checks.admin_or_permissions(manage_messages=True)
    async def _bank_reset_account_cache(self, ctx, user: discord.Member):
        """Reset seulement les données du cache du compte bancaire du membre

        Cela réinitialise les délais des bonus"""
        await self.config.member(user).config.clear_raw("daily_bonus")
        await ctx.send(f"**Succès** • Le cache du compte de {user.mention} a été réinitialisé")