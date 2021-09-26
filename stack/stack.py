from io import RawIOBase
import json
import logging
import operator
from os import truncate
from pickle import NONE
import random
from re import T
import time
import asyncio
from datetime import datetime
from typing import List, Union, Set, Any, Dict
from copy import copy
from typing_extensions import ParamSpecKwargs

import discord
from discord.ext import tasks
from discord.ext.commands import Greedy
from fuzzywuzzy import process
from redbot.core import commands, Config, checks
from redbot.core.commands.commands import Command
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, start_adding_reactions
from redbot.core.utils.chat_formatting import box, humanize_timedelta
from tabulate import tabulate

logger = logging.getLogger("red.RedX.Stack")

VERSION = 'v1.0'

STACK_ICON = 0x00FFFF, 'https://i.imgur.com/5aQaxrt.png'

TIER_NAMES = {
    1: "Commun",
    2: "Rare",
    3: "Épique"
}

class StackException(Exception):
    """Classe de base pour les erreurs spécifiques à Stack"""
    
class InventoryCapacityError(StackException):
    """La capacité de l'inventaire ne permet pas de faire l'opération"""
    
class InventoryContentError(StackException):
    """Le contenu de l'inventaire ne permet pas l'opération demandée"""
    
class EquipmentCapacityError(StackException):
    """La capacité de l'équipement ne permet pas de faire l'opération"""
    
class EquipmentCannotEquip(StackException):
    """L'item ne peut être équipé"""
    
class CraftingError(StackException):
    """Erreurs lié au crafting"""


class StackItem:
    def __init__(self, cog, item_id: str):
        self._cog = cog
        self._raw = cog.items[item_id]

        self.id = item_id
        self.__dict__.update(self._raw)
        
    def __getattr__(self, attr):
        return None
        
    def __str__(self):
        return self.name
    
    def __eq__(self, other: object):
        return self.id == other.id
    
    def famount(self, amount: int):
        return f'{self.__str__()} ×{amount}'
    
    async def guild_value(self, guild: discord.Guild):
        return await self._cog.item_guild_value(guild, self)


class Stack(commands.Cog):
    """Système centralisé de données de jeux et de gestion d'items"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)
        
        default_user = {
            'PublicInventory': True
        }

        default_member = {
            'Stamina': 100,
            'Inventory': {},
            'Equipment': {},
            'Crafting': {
                'unlocked': [],
                'expertise': {}
            },
            'Config': {
                'temp_items': []
            }
        }

        default_guild = {
            'Timerange': '',
            'Shop': {},
            'Fire': {
                'level': 100.0,
                'degradation': 1.5,
                'stamina_regen': 2,
                'status': {}},
            'Events': {
                'channels': [],
                'events_cooldown': 900
            }
        }
        
        default_global = {
            'DefaultInventorySlots': 100,
            'DefaultStaminaLimit': 100,
            'ItemValueMaxVariance': 0.25,
            'ShopsAvailability' : (6, 21),
            'TemporizeExpiration': 600
        }
        
        self.config.register_user(**default_user)
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        self.cache = {}
        
        self.stack_loop.start()
        
# LOOP ____________________________________________________

    @tasks.loop(seconds=60.0)
    async def stack_loop(self):
        all_guilds = await self.config.all_guilds()
        

    @stack_loop.before_loop
    async def before_stack_loop(self):
        logger.info('Démarrage de la boucle stack_loop...')
        await self.bot.wait_until_ready()
        
        
# CHARGEMENT DONNEES ______________________________________

    # Se charge avec __init__.py au chargement du module
    def _load_bundled_data(self):
        items_path = bundled_data_path(self) / 'items.json'
        with items_path.open() as json_data:
            self.items = json.load(json_data)
        logger.info("Items Stack chargés")
        
        shops_path = bundled_data_path(self) / 'shops.json'
        with shops_path.open() as json_data:
            self.shops = json.load(json_data)
        logger.info("Boutiques Stack chargées")
        
        craft_path = bundled_data_path(self) / 'craft.json'
        with craft_path.open() as json_data:
            self.crafting = json.load(json_data)
        logger.info("Recettes de craft Stack chargées")
        
        self._include_crafting_recipes()
        
    def _include_crafting_recipes(self):
        recipes = {}
        for craft in self.crafting:
            itemcraft = self.items[craft]
            recipe_id = f'rcp{craft}'
            recipe = {
                "name": f"Recette : {itemcraft['name']}",
                "description": f"Une recette qui indique comment crafter {itemcraft['name']}",
                "tags": ['recipe'],
                "tier": itemcraft.get('tier', 1),
                "value": itemcraft.get('value', 50) * 3,
                "on_use": {
                    'unlock_recipe': craft
                },
                "info":
                    [f"[ᵘ] Débloque la recette pour {itemcraft['name']}"]
                }
            recipes[recipe_id] = recipe
        
        self.items.update(recipes)
    
    
    def register_items(self, source: str, items: dict):
        """Charger des items d'une source extérieure dans le cache Stack"""
        self.items.update(items)
        logger.info(f"Items chargés dans Stack depuis le cog {source}")
    
    
