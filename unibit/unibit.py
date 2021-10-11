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

logger = logging.getLogger("red.RedX.UniBit")


class AssetItem:
    def __init__(self, raw_data):
        self._raw = raw_data
        self.type = type(raw_data)
    
    def one_liner_repr(self):
        types_map = {
            str: f"`{self._raw if len(self._raw) <= 200 else self._raw[:197] + '...'}`",
            int: f"`{self._raw}`",
            float: f"`{self._raw}`",
            list: f"[{' '.join([f'`{i}`' for i in self._raw])}]",
            tuple: f"({' '.join([f'`{i}`' for i in self._raw])})"
        }
        
        if self.type in types_map:
            return types_map[self.type]
        
        if self.type != dict:
            return f"`{repr(self._raw)}"
        
        dict_repr = f"{{{' '.join([f'`{i}:{self._raw[i]}`' for i in self._raw if not i.startswith('_')])}}}"
        return self._raw.get('_repr', dict_repr)
    
    def item_type_name(self):
        types_map = {
            str: 'Texte',
            int: 'Numéral',
            float: 'Numéral',
            list: 'Liste variable',
            tuple: 'Liste invariable'
        }
        
        if self.type in types_map:
            return types_map[self.type]
        
        if self.type != dict:
            return 'inconnu'
        
        return self._raw.get('_type', 'Données brutes')
        
    def __str__(self):
        return self.item_type_name()


class Asset:
    def __init__(self, cog, asset_id: str, asset_data: dict):
        self.id = asset_id
        self._cog = cog
        self._raw = asset_data
        
        self.metadata = self._raw['metadata']
        self.history = self._raw['history']
        
        self.__dict__.update(asset_data)

    def __str__(self):
        return f"{self.id} {str(self.item)}"
    
    def __eq__(self, comp: object):
        return self.id == comp.id
    
    @property
    def owner(self):
        last_log = self.history[-1]
        user = self._cog.bot.get_user(last_log['owner'])
        return user if user else last_log['owner']
    
    @property
    def author(self):
        auth = self.metadata['author']
        user = self._cog.bot.get_user(auth)
        return user if user else auth
    
    @property
    def item(self):
        return AssetItem(self._raw['item'])
    
    @property
    def color(self):
        rng = random.Random(self.id)
        r = lambda: rng.randint(0,255)
        return '#%02X%02X%02X' % (r(),r(),r())
    

