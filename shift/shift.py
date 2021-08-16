import json
import logging
import operator
import random
import re
import time
import asyncio
from datetime import date, datetime, timedelta
from typing import List, Union, Set, Any, Dict

import discord
from discord.ext import tasks
from discord.ext.commands import Greedy
from fuzzywuzzy import process
from redbot.core import commands, Config, checks
from redbot.core.commands.commands import Command
from redbot.core.commands.context import Context
from redbot.core.commands.requires import PermStateTransitions
from redbot.core.config import Value
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, start_adding_reactions
from redbot.core.utils.chat_formatting import box
from tabulate import tabulate

logger = logging.getLogger("red.RedX.Shift")

SHIFT_COLOR, SHIFT_ICON = 0xFEFEFE, ''
    
    
class ShiftError(Exception):
    """Classe de base pour les erreurs spécifiques à Shift"""
    
class InventoryError(ShiftError):
    """Erreurs en rapport avec l'inventaire"""
    
class EquipmentError(ShiftError):
    """Erreurs en rapport avec l'équipement"""
    
class ItemNotEquipable(EquipmentError):
    """L'item n'est pas équipable"""
    

class ShiftItem:
    def __init__(self, cog, item_id: str):
        self._cog = cog
        self._raw = cog.items[item_id]
        
        self.id = item_id
        self.name = self._raw['name']
        self.value = self._raw.get('value', None)
        self.tags = self._raw.get('tags', [])
        
    def __str__(self):
        return self.name
    
    def __eq__(self, other: object):
        return self.id == other.id
    
    @property
    def equipable(self):
        return 'equipment' in self.tags
    
    @property
    def default_config(self):
        return self._raw.get('config', {})
    
    @property
    def on_use(self):
        return self._raw.get('on_use', None)
    
    @property
    def on_equip(self):
        return self._raw.get('on_equip', None)
    

class Shift(commands.Cog):
    """Simulateur de vie sur une planète inhospitalière"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {
            'Stamina': 100,
            'Inventory': {},
            'Equipment' : {}
        }

        default_guild = {}
        
        default_global = {
            'DefaultInventorySlots': 100,
            'DefaultStaminaLimit': 100
        }
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        self.cache = {}
        
    
    # Se charge avec __init__.py au chargement du module
    def _load_bundled_data(self):
        items_path = bundled_data_path(self) / 'items.json'
        with items_path.open() as json_data:
            self.items = json.load(json_data)
        logger.info("Items Shift chargés")
    
    
# ITEMS ______________________________

    def get_item(self, item_id: str) -> ShiftItem:
        if not item_id in self.items:
            raise KeyError(f"{item_id} n'est pas un item valide")
        
        return ShiftItem(self, item_id)
    
    def get_items_by_tags(self, *tags: str) -> List[ShiftItem]:
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
        fuzzy = process.extractOne(search, [items[n]['name'] for n in items], score_cutoff=fuzzy_cutoff)
        if fuzzy:
            return self.get_item([n for n in items if items[n]['name'] == fuzzy[0]][0])

        return None
    
    
# INVENTAIRE _________________________

    async def inventory_capacity(self, user: discord.Member) -> int:
        invcap = await self.config.DefaultInventorySlots()
        
        equipeff = await self.equipment_effects(user)
        if 'extend_inventory' in equipeff:
            invcap += sum(equipeff['extend_inventory'])
        
        return invcap

    async def inventory_check(self, user: discord.Member, item: ShiftItem, amount: int) -> bool:
        inv = await self.config.member(user).Inventory()
        if amount > 0:
            maxcap = await self.inventory_capacity(user)
            invsum = sum([inv[i] for i in inv])
            return invsum + amount <= maxcap
        elif amount < 0:
            return inv.get(item.id, 0) >= amount
        return True

    async def inventory_edit(self, user: discord.Member, item: ShiftItem, amount: int) -> int:
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
    
    async def inventory_add(self, user: discord.Member, item: ShiftItem, amount: int) -> int:
        if amount < 0:
            raise ValueError("Impossible d'ajouter une quantité négative d'items")
        
        if not await self.inventory_check(user, item, amount):
            raise InventoryError("L'inventaire ne peut contenir autant d'items")
        
        inv = await self.config.member(user).Inventory()
        return await self.inventory_edit(user, item, inv.get(item.id, 0) + amount)
    
    async def inventory_remove(self, user: discord.Member, item: ShiftItem, amount: int) -> int:
        amount = abs(amount)
        
        if not await self.inventory_check(user, item, -amount):
            raise InventoryError("L'inventaire ne contient pas cette quantité de cet item")
        
        inv = await self.config.member(user).Inventory()
        return await self.inventory_edit(user, item, inv.get(item.id, 0) - amount)
    
    async def inventory_get(self, user: discord.Member, item: ShiftItem = None) -> Union[dict, int]:
        inv = await self.config.member(user).Inventory()
        if item:
            return inv.get(item.id, 0)
        return inv
    
    async def inventory_operation_dialog(self, ctx, item: ShiftItem, amount: int, *, user: discord.Member = None) -> bool:
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
    
# EQUIPMENT ____________________________

    async def equipment_get(self, user: discord.Member, item: ShiftItem = None) -> dict:
        equip = await self.config.member(user).Equipment()
        if item:
            return equip.get(item.id, None)
        return equip

    async def equipment_carry(self, user: discord.Member, item: ShiftItem) -> dict:
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
    
    async def equipment_edit(self, user: discord.Member, item: ShiftItem, *, update: bool = True, **new_config) -> dict:
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
        
    async def equipment_drop(self, user: discord.Member, item: ShiftItem):
        if not await self.equipment_get(user, item):
            raise KeyError(f"L'item {item} n'est pas équipé")
        
        try:
            await self.inventory_add(user, item, 1)
        except InventoryError:
            raise
        
        await self.config.member(user).Equipment.clear_raw(item.id)
        
    async def equipment_effects(self, user: discord.Member) -> dict:
        equip = await self.equipment_get(user)
        effects = {}
        for item in [self.get_item(i) for i in equip if 'on_equip' in equip[i]]:
            for e in item.on_equip:
                if e not in effects:
                    effects[e] = []
                effects[e].append(item.on_equip[e])
        return effects