# ITEMS __________________________________________________

    def get_item(self, item_id: str) -> StackItem:
        if not item_id in self.items:
            raise KeyError(f"{item_id} n'est pas un item valide")
        
        return StackItem(self, item_id)
    
    def get_items_by_tags(self, *tags: str) -> List[StackItem]:
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

        strict_name = [i for i in items if search == items[i]['name'].lower()]  # Recherche brute par nom
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
    
    async def search_item(self, ctx, search: str, custom_list: list = None, fuzzy_cutoff: int = 80):
        items = self.items if not custom_list else {i: self.items[i] for i in custom_list if i in self.items}
        search = search.lower()
        
        em = discord.Embed(title=f"Recherche d'item · ***{search}***", color=await ctx.embed_color())
        em.set_footer(text=f"› Choisissez l'item", icon_url=STACK_ICON)
        results = None
        
        fuzzy = process.extractBests(search, [items[n]['name'].lower() for n in items], score_cutoff=fuzzy_cutoff, limit=3)
        if fuzzy:
            results = [n for n in items if items[n]['name'].lower() in [f[0] for f in fuzzy]]
            em.description = box('\n'.join([f'{self.get_item(r)} [{r}]' for r in results]))
        
        fuzzyid = process.extractBests(search, list(items.keys()), score_cutoff=fuzzy_cutoff, limit=3)
        if fuzzyid:
            results = [f[0] for f in fuzzyid]
            em.description = box('\n'.join([f'{self.get_item(r)} [{r}]' for r in results]))
            
        if results:
            emojis = {'🇦': 0, '🇧': 1, '🇨': 2}
            dispemojis = list(emojis.keys())[:len(results)]
            msg = await ctx.reply(embed=em, mention_author=False)
            start_adding_reactions(msg, dispemojis)
            try:
                react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id, timeout=30)
            except asyncio.TimeoutError:
                await msg.delete()
                return None
            
            await msg.delete(delay=3)
            emoji = react.emoji
            if emoji not in emojis:
                return None
            
            item = self.get_item(results[emojis[emoji]])
            return item
        return None
    
    def parse_item_amount(self, text: str, default_amount: int = 1):
        qte = default_amount
        textsplit = text.split()
        itemguess = text
        for e in textsplit:
            if e.isdigit():
                qte = int(e)
                itemguess.replace(e, '').strip()
                break
        
        item = self.fetch_item(itemguess)
        return item, qte
    
    async def item_guild_value(self, guild: discord.Guild, item: StackItem) -> int:
        if not item.value:
            raise ValueError(f"L'item {item} n'est pas vendable")
        
        minvar = round(item.value * (1 - await self.config.MaxValueVariance()))
        varbase = 0.998 if len(str(item.value)) < 3 else 0.996
        value = item.value
        itempool = 0
        
        holders = await self.all_inventories_with(guild, item)
        for h in holders:
            itempool += await self.inventory_get(h, item)
            
        if not itempool:
            return value
        
        valuevar = varbase**(itempool / (len(holders)))
        value = round(value * valuevar)
        return max(minvar, value)
    
    def get_all_tags(self) -> dict:
        tags = {}
        for i in self.items:
            for t in self.items[i].get('tags', []):
                if t not in tags:
                    tags[t] = [t]
    
        return tags
    
    