class UniBit(commands.Cog):
    """Système global de certificats digitaux"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_global = {
            'Database' : {}
        }

        self.config.register_global(**default_global)
        
    async def generate_uid(self):
        assets = await self.config.Database()
        uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        while uid in assets:
            uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return uid
        
    async def create_asset(self, author: discord.User, item, **extension) -> Asset:
        """Créer un asset global"""
        asset_id = await self.generate_uid()
        asset_data = {
            'metadata': {
                'author': author.id,
                'created_at': time.time()},
            'history': [{'timestamp': time.time(), 'event': f"Création par {author}", 'owner': author.id}],
            'item': item
        }
        asset_data.update(extension)
        
        await self.config.Database.set_raw(asset_id, value=asset_data)
        return Asset(self, asset_id, asset_data)
    
    async def edit_asset(self, asset: Asset, **update) -> Asset:
        """Modifier les données brutes d'un asset"""
        new_data = asset._raw
        new_data.update(update)
        
        await self.config.Database.set_raw(asset.id, value=new_data)
        return Asset(self, asset.id, new_data)
    
    async def delete_asset(self, asset: Asset):
        """Supprimer un asset global"""
        assets = await self.config.Database()
        if asset.id not in assets:
            raise KeyError(f"L'asset {asset.id} n'existe pas")
        
        await self.config.Database.clear_raw(asset.id)  
    
    async def append_asset_event(self, asset: Asset, event: str, owner: discord.User, **attachments) -> Asset:
        """Ajouter une opération à l'asset"""
        ope = {'timestamp': time.time(), 'event': event, 'owner': owner.id}
        ope.update(attachments)
        
        new_history = copy(asset.history)
        new_history.append(ope)
        
        return await self.edit_asset(asset, history=new_history)  
    
    async def remove_asset_event(self, asset: Asset, index: int) -> Asset:
        """Retirer une opération à l'asset"""
        if len(asset.history) <= index:
            raise ValueError(f"Impossible de retirer un log sur ID:{asset.id} à l'index {index}")
        
        new_history = copy(asset.history)
        new_history.remove(asset.history[index])
        
        return await self.edit_asset(asset, history=new_history)
    
    
    async def get_asset(self, asset_id: str) -> Asset:
        """Obtenir les données d'un asset"""
        assets = await self.list_assets()
        for a in assets:
            if a.id == asset_id:
                return a
        return None
    
    async def list_assets(self) -> List[Asset]:
        """Liste tous les assets existants"""
        assets = await self.config.Database()
        return [Asset(self, a, assets[a]) for a in assets]
    
    async def user_assets(self, user: discord.User) -> List[Asset]:
        """Obtenir tous les assets d'un utilisateur"""
        all_assets = await self.list_assets()
        return [asset for asset in all_assets if asset.owner == user]
        
    async def transfer_asset(self, asset: Asset, new_owner: discord.User, **attachments):
        """Transférer un asset de son possesseur actuel à un nouveau propriétaire"""
        if asset.owner == new_owner:
            raise ValueError("Impossible de transférer un asset si le membre source et le nouveau propriétaire sont identiques")
    
        return await self.append_asset_event(asset, f"Transfert {asset.owner} › {new_owner}", new_owner, **attachments)

        
    @commands.group(name='asset', invoke_without_command=True)
    async def assets_data(self, ctx, asset_id: str):
        """Groupe de commandes permettant de consulter les données d'un Asset"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.show_asset_info, asset_id)
    
    @assets_data.command(name='info')
    async def show_asset_info(self, ctx, asset_id: str):
        """Affiche les détails d'un Asset"""
        asset = await self.get_asset(asset_id)
        cross = self.bot.get_emoji(812451214179434551)
        
        if not asset:
            return await ctx.reply(f"{cross} **Asset inconnu** · Aucun asset n'existe sous l'identifiant `{asset_id}`", mention_author=False)
        
        em = discord.Embed(title=f"**Info. sur Asset** · `{asset_id}`", color=asset.color)
        
        mtd = f"**Date de création** · {datetime.now().fromtimestamp(asset.metadata['created_at']).strftime('%d.%m.%Y %H:%M')}\n"
        auth = f"ID:{asset.author}" if type(asset.author) not in (discord.User, discord.Member) else f'{asset.author}'
        usercreate = asset._raw.get('user_created', False)
        mtd += f"**Auteur original** · {auth}{'' if usercreate is False else 'ᵐ'}"
        em.add_field(name="Metadonnées", value=mtd)
        
        em.add_field(name="Propriétaire actuel", value=f"ID:{asset.owner}" if type(asset.owner) not in (discord.User, discord.Member) else f'{asset.owner}')
        
        em.add_field(name="Type d'objet", value=asset.item.item_type_name())
        em.add_field(name="Contenu", value=asset.item.one_liner_repr(), inline=False)
        
        em.set_footer(text="L'historique des opérations est disponible avec ;asset history")
        await ctx.reply(embed=em, mention_author=False)
        
    @assets_data.command(name='history')
    async def show_asset_history(self, ctx, asset_id: str):
        asset = await self.get_asset(asset_id)
        cross = self.bot.get_emoji(812451214179434551)
        
        if not asset:
            return await ctx.reply(f"{cross} **Asset inconnu** · Aucun asset n'existe sous l'identifiant `{asset_id}`", mention_author=False)
        
        embeds = []
        tabl = []
        
        for event in asset.history:
            if len(tabl) < 25:
                date = datetime.now().fromtimestamp(event['timestamp']).strftime('%d.%m.%Y %H:%M')
                owner = self.bot.get_user(event['owner'])
                owner = owner if owner else f"ID:{event['owner']}"
                tabl.append((date, event['event'], owner))
            else:
                em = discord.Embed(title=f"**Historique de l'Asset** · `{asset_id}`", color=asset.color)
                em.description = box(tabulate(tabl, headers=('Date/Heure', 'Event', 'Propriétaire')))
                em.set_footer(text=f"Consultez les infos sur cet asset avec ;asset info {asset_id}")
                embeds.append(em)
                tabl = []
        
        if tabl:
            em = discord.Embed(title=f"**Historique de l'Asset** · `{asset_id}`", color=asset.color)
            em.description = box(tabulate(tabl, headers=('Date/Heure', 'Event', 'Propriétaire')))
            em.set_footer(text=f"Consultez les infos sur cet asset avec ;asset info {asset_id}")
            embeds.append(em)
        
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply(f"{cross} **Aucun historique** · L'asset `{asset_id}` n'a subit aucune opération depuis sa création", mention_author=False)
        
        
    @commands.group(name='wallet', aliases=['bit'], invoke_without_command=True)
    async def manage_unibit(self, ctx, user: discord.User = None):
        """Groupe de commandes permettant d'effectuer des opérations sur les Assets de son porte-monnaie UniBit"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.show_user_assets, user)
    
    @manage_unibit.command(name='user')
    async def show_user_assets(self, ctx, user: discord.User = None):
        """Affiche une liste des Assets possédés
        
        Mentionner un membre permet de consulter son inventaire"""
        user = ctx.author if not user else user
        assets = await self.user_assets(user)
        cross = self.bot.get_emoji(812451214179434551)
        
        if not assets:
            return await ctx.reply(f"{cross} **Inventaire vide** · Cet inventaire d'assets est vide", mention_author=False)
        
        embeds = []
        tabl = []
        
        for asset in assets:
            if len(tabl) < 25:
                tabl.append((asset.id, asset.item.item_type_name()))
            else:
                em = discord.Embed(color=await ctx.embed_color())
                em.set_author(name="Inventaire d'Assets", icon_url=user.avatar_url)
                em.description = box(tabulate(tabl, headers=('ID Asset', 'Objet')))
                em.set_footer(text="Consultez un Asset avec ;asset info <id>")
                embeds.append(em)
                tabl = []
        
        if tabl:
            em = discord.Embed(color=await ctx.embed_color())
            em.set_author(name="Inventaire d'Assets", icon_url=user.avatar_url)
            em.description = box(tabulate(tabl, headers=('ID Asset', 'Objet')))
            em.set_footer(text="Consultez un Asset avec ;asset info <id>")
            embeds.append(em)
        
        await menu(ctx, embeds, DEFAULT_CONTROLS)
        
    @manage_unibit.command(name='give')
    async def give_asset(self, ctx, to: discord.User, asset_id: str):
        """Donner un Asset au membre visé"""
        asset = await self.get_asset(asset_id)
        author = ctx.author
        cross = self.bot.get_emoji(812451214179434551)
        conf = self.bot.get_emoji(812451214037221439)
        
        if not asset:
            return await ctx.reply(f"{cross} **Asset inconnu** · Aucun asset n'existe sous l'identifiant `{asset_id}`", mention_author=False)
        
        if asset.owner != author:
            return await ctx.reply(f"{cross} **Asset non possédé** · L'asset `{asset_id}` existe mais ne vous appartient pas", mention_author=False)
        
        try:
            await self.append_asset_event(asset, f"Transfert à {to}", to)
        except:
            return await ctx.reply(f"{cross} **Erreur dans la transaction** · L'opération n'a pu être effectuée sur l'Asset", mention_author=False)
        
        await ctx.reply(f"{conf} **Opération réalisée** · L'Asset `{asset_id}` a été transféré à {to.mention}")
        
    @manage_unibit.command(name='delete')
    async def delete_user_asset(self, ctx, asset_id: str):
        """Supprimer un de vos Asset
        
        Attention, cette opération est définitive !"""
        asset = await self.get_asset(asset_id)
        author = ctx.author
        cross = self.bot.get_emoji(812451214179434551)
        conf = self.bot.get_emoji(812451214037221439)
        
        if not asset:
            return await ctx.reply(f"{cross} **Asset inconnu** · Aucun asset n'existe sous l'identifiant `{asset_id}`", mention_author=False)
        
        if asset.owner != author:
            return await ctx.reply(f"{cross} **Asset non possédé** · L'asset `{asset_id}` existe mais ne vous appartient pas", mention_author=False)
        
        msg = await ctx.reply(f"**Êtes-vous certain de vouloir effacer l'Asset `{asset_id}` ?**\nCette opération est __irréversible__ !")
        start_adding_reactions(msg, ['✅', '❎'])
        try:
            react, _ = await self.bot.wait_for("reaction_add",
                                                    check=lambda m,
                                                                u: u == ctx.author and m.message.id == msg.id,
                                                    timeout=20)
        except asyncio.TimeoutError:
            pass
        
        if react.emoji == '✅':
            await self.delete_asset(asset)
            await ctx.reply(f"{conf} **Asset {asset_id} supprimé** · Il a été retiré de votre inventaire et n'est plus transmissible", mention_author=False)
        return await msg.delete()
        
        
    @commands.command(name='newasset')
    async def create_new_asset(self, ctx, ctype: str, *content):
        """Créer un Asset manuellement
        
        D'abord, précisez le type de contenu que vous voulez protéger par un Asset
        Ensuite, insérez le contenu de votre Item dans le champ `[content]`
        
        __Contenus supportés :__
        `raw`/`text` = Texte brut tel qu'il a été entré (ou URLs)
        `num` = Valeurs numérales
        `list` = Liste de valeurs (séparer les valeurs par un espace)
        `data` = Données brutes (utiliser le format `key=value` séparés par un espace)"""
        author = ctx.author
        cross = self.bot.get_emoji(812451214179434551)
        conf = self.bot.get_emoji(812451214037221439)
        ctype = ctype.lower()
        
        if not content:
            return await ctx.reply(f"{cross} **Contenu vide** · Il manque un contenu pour créer un Asset", mention_author=False)
        
        if ctype == 'num':
            text = content[0]
            try:
                itemdata = float(text)
            except:
                return await ctx.reply(f"{cross} **Contenu invalide** · Vous avez indiqué un type `num` mais impossible de trouver une valeur numérique dans votre contenu", mention_author=False)
        elif ctype == 'list':
            itemdata = content
        elif ctype == 'data':
            itemdata = {}
            for c in content:
                key, value = c.split('=')
                itemdata[key] = value
        else:
            itemdata = ' '.join(content)
        
        try:
            asset = await self.create_asset(author, itemdata, user_created=True)
        except:
            return await ctx.reply(f"{cross} **Création impossible** · La création d'un Asset a échouée", mention_author=False)
    
        await ctx.reply(f"{conf} **Asset créé** · Votre Asset porte l'identifiant `{asset.id}` et a été déposé dans votre porte-monnaie UniBit (`;wallet`)")
    
    @commands.command(name='supernewasset', aliases=['snasset'])
    @checks.is_owner()
    async def owner_create_new_asset(self, ctx, author: discord.User, ctype: str, *content):
        """Créer un Asset manuellement en prenant la place d'un autre utilisateur (réservé aux personnes qui savent ce qu'ils font)
        
        D'abord, précisez le type de contenu que vous voulez protéger par un Asset
        Ensuite, insérez le contenu de votre Item dans le champ `[content]`
        
        __Contenus supportés :__
        `raw`/`text` = Texte brut tel qu'il a été entré (ou URLs)
        `num` = Valeurs numérales
        `list` = Liste de valeurs (séparer les valeurs par un espace)
        `data` = Données brutes (utiliser le format `key=value` séparés par un espace)"""
        cross = self.bot.get_emoji(812451214179434551)
        conf = self.bot.get_emoji(812451214037221439)
        ctype = ctype.lower()
        
        if not content:
            return await ctx.reply(f"{cross} **Contenu vide** · Il manque un contenu pour créer un Asset", mention_author=False)
        
        if ctype == 'num':
            text = content[0]
            try:
                itemdata = float(text)
            except:
                return await ctx.reply(f"{cross} **Contenu invalide** · Vous avez indiqué un type `num` mais impossible de trouver une valeur numérique dans votre contenu", mention_author=False)
        elif ctype == 'list':
            itemdata = content
        elif ctype == 'data':
            itemdata = {}
            for c in content:
                key, value = c.split('=')
                itemdata[key] = value
        else:
            itemdata = ' '.join(content)
        
        try:
            asset = await self.create_asset(author, itemdata)
        except:
            return await ctx.reply(f"{cross} **Création impossible** · La création d'un Asset a échouée", mention_author=False)
    
        await ctx.reply(f"{conf} **Asset créé** · Votre Asset porte l'identifiant `{asset.id}` et a été déposé dans votre porte-monnaie UniBit (`;wallet`)")