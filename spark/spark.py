import json
import logging
import operator
import random
import time
import asyncio
from datetime import datetime
from typing import List, Union, Set, Any, Dict
from copy import copy

import discord
from discord.ext import tasks
from discord.ext.commands import Greedy
from fuzzywuzzy import process
from redbot.core import commands, Config, checks
from redbot.core.commands.commands import Command
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, start_adding_reactions
from redbot.core.utils.chat_formatting import box
from tabulate import tabulate

logger = logging.getLogger("red.RedX.Spark")

VERSION = 'BETA'

SPARK_COLOR, SPARK_ICON = 0xFFF859, 'https://i.imgur.com/ks2gkzd.png'

HUMANIZE_TAGS = {
    'ore': "minerai",
    'food': "consommable",
    'equipment': "equipement",
    'misc': "divers"
}
    
FUEL_VALUES = {
    'coal': 20,
    'wood': 7,
    'banane': 3
}

TIER_NAMES = {
                1: 'Commun',
                2: 'Rare',
                3: 'Très rare'
            }
    
class SparkError(Exception):
    """Classe de base pour les erreurs spécifiques à Spark"""
    
class InventoryError(SparkError):
    """Erreurs en rapport avec l'inventaire"""
    
class EquipmentError(SparkError):
    """Erreurs en rapport avec l'équipement"""
    
class ItemNotEquipable(EquipmentError):
    """L'item n'est pas équipable"""
    
class StatusError(SparkError):
    """Erreurs en rapport avec les statuts"""
    

class SparkItem:
    def __init__(self, cog, item_id: str):
        self._cog = cog
        self._raw = cog.items[item_id]
        
        self.id = item_id
        self.name = self._raw['name']
        
        self.value = self._raw.get('value', None)
        self.tags = self._raw.get('tags', [])
        self.details = self._raw.get('details', [])
        self.tier = self._raw.get('tier', 1)
        self.lore = self._raw.get('lore', '')
        self.img = self._raw.get('img', None)
        
        self.default_config = self._raw.get('config', {})
        self.on_use = self._raw.get('on_use', None)
        self.text_on_use = self._raw.get('text_on_use', None)
        self.on_equip = self._raw.get('on_equip', None)
        
    def __str__(self):
        return self.name
    
    def __eq__(self, other: object):
        return self.id == other.id
    
    @property
    def equipable(self):
        return 'equipment' in self.tags
    
    async def guild_value(self, guild: discord.Guild):
        return await self._cog.item_guild_value(guild, self)
    