# INVENTAIRE __________________________________________

    async def inventory_capacity(self, user: discord.Member) -> int:
        invcap = await self.config.DefaultInventorySlots()
        return invcap
    
    async def inventory_check(self, user: discord.Member, item: StackItem, amount: int) -> bool:
        inv = await self.config.member(user).Inventory()
        if amount > 0:
            maxcap = await self.inventory_capacity(user)
            invsum = sum([inv[i] for i in inv])
            return invsum + amount <= maxcap
        elif amount < 0:
            return inv.get(item.id, 0) >= amount
        return True
    
    async def inventory_edit(self, user: discord.Member, item: StackItem, amount: int) -> int:
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
    
    async def inventory_add(self, user: discord.Member, item: StackItem, amount: int, *, force: bool = False) -> int:
        if amount < 0:
            raise ValueError("Impossible d'ajouter une quantité négative d'items")
        
        if not await self.inventory_check(user, item, amount) and force is False:
            raise InventoryCapacityError("L'inventaire ne peut contenir autant d'items")
        
        inv = await self.config.member(user).Inventory()
        return await self.inventory_edit(user, item, inv.get(item.id, 0) + amount)
    
    async def inventory_temporize(self, user: discord.Member, item: StackItem, amount: int) -> dict:
        if amount < 1:
            raise ValueError("Impossible de temporiser une quantité négative ou nulle d'items")
        
        itemtemp = {'item': item.id, 'amount': amount, 'timestamp': time.time()}
        async with self.config.member(user).Config() as config:
            config['temp_items'].append(itemtemp)
        
        return itemtemp
    
    async def inventory_remove(self, user: discord.Member, item: StackItem, amount: int) -> int:
        amount = abs(amount)
        
        if not await self.inventory_check(user, item, -amount):
            raise InventoryContentError("L'inventaire ne contient pas ")
        
        inv = await self.config.member(user).Inventory()
        return await self.inventory_edit(user, item, inv.get(item.id, 0) - amount)
    
    async def inventory_get(self, user: discord.Member, item: StackItem = None) -> Union[dict, int]:
        inv = await self.config.member(user).Inventory()
        if item:
            return inv.get(item.id, 0)
        return inv
    
    async def inventory_items(self, user: discord.Member):
        inv = await self.config.member(user).Inventory()
        for i in inv:
            try:
                item = self.get_item(i)
            except KeyError:
                continue
            yield item, inv[i]
        return None
    
    async def all_inventories_with(self, guild: discord.Guild, item: StackItem, *, minimal_amount: int = 1):
        users = await self.config.all_members(guild)
        result = []
        for u in users:
            if users[u]['Inventory'].get(item.id, 0) >= minimal_amount:
                m = guild.get_member(u)
                if m:
                    result.append(m)
        return result
    
    async def check_temporized_items(self, user: discord.Member):
        tempinv = await self.config.member(user).Config.get_raw('temp_items')
        newtemp = copy(tempinv)
        for t in tempinv:
            item, amount, timestamp = self.get_item(t['item']), t['amount'], t['timestamp']
            if await self.inventory_check(user, item, amount):
                await self.inventory_add(user, item, amount)
                newtemp.remove(t)
            elif timestamp + await self.config.TemporizeExpiration() < time.time():
                newtemp.remove(t)
        
        await self.config.member(user).Config.set_raw('temp_items', value=newtemp)
    

# STAMINA __________________________________________________________

    async def stamina_limit(self, user: discord.Member) -> int:
        stalim = await self.config.DefaultStaminaLimit()
        return stalim
    
    async def stamina_check(self, user: discord.Member, cost: int) -> bool:
        stamina = await self.config.member(user).Stamina()
        return stamina >= cost
    
    async def stamina_get(self, user: discord.Member) -> int:
        return await self.config.member(user).Stamina()
    
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
    
    async def all_users_stamina(self, guild: discord.Guild) -> dict:
        members = await self.config.all_members(guild)
        staminas = {}
        for m in members:
            staminas[m] = members[m]['Stamina']
        return staminas
    

# EQUIPEMENT ________________________________________________

    async def equipment_get(self, user: discord.Member, item: StackItem = None) -> dict:
        equip = await self.config.member(user).Equipment()
        if item:
            return item.id in equip
        return equip

    async def equipment_carry(self, user: discord.Member, item: StackItem) -> dict:
        if not await self.inventory_get(user, item):
            raise KeyError(f"L'item {item} n'est pas possédé")
        
        if not item.equipable:
            raise EquipmentCannotEquip("L'item ne peut être équipé")
        
        equiped = await self.equipment_get(user, item)
        if equiped:
            return equiped
        
        equip = await self.equipment_get(user)
        if len(equip) >= 3:
            raise EquipmentCapacityError("Impossible d'équiper plus de 3 items en même temps")
        
        await self.inventory_remove(user, item, 1)
        
        await self.config.member(user).Equipment.set_raw(item.id, value=item.default_config)
        return item.default_config
    
    async def equipment_edit(self, user: discord.Member, item: StackItem, *, update: bool = True, **new_config) -> dict:
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
        
    async def equipment_drop(self, user: discord.Member, item: StackItem):
        if not await self.equipment_get(user, item):
            raise KeyError(f"L'item {item} n'est pas équipé")
        
        await self.inventory_add(user, item, 1, force=True)
        
        await self.config.member(user).Equipment.clear_raw(item.id)
        
    
    async def user_equipment_properties(self, user: discord.Member) -> dict:
        equip = await self.equipment_get(user)
        properties = []
        for item in [self.get_item(i) for i in equip if 'on_equip' in self.items[i]]:
            properties.append(item.on_equip)
        return properties
    
    async def fetch_property_values(self, user: discord.Member, pty: str):
        props_list = await self.get_equipment_properties(user)
        for props in props_list:
            if pty in props:
                yield props[pty]
        return None
    
    
# CRAFTING ____________________________________________________

    async def get_crafting_recipe(self, item: StackItem) -> dict:
        if item.id not in self.crafting:
            raise CraftingError(f"L'item {item} n'est pas craftable")
        
        return self.crafting[item.id]


    async def crafting_get_unlocked(self, user: discord.Member) -> list:
        return await self.config.member(user).Crafting.get_raw('unlocked')

    async def crafting_unlock_recipe(self, user: discord.Member, item: StackItem) -> Union[None, StackItem]:
        if item.id not in self.crafting:
            raise CraftingError(f"L'item {item} n'est pas craftable")
        
        unlocked = await self.crafting_get_unlocked(user)
        if item.id not in unlocked:
            async with self.config.member(user).Crafting() as crafting:
                crafting['unlocked'].append(item.id)
            
            return item
        return None
    
    async def crafting_forget_recipe(self, user: discord.Member, item: StackItem):
        if item.id not in self.crafting:
            raise CraftingError(f"L'item {item} n'est pas craftable")
        
        unlocked = await self.crafting_get_unlocked(user)
        if item.id in unlocked:
            async with self.config.member(user).Crafting() as crafting:
                crafting['unlocked'].remove(item.id)
        
        
    async def crafting_levelup_expertise(self, user: discord.Member, item: StackItem):
        craft = await self.get_crafting_recipe(item)
        exp = await self.config.member(user).Crafting.get_raw('expertise')
        if item.id not in exp:
            data = {'stamina_use': craft['stamina_use'][0], 'success_rate': craft['success_rate'][0]}
        else:
            expitem = exp[item.id]
            data = {'stamina_use': max(expitem['stamina_use'] - craft['stamina_use'][2], expitem['stamina_use'][1]),
                    'success_rate': min(expitem['success_rate'] + craft['success_rate'][2], craft['success_rate'][1])}
            
        if data != exp.get(item.id, {}):
            await self.config.member(user).Crafting.set_raw('expertise', item.id, value=data)
        return data
        
    async def crafting_leveldown_expertise(self, user: discord.Member, item: StackItem):
        craft = await self.get_crafting_recipe(item)
        exp = await self.config.member(user).Crafting.get_raw('expertise')
        if item.id not in exp:
            data = {'stamina_use': craft['stamina_use'][0], 'success_rate': craft['success_rate'][0]}
        else:
            expitem = exp[item.id]
            data = {'stamina_use': min(expitem['stamina_use'] + craft['stamina_use'][2], expitem['stamina_use'][0]),
                    'success_rate': max(expitem['success_rate'] - craft['success_rate'][2], craft['success_rate'][0])}
        
        if data != exp.get(item.id, {}):
            await self.config.member(user).Crafting.set_raw('expertise', item.id, value=data)
        return data
        
    async def crafting_get_expertise(self, user: discord.Member, item: StackItem):
        try:
            await self.get_crafting_recipe(item)
        except Exception:
            raise
        exp = await self.config.member(user).Crafting.get_raw('expertise')
        return exp.get(item.id, None)

    