class Spark(commands.Cog):
    """Simulateur de vie sur une planète inhospitalière"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_user = {
            'TechnicalMode': False
        }

        default_member = {
            'Stamina': 100,
            'Inventory': {},
            'Equipment' : {},
            'Status': 1
        }

        default_guild = {
            'Shop': {
                'data': {},
                'timerange': ''
            },
            'Fire': 100,
            'GroupChests': {},
            'Events': {'channels': [],
                       'events_cooldown': 600,
                       'starting_threshold': 150,
                       'fire_degradation': 2}
        }
        
        default_global = {
            'EventsExpectedDelay': 600,
            'DefaultInventorySlots': 100,
            'DefaultStaminaLimit': 100,
            'StaminaRegenDelay': 300,
            'MaxValueVariance': 0.20,
            'ShopUpdateRange': (6, 22)
        }
        
        self.config.register_user(**default_user)
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        self.cache = {}
        
        self.spark_loop.start()
        
        
# LOOP ____________________________________________________

    @tasks.loop(minutes=1.0)
    async def spark_loop(self):
        all_guilds = await self.config.all_guilds()
        timerange = datetime.now().strftime('%H%j')
        for g in all_guilds:
            if all_guilds[g]['Shop'].get('timerange', '') != timerange:
                guild = self.bot.get_guild(g)
                await self.update_shop(guild)
                logger.info(f"Boutique de {guild.name} mise à jour")
                await self.config.guild(guild).Shop.set_raw('timerange', value=timerange)
                
                firedeg = all_guilds[g]['Events'].get('fire_degradation', 1)
                await self.config.guild(guild).Fire.set(max(0, all_guilds[g]['Fire'] - firedeg))

    @spark_loop.before_loop
    async def before_spark_loop(self):
        logger.info('Démarrage de la boucle spark_loop...')
        await self.bot.wait_until_ready()
        
        
# DONNEES ____________________________

    # Se charge avec __init__.py au chargement du module
    def _load_bundled_data(self):
        items_path = bundled_data_path(self) / 'items.json'
        with items_path.open() as json_data:
            self.items = json.load(json_data)
        logger.info("Items Spark chargés")
        
        shops_path = bundled_data_path(self) / 'shops.json'
        with shops_path.open() as json_data:
            self.shops = json.load(json_data)
        logger.info("Boutiques Spark chargées")
    
    
# ITEMS ______________________________

    def get_item(self, item_id: str) -> SparkItem:
        if not item_id in self.items:
            raise KeyError(f"{item_id} n'est pas un item valide")
        
        return SparkItem(self, item_id)
    
    def get_items_by_tags(self, *tags: str) -> List[SparkItem]:
        items = []
        for i in self.items:
            for l in self.items[i].get('tags', []):
                if l.lower() in tags:
                    items.append(self.get_item(i))
        return items

    def fetch_item(self, search: str, custom_list: list = None, *, fuzzy_cutoff: int = 80):
        items = self.items if not custom_list else {i: self.items[i] for i in custom_list if i in self.items}
        search = search.lower()

        if search in items:  # Recherche brute par ID
            return self.get_item(search)

        strict_name = [i for i in items if search == items[i]['name']]  # Recherche brute par nom
        if strict_name:
            return self.get_item(strict_name[0])

        # Fuzzy avec le nom des items
        fuzzy = process.extractOne(search, [items[n]['name'].lower() for n in items], score_cutoff=fuzzy_cutoff)
        if fuzzy:
            return self.get_item([n for n in items if items[n]['name'].lower() == fuzzy[0]][0])

        # Fuzzy avec l'ID
        fuzzyid = process.extractOne(search, list(items.keys()), score_cutoff=fuzzy_cutoff)
        if fuzzyid:
            return self.get_item(fuzzyid[0])

        return None
    
    async def item_guild_value(self, guild: discord.Guild, item: SparkItem):
        if not item.value:
            raise ValueError(f"L'item {item} n'est pas vendable")
        
        minvar = round(item.value * (1 - await self.config.MaxValueVariance()))
        varbase = 0.998 if len(str(item.value)) < 3 else 0.996
        value = item.value
        itempool = 0
        
        chestswith = await self.all_chests_with(guild, item)
        if chestswith:
            chests = await self.config.guild(guild).GroupChests()
            for c in chestswith:
                itempool += chests[c]['content'].get(item.id, 0)
        
        holders = await self.all_inventories_with(guild, item)
        for h in holders:
            itempool += await self.inventory_get(h, item)
            
        if not itempool:
            return value
        
        valuevar = varbase**(itempool / (len(holders)))
        value = round(value * valuevar)
        return max(minvar, value)

    
# INVENTAIRE _________________________

    async def inventory_capacity(self, user: discord.Member) -> int:
        invcap = await self.config.DefaultInventorySlots()
        
        equipeff = await self.equipment_effects(user)
        if 'extend_inventory' in equipeff:
            invcap += sum(equipeff['extend_inventory'])
        
        return invcap

    async def inventory_check(self, user: discord.Member, item: SparkItem, amount: int) -> bool:
        inv = await self.config.member(user).Inventory()
        if amount > 0:
            maxcap = await self.inventory_capacity(user)
            invsum = sum([inv[i] for i in inv])
            return invsum + amount <= maxcap
        elif amount < 0:
            return inv.get(item.id, 0) >= amount
        return True

    async def inventory_edit(self, user: discord.Member, item: SparkItem, amount: int) -> int:
        if amount < 0:
            raise ValueError("La quantité d'un item ne peut être négative")
        
        if amount != 0:
            await self.config.member(user).Inventory.set_raw(item.id, value=amount)
        else:
            try:
                await self.config.member(user).Inventory.clear_raw(item.id)
            except KeyError:
                pass
        return amount
    
    async def inventory_add(self, user: discord.Member, item: SparkItem, amount: int, *, force: bool = False) -> int:
        if amount < 0:
            raise ValueError("Impossible d'ajouter une quantité négative d'items")
        
        if not await self.inventory_check(user, item, amount) and force is False:
            raise InventoryError("L'inventaire ne peut contenir autant d'items")
        
        inv = await self.config.member(user).Inventory()
        return await self.inventory_edit(user, item, inv.get(item.id, 0) + amount)
    
    async def inventory_remove(self, user: discord.Member, item: SparkItem, amount: int) -> int:
        amount = abs(amount)
        
        if not await self.inventory_check(user, item, -amount):
            raise InventoryError("L'inventaire ne contient pas cette quantité de cet item")
        
        inv = await self.config.member(user).Inventory()
        return await self.inventory_edit(user, item, inv.get(item.id, 0) - amount)
    
    async def inventory_get(self, user: discord.Member, item: SparkItem = None) -> Union[dict, int]:
        inv = await self.config.member(user).Inventory()
        if item:
            return inv.get(item.id, 0)
        return inv
    
    async def all_inventories_with(self, guild: discord.Guild, item: SparkItem, *, minimal_amount: int = 1):
        users = await self.config.all_members(guild)
        result = []
        for u in users:
            if users[u]['Inventory'].get(item.id, 0) >= minimal_amount:
                m = guild.get_member(u)
                if m:
                    result.append(m)
        return result
    
    async def inventory_operation_dialog(self, ctx, item: SparkItem, amount: int, *, user: discord.Member = None) -> bool:
        user = user if user else ctx.author
        
        if amount < 0:
            try:
                await self.inventory_remove(user, item, amount)
            except InventoryError:
                qte = await self.inventory_get(user, item)
                await ctx.send(f"**Quantité insuffisante** · L'opération demande {amount}x **{item}** et vous en avez que {qte}")
                return False
            
        else:
            try:
                await self.inventory_add(user, item, amount)
            except InventoryError:
                inv = await self.inventory_get(user)
                invcap = await self.inventory_capacity(user)
                invsum = sum([inv[i] for i in inv])
                
                if invsum < invcap:
                    new_amount = invcap - invsum
                    await self.inventory_add(user, item, new_amount)
                    await ctx.send(f"**Inventaire presque plein** › Seule une partie de la quantité obtenue de **{item}** (~~{amount}~~ → {new_amount}) a été conservée")
                else:
                    await ctx.send(f"**Inventaire plein** · Impossible d'y ajouter x{amount} **{item}**")
                    return False
                
        return True
    
# GROUPCHESTS __________________________

    async def all_chests_with(self, guild: discord.Guild, item: SparkItem, *, minimal_amount: int = 1):
        chests = await self.config.guild(guild).GroupChests()
        result = []
        for c in chests:
            if chests[c]['content'].get(item.id, 0) >= minimal_amount:
                result.append(c)
        return result
    
# STAMINA ______________________________

    async def stamina_limit(self, user: discord.Member) -> int:
        stalim = await self.config.DefaultStaminaLimit()
        
        equipeff = await self.equipment_effects(user)
        if 'enhance_stamina' in equipeff:
            stalim += sum(equipeff['enhance_stamina'])
        
        return stalim

    async def stamina_check(self, user: discord.Member, cost: int) -> bool:
        stamina = await self.config.member(user).Stamina()
        return stamina >= cost
    
    async def stamina_set(self, user: discord.Member, amount: int, *, allow_excess: bool = False) -> int:
        if amount < 0:
            raise ValueError("L'énergie ne peut être négative")
        
        limit = await self.stamina_limit(user)
        amount = amount if allow_excess else min(limit, amount)
        await self.config.member(user).Stamina.set(amount)
        return amount
    
    async def stamina_increase(self, user: discord.Member, amount: int, *, allow_excess: bool = False) -> int:
        stamina = await self.config.member(user).Stamina()
        return await self.stamina_set(user, stamina + amount, allow_excess=allow_excess)
        
    async def stamina_decrease(self, user: discord.Member, amount: int) -> int:
        amount = abs(amount)
        stamina = await self.config.member(user).Stamina()
        return await self.stamina_set(user, max(0, stamina - amount))
    
    async def stamina_level(self, user: discord.Member) -> float:
        stamina = await self.config.member(user).Stamina()
        maxsta = await self.stamina_limit(user)
        return round((stamina / maxsta) * 100, 2)
    
    async def stamina_level_color(self, user: discord.Member) -> int:
        colors = {
            100: 0x43aa8b,
            80: 0x90be6d,
            60: 0xf9c74f,
            40: 0xf8961e,
            20: 0xf3722c,
            0: 0xf94144
        }
        prc = await self.stamina_level(user)
        for k in colors:
            if k <= prc:
                return colors[k]
        return colors[0]
    
    async def users_stamina(self, guild: discord.Guild) -> dict:
        members = await self.config.all_members(guild)
        staminas = {}
        for m in members:
            staminas[m] = members[m]['Stamina']
        return staminas
    
# EQUIPMENT ____________________________

    async def equipment_get(self, user: discord.Member, item: SparkItem = None) -> dict:
        equip = await self.config.member(user).Equipment()
        if item:
            return item.id in equip
        return equip

    async def equipment_carry(self, user: discord.Member, item: SparkItem) -> dict:
        if not await self.inventory_get(user, item):
            raise KeyError(f"L'item {item} n'est pas possédé")
        
        if not item.equipable:
            raise ItemNotEquipable("L'item ne peut être équipé")
        
        equiped = await self.equipment_get(user, item)
        if equiped:
            return equiped
        
        equip = await self.equipment_get(user)
        if len(equip) >= 3:
            raise EquipmentError("Impossible d'équiper plus de 3 items en même temps")
        
        try:
            await self.inventory_remove(user, item, 1)
        except InventoryError:
            raise
        
        await self.config.member(user).Equipment.set_raw(item.id, value=item.default_config)
        return item.default_config
    
    async def equipment_edit(self, user: discord.Member, item: SparkItem, *, update: bool = True, **new_config) -> dict:
        if not await self.equipment_get(user, item):
            raise KeyError(f"L'item {item} n'est pas équipé")
        
        if not update:
            await self.config.member(user).Equipment.set_raw(item.id, value=new_config)
            return new_config
        else:
            config = await self.equipment_get(user, item)
            config.update(new_config)
            await self.config.member(user).Equipment.set_raw(item.id, value=config)
            return config
        
    async def equipment_drop(self, user: discord.Member, item: SparkItem):
        if not await self.equipment_get(user, item):
            raise KeyError(f"L'item {item} n'est pas équipé")
        
        try:
            await self.inventory_add(user, item, 1, force=True)
        except InventoryError:
            raise
        
        await self.config.member(user).Equipment.clear_raw(item.id)
        
    async def equipment_effects(self, user: discord.Member) -> dict:
        equip = await self.equipment_get(user)
        effects = {}
        for item in [self.get_item(i) for i in equip if 'on_equip' in self.items[i]]:
            for e in item.on_equip:
                if e not in effects:
                    effects[e] = []
                effects[e].append(item.on_equip[e])
        return effects

# SHOP ___________________________________

    async def update_shop(self, guild: discord.Guild):
        seed = datetime.now().strftime('%H%j')
        rng = random.Random(seed)
        shopid = rng.choice(list(self.shops.keys()))
        shop = self.shops[shopid]
        
        tagsell = self.get_items_by_tags(*shop['selling'])
        itemssell = [i.id for i in tagsell if i.value]
        selling = rng.sample(itemssell, k=min(len(itemssell), 4))
        
        shop_data = {'id': shopid, 'selling': selling, 'discount': round(rng.uniform(*shop['price_range']), 2)}
        await self.config.guild(guild).Shop.set_raw('data', value=shop_data)
        
    async def get_guild_shop(self, guild: discord.Guild):
        """Récupère les données de la boutique actuellement disponible"""
        shop = await self.config.guild(guild).Shop.get_raw('data')
        return shop
    
    
# CACHE ________________________________

    async def get_cache(self, guild: discord.Guild):
        if guild.id not in self.cache:
            self.cache[guild.id] = {
                'counter': 0,
                'event_ongoing': False,
                'next_event': await self.config.guild(guild).Events.get_raw('starting_threshold'),
                'last_event': 0,
                'next_event_cooldown': time.time(),
                
                'stamina_regen': {}
            }
        return self.cache[guild.id]


# COMMANDES ______________________________

    @commands.command(name='inventory', aliases=['inv'])
    @commands.guild_only()
    async def display_inventory(self, ctx):
        """Affiche son inventaire"""
        user, guild = ctx.author, ctx.guild
        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        account = await eco.get_account(user)
        
        inv = await self.inventory_get(user)
        invsum = sum([inv[i] for i in inv])
        invcap = await self.inventory_capacity(user)
        stamina = await self.config.member(user).Stamina()
        stamina_limit = await self.stamina_limit(user)
        stamina_level, stamina_color = await self.stamina_level(user), await self.stamina_level_color(user)
        
        stats_txt = f"⚡ **Energie** · {stamina}/{stamina_limit} ({stamina_level}%)\n"
        stats_txt += f"💶 **Solde** · {account.balance}{currency}\n"
        stats_txt += f"🎒 **Capacité d'inventaire** · {invsum}/{invcap}"
        
        itemssort = sorted([(i, self.items[i]['name']) for i in inv], key=operator.itemgetter(1))
        items = [self.get_item(i[0]) for i in itemssort]
        
        tabls = []
        tabl = []
        for item in items:
            if len(tabl) < 30:
                typehint = ''
                if item.equipable:
                    typehint += ' [E]'
                if item.on_use:
                    typehint += ' [U]'
                tabl.append((f"{item.name}{typehint}", await self.inventory_get(user, item)))
            else:
                tabls.append(tabl)
                tabl = []
        if tabl:
            tabls.append(tabl)
            
        if not tabls:
            em = discord.Embed(description=stats_txt, color=stamina_color)
            em.set_footer(text=f'Spark {VERSION} — {user.name}', icon_url=SPARK_ICON)
            em.add_field(name=f'Inventaire', value=box("Inventaire vide"))
            return await ctx.reply(embed=em, mention_author=False)
            
        p = 0
        msg = None
        while True:
            em = discord.Embed(description=stats_txt, color=stamina_color)
            em.set_footer(text=f'Spark {VERSION} — {user.name}', icon_url=SPARK_ICON)
            em.add_field(name=f'Inventaire ({p + 1}/{len(tabls)})', value=box(tabulate(tabls[p], headers=('Item', 'Qte'))))
            
            if not msg:
                msg = await ctx.reply(embed=em, mention_author=False)
                start_adding_reactions(msg, ['◀️', '⏹️', '▶️'])
            else:
                await msg.edit(embed=em)
            
            try:
                react, _ = await self.bot.wait_for("reaction_add", 
                                                   check=lambda m, u: u == ctx.author and m.message.id == msg.id, 
                                                   timeout=60)
            except asyncio.TimeoutError:
                await msg.clear_reactions()
                return
            
            if react.emoji == '◀️':
                if p == 0:
                    p = len(tabls) - 1
                else:
                    p -= 1
                    
            elif react.emoji == '▶️':
                if p == len(tabls) - 1:
                    p = 0
                else:
                    p += 1
            
            else:
                await msg.clear_reactions()
                return
            
            
    @commands.group(name='equipment', aliases=['equip'], invoke_without_command=True)
    @commands.guild_only()
    async def member_equipment(self, ctx):
        """Voir et gérer son équipement Spark"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.show_equipment)
        
    @member_equipment.command(name="list")
    async def show_equipment(self, ctx):
        """Afficher son équipement"""
        user = ctx.author
        equip = await self.equipment_get(user)
        
        n = 1
        embeds = []
        for itemid in equip:
            item = self.get_item(itemid)
            em = discord.Embed(title=f"**{item.name}** `{item.id}`", 
                               color=user.color)
            
            if item.lore:
                em.description = f'*{item.lore}*'
            
            details = '\n'.join(item.details) if item.details else ''
            if details:
                em.add_field(name="Détails", value=details)
            
            if item.img:
                em.set_thumbnail(url=item.img)
                
            if equip[item.id] and await self.config.user(user).TechnicalMode():
                txt = ''
                for k in equip[item.id]:
                    txt += f'{k}: {equip[item.id]}\n'
                em.add_field(name="Infos techniques (Config)", value=box(txt))
                
            em.set_footer(text=f'Spark {VERSION} — Equipement de {user.name} ({n}/{len(equip)})')
            n += 1
            embeds.append(em)
            
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply(f"**Aucun item équipé** · Vous pouvez équiper un item avec `;equip carry`", mention_author=False)
        
    @member_equipment.command(name="carry")
    async def carry_equipment(self, ctx, *, item: str):
        """Equiper un item possédé
        
        Les items équipés sont retirés de l'inventaire et ne peuvent donc être vendus ou donnés tant qu'ils sont équipés"""
        user = ctx.author
        eqm = self.fetch_item(item)
        if not eqm:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID", mention_author=False)
        if await self.equipment_get(user, eqm):
            return await ctx.reply("**Impossible** · Un item identique est déjà équipé, vous ne pouvez pas équiper deux fois un même item.", mention_author=False)
        try:
            await self.equipment_carry(user, eqm)
        except KeyError or InventoryError:
            return await ctx.reply("**Item non possédé** · Consultez votre inventaire avec `;inv`", mention_author=False)
        except ItemNotEquipable:
            return await ctx.reply(f"**Item non équipable** · L'item {item} ne peut être équipé", mention_author=False)
        except EquipmentError:
            return await ctx.reply("**Equipement plein** · Vous ne pouvez pas équiper plus de 3 items en même temps\nRetirez un équipement avec `;equip drop`", mention_author=False)
        else:
            rappel = '' if random.randint(0, 2) != 0 else "\n__Rappel :__ Vous ne pouvez pas vendre ou donner un item si celui-ci est équipé, vous devrez d'abord le retirer de votre équipement"
            await ctx.reply(f"**Item équipé** › L'item **{item}** a été placé dans un emplacement d'équipement (et retiré de votre inventaire){rappel}", mention_author=False)
        
    @member_equipment.command(name="drop")
    async def drop_equipment(self, ctx, *, item: str):
        """Deséquiper un item de votre équipement
        
        Les items équipés sont retirés de l'inventaire et ne peuvent donc être vendus ou donnés tant qu'ils sont équipés"""
        user = ctx.author
        eqm = self.fetch_item(item)
        if not eqm:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID", mention_author=False)
        try:
            await self.equipment_drop(user, eqm)
        except KeyError:
            return await ctx.reply("**Item non équipé** · Consultez vos items équipés avec `;equip`", mention_author=False)
        except InventoryError:
            return await ctx.reply("**Erreur** · Impossible de récupérer l'item dans votre inventaire", mention_author=False)
        else:
            await ctx.reply(f"**Item retiré de l'équipement** › L'item **{item}** a été replacé dans votre inventaire", mention_author=False)
        
        
    @commands.command(name='iteminfo')
    @commands.guild_only()
    async def display_item_infos(self, ctx, *, search: str):
        """Afficher les informations détaillées sur un item"""
        guild = ctx.guild
        item = self.fetch_item(search)
        if not item:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID", mention_author=False)
        
        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        
        em = discord.Embed(title=f"**{item.name}** `{item.id}`", color=SPARK_COLOR, timestamp=ctx.message.created_at)
        if item.lore:
            em.description = f'*{item.lore}*'
        
        tags = ' '.join([f"`{HUMANIZE_TAGS.get(t, t)}`" for t in item.tags])
        em.add_field(name="Tags", value=tags)
        
        details = '\n'.join(item.details) if item.details else ''
        if details:
            em.add_field(name="Détails", value=details)
        
        em.add_field(name="Tier", value=f'**{TIER_NAMES[item.tier]}**')
        
        if item.img:
            em.set_thumbnail(url=item.img)
        if item.value:
            em.add_field(name='Valeur estimée', value=box(f'{await item.guild_value(guild)}{currency}' , lang='css'))
            
        em.set_footer(text=f'Spark {VERSION}', icon_url=SPARK_ICON)
        
        await ctx.send(embed=em)
        
        
    @commands.command(name="use")
    async def user_use_item(self, ctx, *, item: str):
        """Utiliser un item
        
        Seuls certains items (notamment ceux tagués 'Consommables') peuvent être utilisés"""
        user = ctx.author
        data = self.fetch_item(item, fuzzy_cutoff=70)
        if not data:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID", mention_author=False)
        if not data.on_use:
            return await ctx.reply("**Inutile** · Cet item n'offre aucun effet à son utilisation", mention_author=False)
        
        if not await self.inventory_get(user, data):
            return await ctx.reply(f"**Impossible** · Vous ne possédez pas **{data}**", mention_author=False)
        
        em = discord.Embed(color=user.color)
        em.set_author(name=f"{user.name}", icon_url=user.avatar_url)
        em.set_footer(text=f'Spark {VERSION} — Utiliser un item', icon_url=SPARK_ICON)
        em.description = f"Voulez-vous utiliser **{data}** ?"
        
        details = '\n'.join(data.details) if data.details else ''
        if details:
            em.add_field(name="Détails", value=details)
                
        if data.img:
            em.set_thumbnail(url=data.img)
        
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        msg = await ctx.reply(embed=em, mention_author=False)
        start_adding_reactions(msg, [conf, stop])
        try:
            react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id, timeout=30)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Annulé** · L'item n'a pas été utilisé.", mention_author=False)
        if react.emoji == stop:
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Annulé** · L'item n'a pas été utilisé.", mention_author=False)
        
        try:
            await self.inventory_remove(user, data, 1)
        except:
            return await ctx.reply(f"**Erreur** · Impossible de retirer l'item de votre inventaire.", mention_author=False)
        
        txt = []
        effects = data.on_use
        userstatus = await self.config.member(user).Status()
        n = 1
        for name, value in effects.items():
            if name == 'increase_stamina':
                await self.stamina_increase(user, value)
                txt.append(f"{n}. `Energie +{value}`")
            elif name == 'boost_stamina':
                await self.stamina_increase(user, value, allow_excess=True)
                txt.append(f"{n}. `Energie +{value} [Boost]`")
            elif name == 'restore_stamina':
                stacap = await self.stamina_limit(user)
                await self.stamina_set(user, stacap)
                txt.append(f"{n}. `Energie restaurée à 100%`")
            elif name == 'decrease_stamina':
                await self.stamina_decrease(user, value)
                txt.append(f"{n}. `Energie -{value}`")
            elif name == 'remove_parasite' and userstatus == 2:
                await self.config.member(user).Status.set(1)
                txt.append(f"{n}. `Parasite retiré`")
            n += 1
        
        em = discord.Embed(color=user.color)
        em.set_author(name=f"{user.name}", icon_url=user.avatar_url)
        em.set_footer(text=f'Spark {VERSION} — Utiliser un item', icon_url=SPARK_ICON)
        em.description = f"{conf} **Item _{data}_ utilisé avec succès**"
        em.add_field(name="Effets obtenus", value='\n'.join(txt))
        await msg.clear_reactions()
        await msg.edit(embed=em)
        
        
    @commands.command(name="buy", aliases=['achat'])
    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel)
    async def buy_items(self, ctx, *order):
        """Acheter un item dans la boutique
        
        Préciser le nombre d'items dans le paramètre 'order'
        Si aucun ordre d'achat n'est donné, renvoie des informations sur la boutique"""
        guild = ctx.guild
        user = ctx.author
        shopdata = await self.get_guild_shop(guild)
        if not shopdata:
            return await ctx.reply(f"**Boutique indisponible** · Aucune boutique n'est disponible actuellement", mention_author=False)
            
        shop = self.shops[shopdata['id']]
        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)

        hour = datetime.now().hour
        shoprange = await self.config.ShopUpdateRange()
        if not shoprange[0] <= hour <= shoprange[1]:
            return await ctx.reply(f"**Boutique indisponible** · Les marchands ne vendent qu'entre {shoprange[0]}h et {shoprange[1]}", mention_author=False)
        
        if not order:
            em = discord.Embed(title=f"Boutique ***{shop['name']}***", color=SPARK_COLOR)
            sell = []
            for i in shopdata['selling']:
                item = self.get_item(i)
                price = round(item.value * shopdata['discount'])
                price_str = f'{price}{currency}'
                sell.append((item.name, price_str))
            
            em.description = random.choice(shop['welcome'])
            em.add_field(name="En vente", value=box(tabulate(sell, headers=("Item", "Prix"))))
            em.set_thumbnail(url=shop['img'])
            em.set_footer(text=f'Spark {VERSION} — Boutique', icon_url=SPARK_ICON)
            return await ctx.send(embed=em)

        qte = 1
        itemname = ' '.join(order)
        for e in order:
            if e.isdigit():
                qte = int(e)
                itemname.replace(e, '').strip()
                break
            
        item = self.fetch_item(itemname, shopdata['selling'])
        if not item:
            return await ctx.reply("**Commande invalide** · Cet item n'existe pas ou n'est pas vendu par cette boutique. Vérifiez le nom ou fournissez directement l'ID de l'item.",
                                   mention_author=False)
        
        price_item = round(item.value * shopdata['discount'])
        total_cost = price_item * qte
        if not await eco.check_balance(user, total_cost):
            return await ctx.reply(f"**Solde insuffisant** · Vous n'avez pas assez de crédits pour cette opération, vous avez besoin de **{total_cost}**{currency}.", 
                                   mention_author=False)
        
        if not await self.inventory_check(user, item, +qte):
            return await ctx.reply(f"**Inventaire plein** · Vous ne pouvez pas acheter cette quantité d'items car vous n'avez pas l'espace suffisant dans votre inventaire.",
                                   mention_author=False)
        
        em = discord.Embed(color=SPARK_COLOR)
        em.set_author(name=f"{shop['name']}", icon_url=shop['img'])
        em.set_footer(text=f'Spark {VERSION} — Achat', icon_url=SPARK_ICON)
        em.description = f"Voulez-vous acheter __x{qte} **{item}**__ ?"
        if item.lore:
            em.add_field(name="Description", value=f'*{item.lore}*')
        if item.details:
            em.add_field(name="Détails", value='\n'.join(item.details))
        em.add_field(name="Prix", value=box(f'{total_cost}{currency} ({qte}x{price_item})'))
        if item.img:
            em.set_thumbnail(url=item.img)
        
        msg = await ctx.reply(embed=em, mention_author=False)
        start_adding_reactions(msg, [conf, stop])
        try:
            react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id, timeout=30)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Commande annulée** · ***{shop['name']}*** vous remercie pour votre visite.", mention_author=False)
        
        if react.emoji == conf:
            try:
                await eco.withdraw_credits(user, total_cost, reason="Achat d'items")
            except ValueError:
                await msg.delete(delay=5)
                return await ctx.reply(f"**Fonds insuffisants** · Revenez lorsque vous aurez assez de crédits pour effectuer cette opération !", mention_author=False)
            else:
                await self.inventory_add(user, item, qte)
                await msg.delete(delay=8)
                return await ctx.reply(f"{conf} **Achat réalisé** › __x{qte} **{item}**__ ont été ajoutés à votre inventaire.\n***{shop['name']}*** vous remercie pour votre visite, à bientôt !", mention_author=False)
            
        elif react.emoji == stop:
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Commande annulée** · ***{shop['name']}*** vous remercie pour votre visite.", mention_author=False)
        
    @commands.command(name='sell', aliases=['vente'])
    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel)
    async def sell_items(self, ctx, *, item: str):
        """Vendre un item au prix courant au bot
        
        Le prix est déterminé à partir du nombre d'items identiques déjà en circulation et d'un prix de base déterminé"""
        guild = ctx.guild
        user = ctx.author
        data = self.fetch_item(item, fuzzy_cutoff=70)
        if not item:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID")

        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        if not data.value:
            return await ctx.reply(f"**Item invendable** · Cet item n'a pas de valeur et ne peut donc être vendu à {self.bot.user.name}")
        
        value = await data.guild_value(guild)
        qte_poss = await self.inventory_get(user, data)
        if not qte_poss:
            return await ctx.reply(f"**Item non possédé** · Vous ne possédez pas {data.name}.")
        
        em = discord.Embed(color=SPARK_COLOR)
        em.set_author(name=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        em.add_field(name=f"Prix d'achat", value=box(f'{value}{currency}', lang='css'))
        em.add_field(name=f"Quantité possédée", value=box(f'x{qte_poss}', lang='css'))
        em.description = f"Combien voulez-vous en vendre ? ['0' pour annuler]"
        em.set_footer(text=f'Spark {VERSION} — Vente', icon_url=SPARK_ICON)
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        msg = await ctx.reply(embed=em, mention_author=False)
        try:
            rep = await self.bot.wait_for('message', timeout=30, check=lambda m: m.author == user)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Commande annulée** · Revenez vendre vos items quand vous le voulez !", mention_author=False)
        
        qte_str = rep.content
        
        if qte_str.lower() in ('stop', '0'):
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Commande annulée** · Revenez vendre vos items quand vous le voulez !", mention_author=False)
        
        if qte_str.isdigit():
            qte = int(qte_str)
            if qte <= qte_poss and await self.inventory_check(user, data, -qte):
                await self.inventory_remove(user, data, qte)
                sell_value = qte * value
                await eco.deposit_credits(user, sell_value, reason="Vente d'items")
                
                await msg.delete(delay=8)
                return await ctx.reply(f"{conf} **Vente réalisée** › Vous avez vendu x{qte} **{data}** pour {sell_value}{currency}", mention_author=False)
            else:
                await msg.delete(delay=5)
                return await ctx.reply(f"**Vente impossible** · Vous n'avez pas cette quantité de **{data}**", mention_author=False)
        else:
            await msg.delete(delay=5)
            return await ctx.reply(f"**Quantité invalide** · Je n'ai pas reconnu de quantité d'item dans votre réponse", mention_author=False)
        
    @commands.command(name="giveitem")
    @commands.cooldown(1, 10, commands.BucketType.member)
    async def give_item(self, ctx, to: discord.Member, *, item: str):
        """Donner un item à un membre
        
        Vous ne pouvez pas donner les items équipés"""
        guild = ctx.guild
        user = ctx.author
        data = self.fetch_item(item, fuzzy_cutoff=70)
        if not item:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID")
        
        qte_poss = await self.inventory_get(user, data)
        if not qte_poss:
            return await ctx.reply(f"**Item non possédé** · Vous ne possédez pas {data.name}.")
    
        toinv = await self.inventory_get(to)
        tocap = await self.inventory_capacity(to) - sum([toinv[i] for i in toinv])
    
        em = discord.Embed(color=SPARK_COLOR)
        em.set_author(name=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        em.add_field(name=f"Quantité possédée", value=box(f'x{qte_poss}', lang='css'))
        em.add_field(name=f"Espace disponible chez {to.name}", value=box(f'{tocap}'))
        em.description = f"Combien voulez-vous en donner ? ['0' pour annuler]"
        em.set_footer(text=f"Spark {VERSION} — Don d'item", icon_url=SPARK_ICON)
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        msg = await ctx.reply(embed=em, mention_author=False)
        try:
            rep = await self.bot.wait_for('message', timeout=30, check=lambda m: m.author == user)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Action annulée** · Vous avez abandonné le don d'item", mention_author=False)
        
        qte_str = rep.content
        
        if qte_str.lower() in ('stop', '0'):
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Action annulée** · Vous avez abandonné le don d'item", mention_author=False)
        
        if qte_str.isdigit():
            qte = int(qte_str)
            if qte <= qte_poss and await self.inventory_check(user, data, -qte):
                if not await self.inventory_check(to, data, +qte):
                    return await ctx.send(f"**Impossible** · {to.mention} ne possède pas assez d'espace dans son inventaire pour cette opération ({qte})")
                try:
                    await self.inventory_remove(user, data, qte)
                except:
                    return await ctx.reply(f"**Erreur** · Une erreur a eu lieue en tentant de retirer l'item de l'inventaire du donneur", mention_author=False)
                else:
                    await self.inventory_add(to, data, qte)
                await ctx.reply(f"{conf} **Succès** · **{data}** x{qte} a été donné à {to.mention}", mention_author=False)
            else:
                await ctx.reply(f"**Impossible** · Vous ne pouvez pas donner plus d'items que ce que vous possédez", mention_author=False)
        else:
            await ctx.reply(f"**Quantité invalide** · Je n'ai pas trouvé de quantité valide dans votre réponse", mention_author=False)
            

    @commands.group(name='firepit', aliases=['fire'], invoke_without_command=True)
    @commands.guild_only()
    async def firepit_commands(self, ctx):
        """Voir l'état du feu de camp et l'entrenir"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.show_firepit)
        
    @firepit_commands.command(name="status")
    async def show_firepit(self, ctx):
        """Affiche l'état du feu de camp"""
        guild = ctx.guild
        fire = await self.config.guild(guild).Fire()
        levels = {
            100: (0x43aa8b, "Excellent", 'https://i.imgur.com/Rj2aIrs.png'),
            80: (0x90be6d, "Bon", 'https://i.imgur.com/GUJHuNJ.png'),
            60: (0xf9c74f, "Correcte", 'https://i.imgur.com/nGeLVQk.png'),
            40: (0xf8961e, "Moyen", 'https://i.imgur.com/NCHPBOa.png'),
            20: (0xf3722c, "Mauvais", 'https://i.imgur.com/mhbuOuP.png'),
            0: (0xf94144, "Médiocre", 'https://i.imgur.com/Z2JzszU.png')
        }
        for k in levels:
            if k <= fire:
                color, text, img = levels[k]
                break
        
        em = discord.Embed(title="🔥 Feu de camp", color=color)
        em.add_field(name="Etat du feu", value=box(f'{text} ({fire}%)'))
        em.set_thumbnail(url=img)
        
        if fire < 25:
            em.set_footer(text="Réalimentez le feu avec ';fire fuel'")
        else:
            em.set_footer(text="Le feu (au-dessus de 20%) permet de recharger votre énergie passivement lorsque vous discutez sur les salons de ce serveur")
        
        await ctx.send(embed=em)
        
    @firepit_commands.command(name="fuel")
    async def fuel_firepit(self, ctx, *, item: str):
        """Alimenter le feu
        
        Seuls les items avec un tag 'fuel' permettent d'alimenter le feu"""
        guild = ctx.guild
        user = ctx.author
        data = self.fetch_item(item)
        if not data:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID", mention_author=False)
        
        fire = await self.config.guild(guild).Fire()
        qte_poss = await self.inventory_get(user, data)
        if not qte_poss:
            return await ctx.reply(f"**Item non possédé** · Vous ne possédez pas {data.name}.", mention_author=False)
        
        if not 'fuel' in data.tags:
            return await ctx.reply(f"**Impossible** · Seul les items dotés d'un tag `fuel` peuvent alimenter le feu", mention_author=False)
            
        
        em = discord.Embed(color=SPARK_COLOR)
        em.set_author(name=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        em.add_field(name=f"% Restauration par unité", value=box(f'{FUEL_VALUES[data.id]}', lang='fix'))
        em.add_field(name=f"Quantité possédée", value=box(f'x{qte_poss}', lang='css'))
        em.add_field(name=f"Etat actuel du feu", value=box(f'{fire}%'))
        em.description = f"Combien voulez-vous en mettre ? ['0' pour annuler]"
        em.set_footer(text=f'Spark {VERSION} — Alimenter le feu', icon_url=SPARK_ICON)
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        msg = await ctx.reply(embed=em, mention_author=False)
        try:
            rep = await self.bot.wait_for('message', timeout=30, check=lambda m: m.author == user)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Action annulée** · N'oubliez pas de revenir alimenter le feu avant qu'il ne s'éteigne !", mention_author=False)
        
        qte_str = rep.content
        
        if qte_str.lower() in ('stop', '0'):
            await msg.delete(delay=5)
            return await ctx.reply(f"{stop} **Action annulée** · N'oubliez pas de revenir alimenter le feu avant qu'il ne s'éteigne !", mention_author=False)
        
        if qte_str.isdigit():
            qte = int(qte_str)
            if qte <= qte_poss and await self.inventory_check(user, data, -qte):
                await self.inventory_remove(user, data, qte)
                restore = FUEL_VALUES[data.id] * qte
                new_fire = min(100, fire + restore)
                await self.config.guild(guild).Fire.set(new_fire)
                await ctx.send(f"{conf} **Feu restauré** › Le feu est désormais à {new_fire}% grâce à vous ! Vous avez utilisé x{qte} **{data}**.")
            else:
                return await ctx.reply(f"**Action impossible** · Vous n'avez pas cette quantité de **{data}**", mention_author=False)
        else:
            return await ctx.reply(f"**Quantité invalide** · Je n'ai pas reconnu de quantité dans votre réponse", mention_author=False)
        
        
    @commands.command(name="spawnitem")
    @checks.admin_or_permissions(manage_roles=True)
    async def mod_spawn_item(self, ctx, target: discord.Member, *order: str):
        """Permet de donner un item choisi au membre
        
        Vous pouvez préciser le nombre dans le paramètre 'order'"""
        qte = 1
        itemname = ' '.join(order)
        for e in order:
            if e.isdigit():
                qte = int(e)
                itemname.replace(e, '').strip()
                break
        
        item = self.fetch_item(itemname)
        if not item:
            return await ctx.reply(f"**Item inconnu** · Vérifiez le nom ou donnez directement l'ID de l'item désiré", mention_author=False)
        if not await self.inventory_check(target, item, qte):
            return await ctx.reply(f"**Action impossible** · Le membre n'a pas assez d'emplacements d'inventaire", mention_author=False)

        await self.inventory_add(target, item, qte)
        await ctx.reply(f"**Don effectué** · {target.mention} a reçu x{qte} **{item}**", mention_author=False)
        
        
# PARAMETRES _________________

    @commands.group(name="userspark")
    @commands.guild_only()
    async def spark_user_settings(self, ctx):
        """Paramètres personnels de Spark"""
        
    @spark_user_settings.command(name="techmode")
    async def toggle_techmode(self, ctx):
        """Active/désactive le mode 'Technique' qui permet d'obtenir des informations supplémentaires sur certains 
        
        Ce paramètre est valable sur tous les serveurs où se trouve ce jeu
        Par défaut désactivé"""
        user = ctx.author
        current = await self.config.user(user).TechnicalMode()
        if current:
            await ctx.send(f"Mode désactivé · Vous ne verrez plus les aspects techniques des items et statuts.")
        else:
            await ctx.send(f"Mode activé · Vous avez désormais accès à des précisions supplémentaires sur les items et statuts.")
        await self.config.user(user).TechnicalMode.set(not current)


    @commands.group(name="sparkset")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def spark_settings(self, ctx):
        """Paramètres serveur de Spark"""
        
    @spark_settings.command(name='channels')
    async def set_channels(self, ctx, channels: Greedy[discord.TextChannel] = None):
        """Configure les salons où peuvent apparaître les évènements (minage, combat etc.)"""
        guild = ctx.guild
        if not channels:
            await self.config.guild(guild).Events.clear_raw('channels')
            return await ctx.send(f"Salons retirés · Plus aucun évènement n'apparaîtra sur vos salons écrits.")
        else:
            ids = [c.id for c in channels]
            await self.config.guild(guild).Events.set_raw('channels', value=ids)
            return await ctx.send(f"Salons modifiés · Les évènements pourront apparaître sur les salons donnés.")
        
    @spark_settings.command(name='fire')
    async def fire_degradation(self, ctx, value: int = 2):
        """Modifie le % de dégradation du feu à chaque période d'une heure
        
        Certains évènements spéciaux peuvent accélérer cette dégradation
        Par défaut 2%"""
        guild = ctx.guild
        if value < 0:
            return await ctx.send("Erreur · La valeur ne peut être négative")
        await self.config.guild(guild).Events.set_raw('fire_degradation', value=value)
        await ctx.send(f"Modifié · Le feu baissera de {value}% chaque heure (sauf évènements spéciaux).")
        
    @spark_settings.command(name='eventscd')
    async def set_events_cooldown(self, ctx, value: int = 600):
        """Modifier le temps en SECONDES minimal entre deux évènements (minage par ex.)
        
        Par défaut 600s (10 minutes)"""
        guild = ctx.guild
        if value < 0:
            return await ctx.send("Erreur · La valeur ne peut être négative")
        await self.config.guild(guild).Events.set_raw('events_cooldown', value=value)
        await ctx.send(f"Modifié · Il faudra désormais au minimum {value}s entre deux évènements.")
        
    @spark_settings.command(name='startcalib')
    async def calibrate_starting_threshold(self, ctx, value: int = 150):
        """Modifier la valeur de départ de l'objectif du counter pour lancer un évènement
        
        -> Si vous ne savez pas ce que ça veut dire, n'y touchez pas
        Par défaut 150"""
        guild = ctx.guild
        if value < 0:
            return await ctx.send("Erreur · La valeur ne peut être négative")
        await self.config.guild(guild).Events.set_raw('starting_threshold', value=value)
        await ctx.send(f"Modifié · Le premier objectif du counter sera désormais {value}.")
        
    @spark_settings.command(name='shopupdate')
    async def manual_shop_update(self, ctx):
        """Mettre à jour manuelle la boutique disponible
        
        Elle ne s'affichera pas disponible si elle est fermée à cause de l'heure"""
        guild = ctx.guild
        await self.update_shop(guild)
        await ctx.send(f"Succès · La boutique a été mise à jour pour ce serveur.")
        
    
    @commands.group(name="sparksuperset", aliases=['sparkss'])
    @checks.is_owner()
    async def spark_owner_settings(self, ctx):
        """Paramètres de propriétaire Spark"""
        
    @spark_owner_settings.command(name='inventoryslots')
    async def set_inventory_slots(self, ctx, value: int):
        """Modifie les slots de base que les membres ont dans leur inventaire"""
        if value <= 0:
            return await ctx.send(f"Erreur · Le nombre de slots doit être un nombre positif non nul.")
        
        await self.config.DefaultInventorySlots.set(value)
        await ctx.send(f"Succès · Les membres ont désormais {value} slots de base")
    
    @spark_owner_settings.command(name='staminalimit')
    async def set_stamina_limit(self, ctx, value: int):
        """Modifie la valeur limite de l'énergie par défaut"""
        if value <= 0:
            return await ctx.send(f"Erreur · La valeur limite d'énergie doit être un nombre positif non nul.")
        
        await self.config.DefaultStaminaLimit.set(value)
        await ctx.send(f"Succès · Les membres ont désormais au max. {value} d'énergie de base") 
        
    @spark_owner_settings.command(name='staminaregen')
    async def set_stamina_regen_delay(self, ctx, temps: int):
        """Modifie le temps en secondes entre deux regénération d'énergie (si le feu est à + de 20%)"""
        if temps < 0:
            return await ctx.send(f"Erreur · Le temps de régénération doit être positif.")
        
        await self.config.StaminaRegenDelay.set(temps)
        await ctx.send(f"Succès · Les membres pourront recharger leur énergie toutes les {temps}s automatiquement (si le feu est à plus de 20%)") 
    
    @spark_owner_settings.command(name='valuevar')
    async def set_item_value_variance(self, ctx, value: float):
        """Modifie la variance maximale (en %, entre 0 et 1) de la valeur d'un item"""
        if 0 < value < 1:
            return await ctx.send(f"Erreur · La valeur doit être comprise entre 0 et 1.")
        
        await self.config.MaxValueVariance.set(value)
        await ctx.send(f"Succès · Les prix pourront désormais varier de {value * 100}% par rapport au prix de base") 

    @spark_owner_settings.command(name='shoprange')
    async def shop_range(self, ctx, start: int, end: int):
        """Modifie l'heure d'ouverture et de fermeture des boutiques classiques
        
        Cela exclut les boutiques apparaissant à certains évènements"""
        guild = ctx.guild
        if not 0 <= start < end <= 23:
            return await ctx.send(f"Erreur · L'heure de début doit être inférieure à l'heure de fin et les deux doivent être compris entre 0 et 23.")
        
        await self.config.ShopUpdateRange.set([start, end])
        await ctx.send(f"Succès · Les boutiques ouvriront désormais entre {start} et {end}h")
        
    
    
# EVENTS ____________________________________
    
    async def event_mining_simple(self, channel: discord.TextChannel):
        items = self.get_items_by_tags('ore')
        weighted = {i.id: i.tier for i in items}
        select = random.choices(list(weighted.keys()), list(weighted.values()), k=1)[0]
        item = self.get_item(select)
        invtier = 4 - item.tier
        
        qte = random.randint(invtier, invtier * 3)
        stam_required = max(qte * (item.tier ** 2), 2)
        timeout = 30 + (3 - item.tier) * 15
        
        em = discord.Embed(color=SPARK_COLOR)
        em.set_footer(text=f'Spark {VERSION} — Minage', icon_url=SPARK_ICON)
        discovery_txt = random.choice((f"Un gisement de **{item}** a été déterré par le vent !",
                                       f"Un gisement de **{item}** a été trouvé juste en dehors du camp !",
                                       f"Des minerais de **{item}** ont été découverts sur le camp !"))
        em.description = discovery_txt + f'\n__Cliquez sur ⛏️ en premier pour obtenir ces minerais !__ ({timeout}s)'
        em.add_field(name="Energie nécessaire", value=box(str(stam_required) + '⚡', lang='fix'))
        if item.img:
            em.set_thumbnail(url=item.img)
        
        notminedmsg = random.choice((f"Personne n'a miné **{item}** ? Dommage.",
                                     f"Il semblerait que personne n'ait miné **{item}**... Tant pis.",
                                     f"Personne n'a pu miner **{item}** à temps, les minerais ont été volés par un brigand.",
                                     f"Allo ? Personne n'a miné les minerais de **{item}** ? Dommage."))
    
        preloadstam = await self.users_stamina(channel.guild)
        
        msg = await channel.send(embed=em)
        start_adding_reactions(msg, ['⛏️'])
        try:
            react, miner = await self.bot.wait_for("reaction_add", check=lambda m, u: preloadstam[u.id] >= stam_required and m.message.id == msg.id and u.bot is False, timeout=timeout)
        except asyncio.TimeoutError:
            await msg.clear_reactions()
            em.description = notminedmsg
            await msg.edit(embed=em)
            await msg.delete(delay=20)
            return False
        
        await msg.clear_reactions()
        await self.stamina_decrease(miner, stam_required)
        desc = []
        desc.append(random.choice((f"{miner.mention} mine avec succès le gisement et repart avec x{qte} **{item}** !",
                              f"{miner.mention} remporte **{item}** x{qte} en minant ce gisement !",
                              f"{miner.mention} gagne **{items}** x{qte} en minant le gisement !")))
        if not await self.inventory_check(miner, item, +qte):
            maxcap = await self.inventory_capacity(miner)
            minv = await self.config.member(miner).Inventory()
            invsum = sum([minv[i] for i in minv])
            old_qte = copy(qte)
            qte = maxcap - invsum
            desc.append(f"⚠️ Certains items (x{old_qte}) ont été détruits en raison du manque de place dans votre inventaire.")
            
        try:
            await self.inventory_add(miner, item, qte)
        except:
            desc.append(f"💥 Impossible d'ajouter les items à votre inventaire, vous avez perdu votre butin.")
        
        em = discord.Embed(color=SPARK_COLOR)
        em.set_footer(text=f'Spark {VERSION} — Minage', icon_url=SPARK_ICON)
        em.description = '\n'.join(desc)
        await msg.edit(embed=em)
        await msg.delete(delay=30)
        return True
        
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            guild = message.guild
            author = message.author
            if author.bot:
                return
            
            cache = await self.get_cache(guild)
            if random.randint(0, 2) != 0:
                cache['counter'] += 1
            
            if cache['counter'] >= cache['next_event']:
                if cache['next_event_cooldown'] <= time.time() and cache['event_ongoing'] is False:
                    channels_id = await self.config.guild(guild).Events.get_raw('channels')
                    channelid = random.choice(channels_id)

                    channel = guild.get_channel(channelid)
                    if channel:
                        cache['event_ongoing'] = True
                        event = 'mining_simple'
                        rdm_time = random.randint(1, 10)
                        await asyncio.sleep(rdm_time)
                        if event == 'mining_simple':
                            result = await self.event_mining_simple(channel)
                            
                        # On adapte la vitesse d'apparition des events en fonction de l'activité sur le serveur
                        expected_lower, expected_upper = await self.config.EventsExpectedDelay() * 0.8, await self.config.EventsExpectedDelay() * 1.2
                        if expected_lower > time.time() - cache['last_event']:
                            cache['next_event'] = int((cache['next_event'] - 1)  * 0.9)
                        elif expected_upper < time.time() - cache['last_event']:
                            cache['next_event'] = int((cache['next_event'] + 1) * 1.1)
                            
                        cache['next_event_cooldown'] = time.time() + await self.config.guild(guild).Events.get_raw('events_cooldown')
                        cache['counter'] = 0
                        cache['event_ongoing'] = False
                    
            fire = await self.config.guild(guild).Fire()
            if fire >= 20:
                if cache['stamina_regen'].get(author.id, 0) < time.time():
                    await self.stamina_increase(author, 1)
                    cache['stamina_regen'][author.id] = time.time() + await self.config.StaminaRegenDelay()