# ACTIONS ____________________________________________________

    async def apply_item_effect(self, ctx, user: discord.Member, action: str, item: StackItem, amount: int = 1):
        conf, stop = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        useramount = await self.inventory_get(user, item)
        if useramount < amount:
            return await ctx.reply(f"**Impossible** · Vous n'avez pas **{item.famount(amount)}** dans votre inventaire", mention_author=False)

        if action == 'use':
            if not item.on_use:
                return await ctx.reply(f"**Inutile** · L'item **{item}** ne procure aucun effet lors de sa consommation", mention_author=False)
            to_apply = item.on_use
        elif action == 'burn':
            if not item.on_burn:
                return await ctx.reply(f"**Inutile** · L'item **{item}** ne procure aucun effet lorsque vous le brûlez", mention_author=False)
            to_apply = item.on_burn
            
        txt = []
        notif = ''
        for name, value in to_apply.items():
            if name == 'increase_stamina':
                await self.stamina_increase(user, value * amount)
                txt.append(f"__Régeneration d'énergie :__ +{value * amount}")
                
            elif name == 'boost_stamina':
                await self.stamina_increase(user, value * amount, allow_excess=True)
                txt.append(f"__Boost d'énergie :__ +{value * amount}")
                
            elif name == 'restore_stamina':
                stacap = await self.stamina_limit(user)
                await self.stamina_set(user, stacap)
                txt.append(f"__Restauration d'énergie :__ 100%")
                
            elif name == 'decrease_stamina':
                await self.stamina_decrease(user, value * amount)
                txt.append(f"__Perte d'énergie :__ {value * amount}")
                
            elif name == 'random_items_from_tags':
                items = self.get_items_by_tags(*value)
                items = [i for i in items if i.tier < 3]
                items_won = random.choices(items, k=amount)
                items_count = [(i, items_won.count(i)) for i in set(items_won)]
                itemtxt = '__Items obtenus :__'
                for item, qte in items_count:
                    if await self.inventory_check(user, item, qte):
                        await self.inventory_add(user, item, qte)
                        itemtxt += f' `{item.famount(qte)}`'
                    else:
                        await self.inventory_temporize(user, item, qte)
                        itemtxt += f' `{item.famount(qte)}ᵗ`'
                        notif = '\n(ᵗ) = Inventaire plein, item tempo.'
                txt.append(itemtxt)
            
            elif name == 'give_items':
                itemtxt = '__Items obtenus :__'
                for k in value:
                    item = self.get_item(k[0])
                    qte = int(k[1]) * amount
                    if await self.inventory_check(user, item, qte):
                        await self.inventory_add(user, item, qte)
                        itemtxt += f' `{item.famount(qte)}`'
                    else:
                        await self.inventory_temporize(user, item, qte)
                        itemtxt += f' `{item.famount(qte)}ᵗ`'
                        notif = '\n(ᵗ) = Inventaire plein, item tempo.'
                txt.append(itemtxt)
            
            elif name == 'unlock_recipe':
                item = self.get_item(value)
                try:
                    await self.crafting_unlock_recipe(user, item)
                except CraftingError:
                    txt.append(f"__Recette débloquée :__ Erreur")
                else:
                    txt.append(f"__Recette débloquée :__ `{item}`")
                    
        em = discord.Embed(description='\n'.join(txt), color=await ctx.embed_color())
        em.set_author(name=f"{user.name}", icon_url=user.avatar_url)
        em.set_footer(text=f"Effets d'items{notif}", icon_url=STACK_ICON)
        return await ctx.reply(embed=em, mention_author=False)

# SHOP ____________________________________________________

    async def update_shop(self, guild: discord.Guild):
        seed = datetime.now().strftime('%H%j')
        rng = random.Random(seed)
        shopid = rng.choice(list(self.shops.keys()))
        shop = self.shops[shopid]
        
        tagsell = self.get_items_by_tags(*shop['selling'])
        itemssell = [i.id for i in tagsell if i.value]
        selling = rng.sample(itemssell, k=min(len(itemssell), 4))
        
        shop_data = {'id': shopid, 'selling': selling, 'discount': round(rng.uniform(*shop['price_range']), 2)}
        await self.config.guild(guild).Shop.set(shop_data)
        
    async def get_guild_shop(self, guild: discord.Guild):
        """Récupère les données de la boutique actuellement disponible"""
        return await self.config.guild(guild).Shop()
    
    
# UTILS _________________________________________________

    def get_actionhints(self, item: StackItem):
        hints = ''
        if item.on_equip:
            hints += 'ᵉ'
        if item.on_use:
            hints += 'ᵘ'
        if item.on_burn:
            hints += 'ᶠ'
        return hints
   
# CACHE ____________________________________________________

    async def get_cache(self, guild: discord.Guild):
        if guild.id not in self.cache:
            self.cache[guild.id] = {
                'counter': 0,
                'event_ongoing': False,
                'last_event': time.time(),
                'next_event_cooldown': time.time(),
                
                'interactions': {}
            }
        return self.cache[guild.id]
    
    
# COMMANDES ==============================================================

    @commands.command(name='inventory', aliases=['inv'])
    @commands.guild_only()
    async def display_inventory(self, ctx, user: discord.Member = None):
        """Affiche son inventaire et les stats principales
        
        Il est possible de consulter l'inventaire d'un autre membre si celui-ci est public"""
        user = user if user else ctx.author
        guild = ctx.guild
        
        if user != ctx.author and await self.config.user(user).PublicInventory() is False:
            return await ctx.reply(f"**Accès refusé** · Ce membre ne désire pas qu'on puisse consulter son inventaire", mention_author=False)
        
        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        account = await eco.get_account(user)
        
        inv = await self.inventory_get(user)
        invsum = sum([inv[i] for i in inv])
        invcap = await self.inventory_capacity(user)
        stamina = await self.config.member(user).Stamina()
        stamina_limit = await self.stamina_limit(user)
        stamina_level, stamina_color = await self.stamina_level(user), await self.stamina_level_color(user)
        
        stats_txt = f"**Énergie** · {stamina}/{stamina_limit} ({stamina_level}%)\n"
        stats_txt += f"**Solde** · {account.balance}{currency}\n"
        stats_txt += f"**Capacité d'inventaire** · {invsum}/{invcap}"
        
        itemssort = sorted([(i, self.items[i]['name']) for i in inv], key=operator.itemgetter(1))
        items = [self.get_item(i[0]) for i in itemssort]
        
        tabls = []
        tabl = []
        for item in items:
            if len(tabl) < 30:
                actionhints = self.get_actionhints(item)
                tabl.append((f"{item.name}{actionhints}", await self.inventory_get(user, item)))
            else:
                tabls.append(tabl)
                tabl = []
               
        tempinv = await self.config.member(user).Config.get_raw('temp_items')
        notif_temp = False
        for t in tempinv:
            tempitem, tempamount = self.get_item(t['item']), t['amount']
            if len(tabl) < 30:
                tabl.append((f"{tempitem.name}ᵗ", tempamount))
                notif_temp = True
            else:
                tabls.append(tabl)
                tabl = []
        
        if tabl:
            tabls.append(tabl)
            
        if not tabls:
            em = discord.Embed(description=stats_txt, color=stamina_color)
            em.set_author(name=f"{user.name}", icon_url=user.avatar_url)
            if notif_temp:
                em.set_footer(text=f'Stack {VERSION} — (ᵗ) = Item tempo.', icon_url=STACK_ICON)
            else:
                em.set_footer(text=f'Stack {VERSION}', icon_url=STACK_ICON)
            em.add_field(name=f'Inventaire', value=box("Inventaire vide"))
            return await ctx.reply(embed=em, mention_author=False)
            
        p = 0
        msg = None
        while True:
            em = discord.Embed(description=stats_txt, color=stamina_color)
            em.set_author(name=f"{user.name}", icon_url=user.avatar_url)
            if notif_temp:
                em.set_footer(text=f'Stack {VERSION}\n(ᵗ) = Inventaire plein, item tempo.', icon_url=STACK_ICON)
            else:
                em.set_footer(text=f'Stack {VERSION}', icon_url=STACK_ICON)
            
            if len(tabls) == 1:
                em.add_field(name=f'Inventaire', value=box(tabulate(tabls[p], headers=('Item', 'Qte'))))
                return await ctx.reply(embed=em, mention_author=False)
            
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
                try:
                    await msg.clear_reactions()
                except:
                    pass
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
            
            
    # Opérations d'équipement ________________________________________________
            
    @commands.group(name='equipment', aliases=['equip'], invoke_without_command=True)
    @commands.guild_only()
    async def member_equipment(self, ctx):
        """Voir et gérer son équipement Stack"""
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
            
            if item.description:
                em.description = f'*{item.description}*'
            info = '\n'.join(item.info) if item.info else ''
            if info:
                em.add_field(name="Information", value=info)
            if item.img:
                em.set_thumbnail(url=item.img)
                
            em.set_footer(text=f'Équipement de {user.name} ({n}/{len(equip)})', icon_url=STACK_ICON)
            n += 1
            embeds.append(em)
            
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply(f"**Équipement vide** · Pour équiper un item, utilisez `;equip carry`", mention_author=False)
        
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
        except KeyError or InventoryContentError:
            return await ctx.reply("**Item non possédé** · Consultez votre inventaire avec `;inv`", mention_author=False)
        except EquipmentCannotEquip:
            return await ctx.reply(f"**Item non équipable** · L'item {item} ne peut être équipé", mention_author=False)
        except EquipmentCapacityError:
            return await ctx.reply("**Équipement plein** · Vous ne pouvez pas équiper plus de 3 items en même temps\nRetirez un équipement avec `;equip drop`", mention_author=False)
        else:
            rappel = '' if random.randint(0, 3) != 0 else "\n__Rappel :__ Vous ne pouvez pas vendre ou donner un item si celui-ci est équipé, vous devrez d'abord le retirer de votre équipement"
            await ctx.reply(f"**Item équipé** › L'item **{eqm}** a été placé dans un emplacement d'équipement (et retiré de votre inventaire){rappel}", mention_author=False)
        
    @member_equipment.command(name="drop")
    async def drop_equipment(self, ctx, *, item: str):
        """Deséquiper un item de votre équipement
        
        Retirer un item équipé l'ajoute de force dans votre inventaire, que vous ayez la place ou non"""
        user = ctx.author
        eqm = self.fetch_item(item)
        if not eqm:
            return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID", mention_author=False)
        try:
            await self.equipment_drop(user, eqm)
        except KeyError:
            return await ctx.reply("**Item non équipé** · Consultez vos items équipés avec `;equip`", mention_author=False)
        else:
            await ctx.reply(f"**Item retiré de l'équipement** › L'item **{eqm}** a été replacé dans votre inventaire", mention_author=False)
      
    
    # Infos Items ________________________________________________  
        
    @commands.command(name='iteminfo', aliases=['infoitem'])
    @commands.guild_only()
    async def display_item_infos(self, ctx, *, search: str):
        """Afficher les informations détaillées sur un item"""
        guild = ctx.guild
        item = self.fetch_item(search, fuzzy_cutoff=95)
        if not item:
            item = await self.search_item(ctx, search)
            if not item:
                return await ctx.reply("**Item inconnu** · Vérifiez le nom ou fournissez directement son ID", mention_author=False)
        
        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        
        em = discord.Embed(title=f"**{item.name}** `{item.id}`", color=await ctx.embed_color(), timestamp=ctx.message.created_at)
        if item.description:
            em.description = f'*{item.description}*'
        
        tags = ' '.join([f'`{t}`' for t in item.tags])
        em.add_field(name="Tags", value=tags)
        
        info = '\n'.join(item.info) if item.info else ''
        if info:
            em.add_field(name="Information", value=info)
        
        tier = item.tier if item.tier else 1
        em.add_field(name="Rareté", value=f'**{TIER_NAMES[tier]}** ({tier})')
        
        if item.img:
            em.set_thumbnail(url=item.img)
        if item.value:
            em.add_field(name='Valeur estimée', value=box(f'{await item.guild_value(guild)}{currency}' , lang='css'))
            
        em.set_footer(text=f'Stack {VERSION}', icon_url=STACK_ICON)
        await ctx.send(embed=em)
    
    
    
    
    
    