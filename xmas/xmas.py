from collections import namedtuple
import json
import logging
import operator
import random
import time
import asyncio
from datetime import date, datetime
from typing import KeysView, List, Tuple, Union, Set, Any, Dict
from copy import copy
import string
import typing

import discord
from discord.ext import tasks
from discord.ext.commands import Greedy
from discord.ext.commands.converter import IDConverter
from discord.ext.commands.errors import PrivateMessageOnly
from discord.utils import MAX_ASYNCIO_SECONDS
from fuzzywuzzy import process
from redbot.core import commands, Config, checks
from redbot.core.commands.commands import Command
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, start_adding_reactions
from redbot.core.utils.chat_formatting import box, humanize_timedelta
from tabulate import tabulate

XMAS_COLOR = lambda: random.choice([0x487F57, 0xF2DEB1, 0x7E4138, 0xB7534E])

class XMasError(Exception):
    """Classe de base pour les erreurs spécifiques à XMas"""
    
DEST_TIME = lambda: 3600 if 2 <= datetime.now().hour <= 9 else 1800
    
TEAMS_PRP = {
    'green' : {
        'name': "Lutins Verts",
        'icon': 'https://i.imgur.com/I7GOqDe.png',
        'color': 0x2bd914
        },
    'red': {
        'name': "Lutins Rouges",
        'icon': 'https://i.imgur.com/alAIF1i.png',
        'color': 0xfc0303
    }
}

_ASTUCES = [
    "Vous remportez des voeux en livrant les cadeaux de votre équipe",
    "Plus vous utilisez de charbon pour saboter un cadeau adverse, plus vos chances de réussite sont importantes !",
    "Les deux équipes n'ont pas de stats qui leurs sont propres",
    "Lorsque vous livrez un cadeau, vous remportez des points personnels en plus de points pour votre équipe !",
    "Si vous ne livrez pas un cadeau, l'équipe adverse gagne du charbon proportionnellement au grade du cadeau perdu.",
    "Vos items personnels vous servent à améliorer les cadeaux de votre équipe, avec ';upgrade'",
    "Le charbon sert à saboter les cadeaux ennemis, consultez ';help coal' pour en savoir plus",
    "Les cadeaux donnés à l'occasion des questions de capitales sont automatiquement de tier 3",
    "La position du traineau change environ toutes les 30m le jour et 1h la nuit, surveillez bien les prochaines destinations avec ';map'",
    "Vous pouvez voter pour ralentir temporairement le traineau, afin qu'il reste plus longtemps à une destination. Utilisez ';slow' pour cela.",
    "Les quêtes sont mises à jour et réinitialisées à midi et à minuit",
    "Si vous avez pas terminé une quête avant la vérification auto. (12h/00h) vous perdrez votre progression",
    "Vous pouvez activer/désactiver votre bonnet avec ';bonnet'",
    "Vous pouvez activer/désactiver la réception de MP en cas d'accomplissement de quête avec ';questmp'"
]

QUEST_INFO = {
    'upgrade_any': {
        'level': 1,
        'desc': "Améliorer n'importe quel cadeau",
        'threshold': 1,
        'prize': 'items'
    },
    'upgrade_T3': {
        'level': 2,
        'desc': "Faire passer un cadeau en tier 3",
        'threshold': 1,
        'prize': 'items'
    },
    'upgrade_T45': {
        'level': 3,
        'desc': "Faire passer un cadeau en tier 4 ou 5",
        'threshold': 1,
        'prize': 'items'
    },
    'event_question': {
        'level': 1,
        'desc': "Obtenir un cadeau par le biais d'un évènement 'Soucis de GPS'",
        'threshold': 1,
        'prize': 'coal'
    },
    'event_questionhard': {
        'level': 3,
        'desc': "Obtenir 3 cadeaux par le biais d'un évènement 'Soucis de GPS'",
        'threshold': 3,
        'prize': 'items'
    },
    'get_chocolat1': {
        'level': 1,
        'desc': "Obtenir x3 `Chocolat`",
        'threshold': 3,
        'prize': 'items'
    },
    'get_chocolat2': {
        'level': 2,
        'desc': "Obtenir x5 `Chocolat`",
        'threshold': 5,
        'prize': 'items'
    },
    'get_sucreorge1': {
        'level': 1,
        'desc': "Obtenir x3 `Sucre d'Orge`",
        'threshold': 3,
        'prize': 'items'
    },
    'get_sucreorge2': {
        'level': 2,
        'desc': "Obtenir x5 `Sucre d'Orge`",
        'threshold': 5,
        'prize': 'items'
    },
    'get_papillote1': {
        'level': 1,
        'desc': "Obtenir x3 `Papillote`",
        'threshold': 3,
        'prize': 'items'
    },
    'get_papillote2': {
        'level': 2,
        'desc': "Obtenir x5 `Papillote`",
        'threshold': 5,
        'prize': 'items'
    },
    'get_painepice1': {
        'level': 1,
        'desc': "Obtenir x3 `Pain d'Epices`",
        'threshold': 3,
        'prize': 'items'
    },
    'get_painepice2': {
        'level': 2,
        'desc': "Obtenir x5 `Pain d'Epices`",
        'threshold': 5,
        'prize': 'items'
    },
    'get_biscuit1': {
        'level': 1,
        'desc': "Obtenir x3 `Biscuit`",
        'threshold': 3,
        'prize': 'items'
    },
    'get_biscuit2': {
        'level': 2,
        'desc': "Obtenir x5 `Biscuit`",
        'threshold': 5,
        'prize': 'items'
    }
}
    
logger = logging.getLogger("red.RedX.XMas")


class Item:
    def __init__(self, cog: 'XMas', item_id: str):
        self._cog = cog
        self._raw = cog.items[item_id]

        self.id = item_id
        self.name = self._raw.get('name')
        
    def __str__(self):
        return self.name
    
    def __eq__(self, other: object):
        return self.id == other.id
    
    def famount(self, amount: int):
        return f'{self.__str__()} ×{amount}'
    

class XMas(commands.Cog):
    """Jeu évènement Noël 2021"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)
        
        default_member = {
            'Team': None,
            'Inventory': {},
            'Points': 0,
            'Wishes': {},
            'SlowCache': {
                'last': 0,
                'dest': ''
            },
            'Quest': {},
            'QuestLast': '',
            'QuestGetMP': True
        }
        
        default_guild = {
            'LastDestChange': 0,
            'Destinations': [],
            'Teams': {
                'green': {
                    'Points': 0,
                    'Gifts': {},
                    'Coal': 0
                },
                'red': {
                    'Points': 0,
                    'Gifts': {},
                    'Coal': 0
                }
            },
            'Settings': {
                'event_channel': None,
                'alert_channel': None,
                'red_role': None,
                'green_role': None
            },
            'QuestCheck': ''
        }
        
        default_global = {
            
        }
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        self.cache = {}
        
        self.xmas_checks.start()
        
        
# LOOP --------------------------------------------

    @tasks.loop(seconds=30.0)
    async def xmas_checks(self):
        all_guilds = await self.config.all_guilds()
        for g in all_guilds:
            guild = self.bot.get_guild(g)
            
            if all_guilds[g]['LastDestChange'] + DEST_TIME() < time.time():
                await self.config.guild(guild).LastDestChange.set(time.time())
                lastdst = await self.fill_destinations(guild)
                lastdst = lastdst[0]
                dst = await self.next_destination(guild)
                await self.check_gifts(guild, lastdst, apply_remove=True)
                
                em = discord.Embed(color=XMAS_COLOR())
                em.description = f"**Arrivée à** · __{dst}__ ({self.countries[dst]})"
                em.set_footer(text="Astuce · " + random.choice(_ASTUCES))
                await self.send_alert(guild, em, expiration=300)
                
                if guild.id == 204585334925819904:
                    amsg = f"{dst} ({self.countries[dst]})"
                    activ = discord.Activity(name=amsg, type=discord.ActivityType.competing)
                    await self.bot.change_presence(activity=activ)
            
            curtime = 'AM' if 0 <= datetime.now().hour <= 11 else 'PM'
            curtime += datetime.now().strftime('%d%m')
            if curtime != all_guilds[g].get('QuestCheck', ''):
                for m in guild.members:
                    complete = await self.check_quest(m)
                    if not complete:
                        await self.clear_quest(m)
                    else:
                        if await self.config.member(m).QuestGetMP():
                            em = discord.Embed(color=XMAS_COLOR())
                            em.set_author(name=f"{m} · Quête accomplie", icon_url=m.avatar_url)
                            em.description = f"Vous avez accompli votre quête, vous remportez **{complete}**"
                            em.set_footer(text="Si ce MP vous dérange, vous pouvez désactiver la réception avec ';stopmp'")
                            try:
                                await m.send(embed=em)
                            except:
                                pass

                await self.config.guild(guild).set_raw('QuestCheck', value=curtime)
            
    @xmas_checks.before_loop
    async def before_xmas_checks(self):
        logger.info('Démarrage de la boucle xmas_checks...')
        await self.bot.wait_until_ready()
    
        
# DONNEES -----------------------------------------

    # Se charge avec __init__.py au chargement du module
    def _load_bundled_data(self):
        content_path = bundled_data_path(self) / 'content.json'
        with content_path.open() as json_data:
            all_content = json.load(json_data)
        
        self.countries, self.gifts, self.items = all_content['countries'], all_content['gifts'], all_content['items']
        self.gifts_list = tuple(self.gifts.values())
        
# CACHE ----------------------------------------

    def get_cache(self, guild: discord.Guild):
        if guild.id not in self.cache:
            self.cache[guild.id] = {
                'status': 0,
                'last_message': None,
                'last_spawn': 0,
                'counter': 0,
                'trigger': 25,
                'resume_counter': [],
                
                'CurrentEvent': False,
                'EventMsg': None,
                'EventType': '',
                'EventUsers': {},
                'EventItems': [],
                
                'EventWinner': None,
                'EventAnswer': '',
                
                'SlowDest': '',
                
                'CoalCD': {}
            }
        return self.cache[guild.id]
    
# VOYAGE & GIFTS ----------------------------------

    async def send_alert(self, guild: discord.Guild, embed: discord.Embed, expiration: int = None):
        channel_id = await self.config.guild(guild).Settings.get_raw('alert_channel')
        if not channel_id:
            raise KeyError("Aucun channel d'alerte n'a été configuré")
        
        channel = guild.get_channel(channel_id)
        alert = await channel.send(embed=embed)
        if expiration:
            await alert.delete(delay=expiration)

    async def fill_destinations(self, guild: discord.Guild):
        current = await self.config.guild(guild).Destinations()
        pool = [c for c in self.countries if c not in current]
        async with self.config.guild(guild).Destinations() as dests:
            while len(dests) < 20:
                country = random.choice(pool)
                dests.append(country)
                pool.remove(country)
        return await self.config.guild(guild).Destinations()
                
    async def next_destination(self, guild: discord.Guild):
        dst = await self.fill_destinations(guild)
        if not dst:
            raise KeyError("Aucune destination n'est prévue")
        
        async with self.config.guild(guild).Destinations() as dests:
            dests.remove(dests[0])
        
        return dst[1]
    
    async def get_destinations(self, guild: discord.Guild):
        current = await self.config.guild(guild).Destinations()
        return current
                
    async def check_gifts(self, guild: discord.Guild, destination: str, apply_remove: bool = False, *, for_team: str = None) -> dict:
        teams = await self.config.guild(guild).Teams()
        destgifts = {}
        for t in teams:
            other_team = [c for c in ('red', 'green') if c != t][0]
            if t not in destgifts:
                destgifts[t] = []
            for g in teams[t]['Gifts']:
                if teams[t]['Gifts'][g]['destination'] == destination:
                    destgifts[t].append(g)
                    if apply_remove:
                        await self.team_remove_gift(guild, t, g)
                        gifttier = teams[t]['Gifts'][g]['tier']
                        await self.coal_add(guild, other_team, gifttier * 2)
                        
        return destgifts if not for_team else destgifts.get(for_team, None) 
    
    async def gen_gift_uid(self, guild: discord.Guild):
        teams = await self.config.guild(guild).Teams()
        collsafe = [i for t in teams for i in teams[t]['Gifts']]
        key = lambda: ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        
        newkey = key()
        while newkey in collsafe:
            newkey = key()
        return newkey
    
    
# TEAMS & MEMBRES ---------------------------------

    # Teams

    async def team_members(self, guild: discord.Guild, team: str) -> list:
        team = team.lower()
        all_members = await self.config.all_members(guild)
        return [m for m in all_members if all_members[m]['Team'] == team]

    async def check_team(self, user: discord.Member) -> str:
        guild = user.guild
        if not await self.config.member(user).Team():
            if len(await self.team_members(guild, 'green')) >= len(await self.team_members(guild, 'red')):
                await self.config.member(user).Team.set('red')
            else:
                await self.config.member(user).Team.set('green')
        return await self.config.member(user).Team()
    
    async def team_members_points(self, guild: discord.Guild, team: str) -> int:
        members = await self.team_members(guild, team)
        total = 0
        for m in members:
            total += await self.config.member_from_ids(guild.id, m).Points()
        return total
    
    # Cadeaux (Team)
    
    def fetch_gift_id(self, text: str):
        if text in self.gifts:
            return text
        
        text = text.lower()
        normgifts = {self.gifts[i].lower(): i for i in self.gifts}
        fuzzy_name = process.extractOne(text, list(normgifts.keys()), score_cutoff=85)
        if fuzzy_name:
            return normgifts[fuzzy_name[0]]
        
        return None
    
    async def get_team_gift(self, guild: discord.Guild, gift_key: str):
        gift_key = gift_key.upper()
        teams = await self.config.guild(guild).Teams()
        for t in ('green', 'red'):
            if gift_key in teams[t]['Gifts']:
                return t, teams[t]['Gifts'][gift_key]
        return None, None
    
    async def team_add_gift(self, guild: discord.Guild, team: str, gift_id: str, tier: int, destination: str) -> dict:
        team = team.lower()
        key = await self.gen_gift_uid(guild)
        gift = {'id': gift_id, 'tier': tier, 'destination': destination, 'max_tier': tier + 2}
        try:
            await self.config.guild(guild).Teams.set_raw(team, 'Gifts', key, value=gift)
        except KeyError:
            raise
        return gift
    
    async def team_remove_gift(self, guild: discord.Guild, team: str, gift_key: str):
        gift_key = gift_key.upper()
        team = team.lower()
        try:
            await self.config.guild(guild).Teams.clear_raw(team, 'Gifts', gift_key)
        except KeyError:
            raise
        
    async def team_gifts(self, guild: discord.Guild, team: str) -> dict:
        team = team.lower()
        try:
            gifts = await self.config.guild(guild).Teams.get_raw(team, 'Gifts')
        except KeyError:
            raise
        return gifts
    
    async def team_check_upgrade(self, guild: discord.Guild, gift_key: str) -> dict:
        gift_key = gift_key.upper()
        _, gift = await self.get_team_gift(guild, gift_key)
        tier = gift['tier']
        seed = f"{gift_key}:{tier}"
        rng = random.Random(seed)
        
        items = rng.sample(list(self.items.keys()), k=rng.randint(tier, len(self.items) - 1))
        return {i: rng.randint(tier, tier * 2) for i in items}
    
    async def team_upgrade_gift(self, guild: discord.Guild, team: str, gift_key: str, *, add_lvl: int = 1):
        gift_key = gift_key.upper()
        gifts = await self.team_gifts(guild, team)
        if gift_key not in gifts:
            raise KeyError(f"Le cadeau {gift_key} n'existe pas")
        
        await self.config.guild(guild).Teams.set_raw(team, 'Gifts', gift_key, 'tier', value=gifts[gift_key]['tier'] + add_lvl)
        
        
    async def get_gift_points(self, gift_data: dict) -> int:
        base = 25
        base += 25 * gift_data.get('tier', 1)
        return base
        
    # Inventaire
    
    def get_item(self, item_id: str) -> Item:
        if item_id not in self.items:
            raise KeyError("Item inexistant")
        return Item(self, item_id)
    
    async def inventory_items(self, user: discord.Member) -> Tuple[Item, int]:
        inv = await self.config.member(user).Inventory()
        return [(self.get_item(p), inv[p]) for p in inv if p in self.items]

    async def inventory_add(self, user: discord.Member, item: Item, amount: int):
        await self.check_team(user)
        
        if amount < 0:
            raise ValueError("Quantité d'items négative")
        inv = await self.config.member(user).Inventory()
        await self.config.member(user).Inventory.set_raw(item.id, value=inv.get(item.id, 0) + amount)
    
    async def inventory_remove(self, user: discord.Member, item: Item, amount: int):
        await self.check_team(user)
        
        amount = abs(amount)
        inv = await self.config.member(user).Inventory()
        if amount > inv.get(item.id, 0):
            raise ValueError("Quantité d'items possédés insuffisante")
        
        if inv.get(item.id, 0) - amount > 0:
            await self.config.member(user).Inventory.set_raw(item.id, value=inv.get(item.id, 0) - amount)
        else:
            try:
                await self.config.member(user).Inventory.clear_raw(item.id)
            except KeyError:
                pass
            
    
    async def wish_list(self, user: discord.Member):
        await self.check_team(user)
        return await self.config.member(user).Wishes()
    
    async def wish_add(self, user: discord.Member, gift_id: str, amount: int = 1):
        await self.check_team(user)
        
        if amount < 0:
            raise ValueError("Quantité de voeux négatif")
        
        wishes = await self.config.member(user).Wishes()
        await self.config.member(user).Wishes.set_raw(gift_id, value=wishes.get(gift_id, 0) + amount)
        
    async def wish_remove(self, user: discord.Member, gift_id: str, amount: int):
        await self.check_team(user)
        
        amount = abs(amount)
        wishes = await self.config.member(user).Wishes()
        if amount > wishes.get(gift_id, 0):
            raise ValueError("Quantité de voeux possédés insuffisants")
        
        if wishes.get(gift_id, 0) - amount > 0:
            await self.config.member(user).Wishes.set_raw(gift_id, value=wishes.get(gift_id, 0) - amount)
        else:
            try:
                await self.config.member(user).Wishes.clear_raw(gift_id)
            except KeyError:
                pass
            
            
    async def coal_check(self, guild: discord.Guild, team: str, amount: int) -> bool:
        coalinv = await self.config.guild(guild).Teams.get_raw(team, 'Coal')
        return coalinv >= amount
    
    async def coal_set(self, guild: discord.Guild, team: str, amount: int) -> int:
        if amount < 0:
            raise ValueError("Impossible de mettre une valuer négative de charbon")
        
        await self.config.guild(guild).Teams.set_raw(team, 'Coal', value=amount)
        return amount
    
    async def coal_add(self, guild: discord.Guild, team: str, amount: int) -> int:
        if amount < 0:
            raise ValueError("Impossible d'ajouter une valuer négative de charbon")
        
        current = await self.config.guild(guild).Teams.get_raw(team, 'Coal')
        return await self.coal_set(guild, team, current + amount)

    async def coal_remove(self, guild: discord.Guild, team: str, amount: int) -> int:
        amount = abs(amount)
        if not await self.coal_check(guild, team, amount):
            raise ValueError(f"Quantité de charbon insuffisante dans la team {team}")

        current = await self.config.guild(guild).Teams.get_raw(team, 'Coal')
        return await self.coal_set(guild, team, current - amount)
    
    # Quetes
    
    async def set_quest(self, user: discord.Member, quest_id: str, threshold: int) -> dict:
        q = {'id': quest_id,
             'threshold': threshold,
             'current': 0}
        await self.config.member(user).Quest.set(q)
        return q
    
    async def update_quest(self, user: discord.Member, quest_id: str, amount: int = 1) -> bool:
        currentq = await self.config.member(user).Quest()
        if currentq.get('id', None) != quest_id:
            return
        
        newam = currentq.get('current', 0) + amount
        await self.config.member(user).Quest.set_raw('current', value=newam)
        
        return newam
    
    async def clear_quest(self, user: discord.Member):
        await self.config.member(user).clear_raw('Quest')
        
    async def check_quest(self, user: discord.Member):
        currentq = await self.config.member(user).Quest()
        if not currentq:
            return False 
        if currentq['current'] < currentq['threshold']:
            return False
        
        userteam = await self.check_team(user)
        qid = currentq['id']
        prize = QUEST_INFO[qid]['prize']
        qlevel = QUEST_INFO[qid]['level']
        tb = ''
        if prize == "coal":
            cqte = qlevel * 2
            await self.coal_add(user.guild, userteam, cqte)
            tb = f"Charbon x{cqte}"
        elif prize == "items":
            rdm_item = random.choice(list(self.items.keys()))
            item = self.get_item(rdm_item)
            qte = random.randint(qlevel + 1, qlevel * 2)
            await self.inventory_add(user, item, qte)
            tb = f"{item.name} x{qte}"
        
        tb += " + 5 points personnels"
        
        userpts = await self.config.member(user).Points()
        await self.config.member(user).Points.set(userpts + 5)
        
        await self.clear_quest(user)
        return tb
        
    
# COMMANDES ======================================

    @commands.command(name='inv', aliases=['pck'])
    async def display_xmas_inventory(self, ctx, user: discord.Member = None):
        """Afficher son inventaire personnel du Jeu des fêtes ou celui du membre mentionné
        
        Affiche aussi diverses informations utiles sur le membre"""
        user = user if user else ctx.author
        
        team = await self.check_team(user)
        teaminfo = TEAMS_PRP[team]
        userdata = await self.config.member(user).all()
        
        em = discord.Embed(color=teaminfo['color'])
        em.set_author(name=f"{user.name}", icon_url=user.avatar_url)
        
        desc = f"**Nb. de voeux** · {sum([userdata['Wishes'][w] for w in userdata['Wishes']])}\n"
        desc += f"**Points personnels** · {userdata['Points']}"
        em.description = desc
        
        items = await self.inventory_items(user)
        items_table = [(f"{item.name}", qte) for item, qte in items]
        if items_table:
            invsum = sum([qte for _, qte in items])
            em.add_field(name=f"Inventaire (#{invsum})", value=box(tabulate(items_table, headers=('Item', 'Qte')), lang='css'))
        else:
            em.add_field(name=f"Inventaire (#0)", value=box("Inventaire vide", lang='css'))
            
        em.set_footer(text=f"{teaminfo['name']}", icon_url=teaminfo['icon'])
        await ctx.reply(embed=em, mention_author=False)
    
    @commands.command(name='craft', aliases=['voeux'])
    async def user_craft_gift(self, ctx, *, gift: str = None):
        """Permet de créer des cadeaux avec des voeux
        
        Affiche votre inventaire de voeux si aucun ID de cadeau n'est précisé"""
        user = ctx.author
        guild = ctx.guild
        team = await self.check_team(user)
        teaminfo = TEAMS_PRP[team]
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        
        if not gift:
            wishes = await self.wish_list(user)
            wishes_table = [(int(w), f"{self.gifts[w]}", wishes[w]) for w in wishes]
            wishes_table = sorted(wishes_table, key=operator.itemgetter(2), reverse=True)
            em = discord.Embed(color=teaminfo['color'])
            em.set_author(name=f"Voeux obtenus", icon_url=user.avatar_url)
            if wishes_table:
                tables = [wishes_table[x:x+20] for x in range(0, len(wishes_table), 20)]
                n = 1
                for wt in tables:
                    em.description = box(tabulate(wt, headers=('ID', 'Cadeau', 'Qte')), lang='css')
                    em.set_footer(text=f"Craftez un cadeau en faisant ';craft <ID>' | Page {n}")
                    await ctx.reply(embed=em, mention_author=False)
                    n += 1
                return
            else:
                em.description = box("Inventaire de voeux vide", lang='css')
                em.set_footer(text="Obtenez des voeux en livrant les cadeaux de votre équipe")
                return await ctx.reply(embed=em, mention_author=False)

        giftid = self.fetch_gift_id(gift)
        if not giftid:
            return await ctx.reply(f"{alert} **Cadeau inconnu** · Vérifiez le nom du cadeau ou tapez son numéro", mention_author=False)
        
        try: 
            await self.wish_remove(user, giftid, 3)
        except:
            em = discord.Embed(color=teaminfo['color'])
            em.set_author(name=f"Craft de cadeaux · Erreur", icon_url=user.avatar_url)
            em.description = f"{alert} Vous n'avez pas assez de voeux pour crafter un cadeau. Collectez au moins 3x voeux d'un même cadeau pour le créer."
            em.set_footer(text="Consultez vos voeux disponibles avec ';craft'")
            return await ctx.reply(embed=em, mention_author=False)
        
        if random.randint(0, 4):
            dests = await self.fill_destinations(guild)
            dest = random.choice(dests[5:])
            
            giftdata = {'gift_id': giftid, 'tier': 1, 'destination': dest} 
            await self.team_add_gift(guild, team, **giftdata)
            em = discord.Embed(color=teaminfo['color'])
            em.set_author(name=f"Craft de cadeaux · Réussite", icon_url=user.avatar_url)
            em.description = f"{check} Vous avez créé **{self.gifts[giftid]} [Tier 1]** pour votre équipe, les *{teaminfo['name']}*."
            em.set_footer(text="Consultez les cadeaux à livrer avec ';gifts'")
        else:
            em = discord.Embed(color=teaminfo['color'])
            em.set_author(name=f"Craft de cadeaux · Echec", icon_url=user.avatar_url)
            em.description = f"{cross} Vous n'avez pas réussi à créer un cadeau pour votre équipe, les *{teaminfo['name']}*."
            em.set_footer(text="Consultez les cadeaux à livrer avec ';gifts'")
        await ctx.reply(embed=em, mention_author=False)
            
            
    @commands.command(name='team', aliases=['teams'])
    async def disp_team_info(self, ctx):
        """Affiche un résumé des informations importantes de votre team et de la team adverse"""
        user = ctx.author
        guild = ctx.guild
        userteam = await self.check_team(user)
        
        async def get_info(t: str) -> discord.Embed:
            teaminfo = TEAMS_PRP[t]
            teamdata = await self.config.guild(guild).Teams.get_raw(t)
            em = discord.Embed(color=teaminfo['color'], title=f"**{teaminfo['name']}**")
            em.set_thumbnail(url=teaminfo['icon'])
            desc = f"**Points** · {teamdata['Points'] + await self.team_members_points(guild, t)}\n"
            desc += f"› Dont points de membres · {await self.team_members_points(guild, t)}\n"
            desc += f"**Cadeaux à distribuer** · {len(await self.team_gifts(guild, t))}\n"
            desc += f"**Charbon** · {await self.config.guild(guild).Teams.get_raw(t, 'Coal')}"
            em.description = desc
            
            currentdest = await self.fill_destinations(guild)
            currentdest = currentdest[0]
            tlist = await self.check_gifts(guild, currentdest, for_team=t)
            teamgifts = await self.team_gifts(guild, t)
            glist = []
            for gtid in tlist:
                tg = teamgifts[gtid]
                giftname = self.gifts[tg['id']]
                glist.append((gtid, giftname, tg['tier']))
            glist = glist[:5]
            gtxt = '\n'.join([f'• **{i}** · *{n}* [T{tier}]' for i, n, tier in glist])
            em.add_field(name="Cadeaux actuellement à livrer", value=gtxt if gtxt else f"Aucun cadeau n'est à livrer pour *{currentdest}*", inline=False)
            
            contrib = await self.team_members(guild, t)
            gmpts = []
            for mu in contrib:
                gm = guild.get_member(mu)
                if gm:
                    gmpts.append((gm.name, await self.config.member(gm).Points()))
            best = sorted(gmpts, key=operator.itemgetter(1), reverse=True)
            besttabl = tabulate(best[:5], headers=('Membre', 'Points'))
            if best:
                em.add_field(name="Top 5 contributeurs", value=box(besttabl), inline=False)
            else:
                em.add_field(name="Top 5 contributeurs", value=box("Aucun contributeur pour le moment"))
            
            em.set_footer(text=f"Actuellement à : {currentdest} ({self.countries[currentdest]})")
            return em
        
        embeds = [await get_info(userteam), await get_info([c for c in ('red', 'green') if c != userteam][0])]
        await menu(ctx, embeds, DEFAULT_CONTROLS)
        
    @commands.command(name='teamtop')
    async def show_teams_top(self, ctx, top: typing.Optional[int] = 20, team: str = None):
        """Affiche un top des contributeurs de votre team
        
        Changez le paramètre [top] pour obtenir un top plus ou moins complet
        Vous pouvez rentrer un nom de team pour consulter une autre team que la votre ou 'global' pour voir le top global"""
        guild = ctx.guild
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        
        if team:
            team = team.lower()
            
            if team == 'global':
                em = discord.Embed(title="Classement Global de l'Event", color=XMAS_COLOR())
                
                glist = [(TEAMS_PRP[t]['name'], await self.team_members_points(guild, t) + await self.config.guild(guild).Teams.get_raw(t, 'Points')) for t in ('red', 'green')]
                classg = sorted(glist, key=operator.itemgetter(1), reverse=True)
                em.add_field(name="Teams", value=box(tabulate(classg)), inline=False)
                
                all_members = await self.config.all_members(guild)
                mlist = [(guild.get_member(m), TEAMS_PRP[all_members[m]['Team']]['name'], all_members[m]['Points']) for m in all_members if m]
                topm = sorted(mlist, key=operator.itemgetter(2), reverse=True)
                em.add_field(name=f"Top {top} contributeurs (Points perso.)*", value=box(tabulate(topm[:top], headers=['Membre', 'Team', 'Points'])), inline=False)
            
                em.set_footer(text="*Comprend les points des membres de la team et ceux de l'équipe (livraisons de cadeaux)")
                try:
                    await ctx.reply(embed=em, mention_author=False)
                except:
                    await ctx.reply(f"{alert} **Top trop grand** · Impossible d'afficher une liste aussi longue. Réduisez le nombre au paramètre [top].",
                                        mention_author=False)
                return
            
            if team not in list(TEAMS_PRP.keys()):
                isname = [g for g in TEAMS_PRP if TEAMS_PRP[g]['name'].lower() == team]
                if isname:
                    team = isname[0]
                else:
                    return await ctx.reply(f"{alert} **Nom invalide** · Ce nom ne correspond à aucune guilde existante.",mention_author=False)
        else:
            team = await self.check_team(ctx.author)
            
        teaminfo = TEAMS_PRP[team]
        members = await self.team_members(guild, team)
        members = [guild.get_member(m) for m in members]
        members_data = await self.config.all_members(guild)
        mscore = [(m.name, members_data[m.id]['Points']) for m in members if m]
        msort = sorted(mscore, key=operator.itemgetter(1), reverse=True)
        
        em = discord.Embed(color=teaminfo['color'])
        em.set_author(name=f"Team des {teaminfo['name']}", icon_url=teaminfo['icon'])
        em.description = box(tabulate(msort[:top], headers=['Membre', 'Points']))
        pts = await self.team_members_points(guild, team) + await self.config.guild(guild).Teams.get_raw(team, 'Points')
        em.set_footer(text=f"Total de l'équipe : {pts}")
        
        try:
            await ctx.reply(embed=em, mention_author=False)
        except:
            await ctx.reply(f"{alert} **Top trop grand** · Impossible d'afficher une liste aussi longue. Réduisez le nombre au paramètre [top].",
                                   mention_author=False)
            
            
    @commands.command(name='gifts', aliases=['g'])
    async def disp_team_gifts(self, ctx):
        """Affiche tous les cadeaux à livrer de votre équipe"""
        user = ctx.author
        guild = ctx.guild
        team = await self.check_team(user)
        teaminfo = TEAMS_PRP[team]
        
        teamgifts = await self.team_gifts(guild, team)
        glist = []
        dests = await self.fill_destinations(guild)
        for d in dests:
            localgifts = await self.check_gifts(guild, d, for_team=team)
            for gtid in localgifts:
                tg = teamgifts[gtid]
                giftname = self.gifts[tg['id']]
                glist.append((gtid, giftname, teamgifts[gtid]['tier'], d if len(d) < 20 else d[:17] + '⋯'))
        
        tabls = [glist[x:x+20] for x in range(0, len(glist), 20)]
        embeds = []
        for t in tabls:
            em = discord.Embed(color=teaminfo['color'], title=f"Cadeaux à livrer · {teaminfo['name']}")
            em.description = '\n'.join([f'• **{i}** · *{n}*  [T{tier}] ➞ __{d}__' for i, n, tier, d in t])
            em.set_footer(text="Livrez un cadeau en faisant ';ship <ID>' ou ';deliver <ID>'")
            embeds.append(em)
        
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            em = discord.Embed(color=teaminfo['color'], title=f"Cadeaux à livrer · {teaminfo['name']}")
            em.description = "**Aucun cadeau à livrer actuellement**"
            em.set_footer(text="Livrez un cadeau en faisant ';ship <ID>' ou ';deliver <ID>'")
            return await ctx.send(embed=em)
        
    @commands.command(name='ship', aliases=['deliver'])
    async def ship_team_gift(self, ctx, gift_key: str = None):
        """Livrer un cadeau
        
        Il faut que la destination du cadeau à livrer corresponde à la position actuelle du traineau"""
        user = ctx.author
        guild = ctx.guild
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        
        if not gift_key:
            return await ctx.reply(f"{alert} **Précisez le cadeau à livrer** · Consultez la liste des cadeaux à livrer avec `;gifts`")
        
        gift_key = gift_key.upper()
        team, gift = await self.get_team_gift(guild, gift_key)
        if not gift:
            return await ctx.reply(f"{cross} **ID de cadeau inconnu** · Consultez la liste des cadeaux à livrer avec `;gifts`")
        
        userteam = await self.check_team(user)
        if team != userteam:
            return await ctx.reply(f"{cross} **ID de cadeau invalide** · Ce cadeau est à l'équipe adverse !")

        dests = await self.fill_destinations(guild)
        dest = dests[0]

        if gift['destination'] != dest:
            return await ctx.reply(f"{cross} **Mauvaise destination** · Ce cadeau doit être livré à *{gift['destination']}* alors que nous sommes actuellement à ***{dest}*** !")
            
        teaminfo = TEAMS_PRP[team]
        try:
            await self.team_remove_gift(guild, team, gift_key)
        except:
            return await ctx.reply(f"{cross} **Impossible de livrer le cadeau** · Il y a eu une erreur lors de la livraison du cadeau")

        pts = await self.get_gift_points(gift)
        teampts = await self.config.guild(guild).Teams.get_raw(team, 'Points')
        await self.config.guild(guild).Teams.set_raw(team, 'Points', value=teampts + pts)
        userpts = await self.config.member(user).Points()
        await self.config.member(user).Points.set(userpts + 10)
        
        await ctx.send(f"{check} 🎁 **Livraison effectuée** · Le cadeau **{gift_key}** contenant *{self.gifts[gift['id']]}* a été livré à {dest} !\nL'équipe des {teaminfo['name']} remporte **+{pts} Points** et {user.mention} en remporte 10.")
    
        wishesrdm = random.choices(list(self.gifts.keys()), k=random.randint(2, 3))
        wishes = {w: wishesrdm.count(w) for w in set(wishesrdm)}
        wl = []
        for w in wishes:
            await self.wish_add(user, w, wishes[w])
            wl.append(f"`{self.gifts[w]} x{wishes[w]}`")
        
        if wishes:
            await ctx.reply(f"☄️ **Voeux gagnés** · Vous remportez des voeux pour {' '.join(wl)} pour avoir livré le cadeau avec succès !")
    
    @commands.command(name='map', aliases=['dest'])
    async def disp_dests_map(self, ctx):
        """Affiche les 10 prochaines destinations"""
        guild = ctx.guild
        dests = await self.fill_destinations(guild)
        dests = dests[:10]
        
        team = await self.check_team(ctx.author)
        gifts = await self.team_gifts(guild, team)
        giftds = set([gifts[n]['destination'] for n in gifts])
        
        txt = "\n".join([f"{'•' if dests.index(d) == 0 else '·'} {d} ({self.countries[d]}) {'🎁' if d in giftds else ''}" for d in dests])
        em = discord.Embed(color=XMAS_COLOR())
        em.set_author(name="Prochaines destinations", icon_url=TEAMS_PRP[team]['icon'])
        em.description = box(txt, lang='css')
        
        lastdest = await self.config.guild(guild).LastDestChange()
        lastdest = lastdest if lastdest else time.time()
        nxtdest = lastdest + DEST_TIME()
        dtxt = datetime.now().fromtimestamp(nxtdest).strftime('%H:%M')
        em.add_field(name="Prochaine dest. vers", value=box(f"{dtxt} ➞ {dests[1]}"))
        
        em.set_footer(text="Consultez les cadeaux à livrer dans ';team' ou avec ';gifts'")
        await ctx.reply(embed=em, mention_author=False)
        
    @commands.command(name='upgrade', aliases=['amelio'])
    async def main_upgrade_gift(self, ctx, gift_key: str = None):
        """Améliorer un cadeau possédé afin de le faire monter en tier (grade)
        
        Faire la commande sans argument permet d'obtenir une liste des améliorations possibles"""
        user = ctx.author
        guild = ctx.guild
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        userteam = await self.check_team(user)
        teaminfo = TEAMS_PRP[userteam]
        
        if not gift_key:
            inv = await self.config.member(user).Inventory()
            gifts = await self.team_gifts(guild, userteam)
            gup = []
            for g in gifts:
                if gifts[g]['max_tier'] > gifts[g]['tier']:
                    up = await self.team_check_upgrade(guild, g)
                    verif = []
                    for u in up:
                        if inv.get(u, 0) >= up[u]:
                            verif.append(u)
                    if len(verif) == len(up):
                        gup.append((g, self.gifts[gifts[g]['id']], f"T{gifts[g]['tier']} ➞ T{gifts[g]['tier'] + 1}"))
            if not gup:
                return await ctx.reply(f"{alert} **Aucun cadeau à améliorer** · Vous ne pouvez pas améliorer de cadeau soit parce qu'il n'y en a pas à améliorer soit parce que vous n'avez pas les items nécessaires pour le faire.")
            
            tables = [gup[x:x+20] for x in range(0, len(gup), 20)]
            embeds = []
            for t in tables:
                em = discord.Embed(color=teaminfo['color'], title=f"Améliorations possibles · {teaminfo['name']}")
                em.description = box('\n'.join([f'{gkey} · {gname} ({tierup})' for gkey, gname, tierup in t]))
                em.set_footer(text="Améliorez un cadeau avec ';upgrade <ID>'")
                embeds.append(em)
            
            return await menu(ctx, embeds, DEFAULT_CONTROLS)
        
        gift_key = gift_key.upper()
        gteam, gift = await self.get_team_gift(guild, gift_key)
        if not gift:
            return await ctx.reply(f"{alert} **Erreur** · Ce cadeau n'existe pas ou n'est pas de votre équipe. Vérifiez l'identifiant.")
        
        gname = self.gifts[gift['id']]
        if gteam != userteam:
            return await ctx.reply(f"{alert} **Erreur** · Ce cadeau n'existe pas ou n'est pas de votre équipe. Vérifiez l'identifiant.")
        
        if gift['max_tier'] <= gift['tier']:
            return await ctx.reply(f"{alert} **Niveau maximal** · Ce cadeau a déjà atteint son Tier maximal (**T{gift['tier']}**) et ne peut être amélioré davantage.")
        
        upgrade = await self.team_check_upgrade(guild, gift_key)
        
        em = discord.Embed(color=teaminfo['color'], title=f"Améliorer un cadeau · `{gift_key}` *{gname}*")
        em.description = f"**Voulez-vous améliorer ce cadeau pour le faire passer en __Tier {gift['tier'] + 1}__ ?**"
        tabl = [(self.items[i]['name'], upgrade[i]) for i in upgrade]
        em.add_field(name="Items demandés", value=box(tabulate(tabl, headers=('Item', 'Qté'))), inline=False)
        em.set_footer(text="Améliorer | Annuler")
        
        msg = await ctx.reply(embed=em, mention_author=False)
        start_adding_reactions(msg, [check, cross])
        try:
            react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id, timeout=40)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"{cross} **Annulé** · L'amélioration du cadeau a été abandonnée.", mention_author=False)
        if react.emoji == cross:
            await msg.delete(delay=5)
            return await ctx.reply(f"{cross} **Annulé** · L'amélioration du cadeau a été abandonnée.", mention_author=False)
        
        inv = await self.config.member(user).Inventory()
        for u in upgrade:
            if inv.get(u, 0) < upgrade[u]:
                return await ctx.reply(f"{cross} **Impossible** · Vous ne possédez pas tous les items demandés.", mention_author=False)
        
        async with ctx.typing():
            await asyncio.sleep(random.randint(1, 2))
            for ui in upgrade:
                await self.inventory_remove(user, self.get_item(ui), upgrade[ui])
            
            await self.team_upgrade_gift(guild, userteam, gift_key)
        await ctx.reply(f"{check} **Amélioration effectuée** · Le cadeau **{gift_key}** contenant *{gname}* est désormais __Tier {gift['tier'] + 1}__ !", mention_author=False)
        
        await self.update_quest(user, 'upgrade_any')
        if gift['tier'] == 2:
            await self.update_quest(user, 'upgrade_T3')
        if gift['tier'] >= 3:
            await self.update_quest(user, 'upgrade_T45')
        
    @commands.command(name='coal', aliases=['charbon'])
    async def use_coal(self, ctx, qte: int):
        """Utiliser du charbon pour réduire les niveaux des cadeaux de l'autre équipe
        
        Plus la quantité de charbon utilisée est grande (de 1 à 10) plus les chances de toucher un cadeau adverse sont hautes"""
        user = ctx.author
        guild = ctx.guild
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        userteam = await self.check_team(user)
        
        if qte < 1:
            return await ctx.reply(f"{alert} **Valeur invalide** · Vous ne pouvez pas utiliser moins d'un charbon.",
                                   mention_author=False)
        
        cache = self.get_cache(guild)
        if cache['CoalCD'].get(userteam, 0) + 2700 > time.time():
            new = (cache['CoalCD'].get(userteam, 0) + 2700) - time.time()
            return await ctx.reply(f"{cross} **Cooldown** · Vous devez patienter encore *{humanize_timedelta(seconds=new)}* avant de pouvoir réutiliser du Charbon pour saboter les cadeaux adverses.",
                                   mention_author=False)
        
        if qte > 10:
            qte = 10
            await ctx.reply(f"{alert} **Qté modifiée** · Vous ne pouvez pas utiliser plus de 10x Charbon à la fois, j'ai donc réduit pour vous la quantité misée.",
                                   mention_author=False)
            
        otherteam = [c for c in ('red', 'green') if c != userteam][0]
        tgifts = await self.team_gifts(guild, otherteam)
        if not tgifts:
            return await ctx.reply(f"{alert} **Impossible** · L'équipe adverse n'a pas de cadeaux à livrer !")
        
        cache['CoalCD'][userteam] = time.time()
        async with ctx.typing():
            await asyncio.sleep(random.randint(2, 3))
            try:
                await self.coal_remove(guild, userteam, qte)
            except:
                return await ctx.reply(f"{cross} **Erreur** · Il est probable que votre équipe ne possède pas cette quantité de Charbon. Réessayez avec une plus petite valeur.",
                                    mention_author=False)
        
        if random.randint(0, qte) == 0:
            return await ctx.reply(f"{cross} **Echec** · Vous n'avez pas réussi à saboter un cadeau de l'équipe adverse, dommage !")
        
        rdm = random.choice(list(tgifts.keys()))
        currentgift = await self.config.guild(guild).Teams.get_raw(otherteam, 'Gifts', rdm)
        if currentgift['tier'] > 1:
            await self.config.guild(guild).Teams.set_raw(otherteam, 'Gifts', rdm, 'tier', value=currentgift['tier'] - 1)
            await ctx.reply(f"{check} **Cadeau saboté** · Vous avez réussi à saboter le cadeau **{rdm}** (contenant *{self.gifts[currentgift['id']]}*) de l'équipe des *{TEAMS_PRP[otherteam]['name']}* en le faisant passer du __Tier {currentgift['tier']}__ au __Tier {currentgift['tier'] - 1}__ !")
        else:
            if qte > 1:
                await self.coal_add(guild, userteam, round(qte / 2))
            await ctx.reply(f"{check} **Echec** · Vous avez tenté de saboter un cadeau qui était déjà au tier le plus bas... Dommage !\nLa moitié de votre Charbon a été remboursé.")
    
    
    @commands.command(name='slow')
    async def vote_slow(self, ctx):
        """Voter pour ralentir temporairement le traineau
        
        Vous pouvez voter une fois par heure
        Il faut réunir au moins un vote d'un membre de chaque équipe pour ralentir le traineau (15m le jour, 30m la nuit)"""
        user = ctx.author
        guild = ctx.guild
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        
        cache = self.get_cache(guild)
        
        userdata = await self.config.member(user).all()
        ucache = userdata.get('SlowCache', {'last': 0, 'dest': ''})
            
        if ucache['last'] + 3600 > time.time():
            new = (ucache['last'] + 3600) - time.time()
            return await ctx.reply(f"{cross} **Cooldown** · Vous devez patienter encore *{humanize_timedelta(seconds=new)}* avant de pouvoir voter de nouveau pour ralentir le traineau.",
                                   mention_author=False)
        
        curdest = await self.fill_destinations(guild)
        curdest = curdest[0]
        if cache['SlowDest'] == curdest:
            return await ctx.reply(f"{alert} **Inutile** · Le traineau a déjà été ralenti pour la position actuelle.",
                                   mention_author=False)
            
        if ucache['dest'] == curdest:
            return await ctx.reply(f"{alert} **Inutile** · Vous avez déjà voté pour la position actuelle.",
                                   mention_author=False)
        
        ucache['last'] = time.time()
        ucache['dest'] = curdest
        await self.config.member(user).SlowCache.set(ucache)
        all_members = await self.config.all_members(guild)
        for u in [i for i in all_members if i != user.id and all_members[i]['SlowCache']['dest'] == curdest]:
            otheru = guild.get_member(u)
            if await self.check_team(otheru) != await self.check_team(user):
                cache['SlowDest'] = curdest
                lastchange = await self.config.guild(guild).LastDestChange()
                diff = 1800 if 2 <= datetime.now().hour <= 9 else 900
                await self.config.guild(guild).LastDestChange.set(lastchange + diff)
                return await ctx.reply(f"{check} **Traineau ralenti** · Le traineau va rester {int(diff / 60)}m de plus à notre position actuelle, **{curdest}**.",
                                   mention_author=False)
        await ctx.reply(f"{check} **Vote pris en compte** · Il faut qu'un membre de l'équipe adverse vote aussi pour ralentir le traineau pour la position actuelle.",
                                   mention_author=False)
        
    @commands.command(name='hat', aliases=['bonnet'])
    async def toggle_user_hat(self, ctx):
        """Activer/désactiver l'affichage de son équipe par le biais d'un rôle avec un icône de bonnet de la couleur de votre équipe"""
        guild = ctx.guild
        user = ctx.author
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        
        team = await self.check_team(user)
        sett = await self.config.guild(guild).Settings()
        redid, greenid = sett.get(f'red_role', None), sett.get(f'green_role', None)
        if not (redid and greenid):
            return await ctx.reply(f"{cross} **Rôles non configurés**",
                                   mention_author=False)
        
        red, green = guild.get_role(redid), guild.get_role(greenid)
        if not (red and green):
            return await ctx.reply(f"{cross} **Rôles configurés mais inexistants**",
                                   mention_author=False)
        
        if team == 'red' and red in user.roles:
            await user.remove_roles(red, reason="Désactivation du bonnet d'équipe")
            return await ctx.reply(f"{check} **Rôle Lutin Rouge retiré** · Vous avez retiré votre bonnet", mention_author=False)
        elif team == 'red':
            await user.add_roles(red, reason=f"Ajout du rôle d'équipe") 
            if green in user.roles:
                await user.remove_roles(green, reason="Changement de rôle d'équipe")
            return await ctx.reply(f"{check} **Rôle Lutin Rouge ajouté** · Vous avez enfilé votre bonnet", mention_author=False)
                
            
        if team == 'green' and green in user.roles:
            await user.remove_roles(green, reason="Désactivation du bonnet d'équipe")
            return await ctx.reply(f"{check} **Rôle Lutin Vert retiré**  · Vous avez retiré votre bonnet", mention_author=False)
        elif team == 'green':
            await user.add_roles(green, reason=f"Ajout du rôle d'équipe") 
            if red in user.roles:
                await user.remove_roles(red, reason="Changement de rôle d'équipe")
            return await ctx.reply(f"{check} **Rôle Lutin Vert ajouté** · Vous avez enfilé votre bonnet", mention_author=False)
        
    @commands.command(name="questmp", aliases=['stopmp'])
    async def toggle_pm_reception(self, ctx):
        """Active/désactive la réception de MP quand vous accomplissez une quête dont vous n'avez pas manuellement vérifié le statut"""
        guild = ctx.guild
        user = ctx.author
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        
        current = await self.config.member(user).QuestGetMP()
        if current:
            await ctx.reply(f"{check} **MP désactivés** · Vous ne recevrez plus de MP en cas d'accomplissement d'une quête non vérifiée manuellement", mention_author=False)
        else:
            await ctx.reply(f"{check} **MP activés** · Vous recevrez désormais un MP en cas d'accomplissement d'une quête non vérifiée manuellement", mention_author=False)
        await self.config.member(user).QuestGetMP.set(not current)
        
    @commands.command(name='quest', aliases=['mission'])
    async def user_quest(self, ctx):
        """Consulter sa mission actuelle et vérifier son avancement"""
        user = ctx.author
        check, cross, alert = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551), self.bot.get_emoji(913597560483106836)
        
        curtime = 'AM' if 0 <= datetime.now().hour <= 11 else 'PM'
        curtime += datetime.now().strftime('%d%m')
        quest = await self.config.member(user).Quest()
        if not quest:
            if await self.config.member(user).QuestLast() == curtime:
                return await ctx.reply(f"{cross} **Aucune mission disponible** · Vous pourrez avoir de nouveau une mission à midi/minuit", mention_author=False)
                
            rdmq = random.choice(list(QUEST_INFO.keys()))
            thre = QUEST_INFO[rdmq]['threshold']
            quest = await self.set_quest(user, rdmq, thre)
            await self.config.member(user).QuestLast.set(curtime)
            
        complete = await self.check_quest(user)
        em = discord.Embed(color=XMAS_COLOR())
        em.set_author(name=f"{user} · Quête actuelle ({'AM' if 0 <= datetime.now().hour <= 11 else 'PM'})", icon_url=user.avatar_url)
        
        qinfo = QUEST_INFO[quest['id']]
        em.description = f"📜 **Mission** · *{qinfo['desc']}*"
        em.add_field(name="Avancement", value=f"**{quest['current']}**/{quest['threshold']}{f' {check}' if complete else ''}")
        
        if complete:
            em.set_footer(text=f"Quête accomplie, vous remportez {complete}\n» Revenez à midi et minuit pour recevoir une nouvelle quête")
        
        await ctx.send(embed=em)
        
    
# LISTENERS --------------------------------------

    async def simple_item_spawn(self, channel: discord.TextChannel):
        rdm_item = random.choice(list(self.items.keys()))
        item = self.get_item(rdm_item)
        qte = random.randint(2, 5)
        emcolor = XMAS_COLOR()
        text = random.choice((f"Des enfants vous offrent **{item.famount(qte)}** !",
                              f"Voici **{item.famount(qte)}** ! Premier arrivé, premier servi.",
                              f"Vous trouvez **{item.famount(qte)}** par terre ! Prenez-les vite !",
                              f"Nouvelle livraison de **{item.famount(qte)}** ! Cliquez vite."))
        em = discord.Embed(title="❄️ Jeu des fêtes • Trouvaille d'items", 
                           description=text,
                           color=emcolor)
        
        emojis = ["⛄","❄️","🧊","🎄","🎁"]
        random.shuffle(emojis)
        emojis = emojis[:3]
        goodemoji = random.choice(emojis)
            
        em.set_footer(text=f"» Cliquez sur {goodemoji}")
        
        spawn = await channel.send(embed=em)
        start_adding_reactions(spawn, emojis)
        try:
            _, user = await self.bot.wait_for("reaction_add",
                                              check=lambda r, u: r.message.id == spawn.id and r.emoji == goodemoji and not u.bot,
                                              timeout=25)
        except asyncio.TimeoutError:
            await spawn.delete()
            return
        else:
            await self.inventory_add(user, item, qte)
            wintxt = random.choice((f"{user.mention} empoche **{item.famount(qte)}** avec succès !",
                                    f"C'est {user.mention} part avec **{item.famount(qte)}** !",
                                    f"{user.mention} repart avec **{item.famount(qte)}**.",
                                    f"Le lutin {user.mention} vient d'obtenir **{item.famount(qte)}**."
                                    ))
            post_em = discord.Embed(title="❄️ Jeu des fêtes • Trouvaille d'items", 
                                    description=wintxt,
                                    color=emcolor)
            post_em.set_footer(text="Astuce · " + random.choice(_ASTUCES))
            
            userquest = await self.config.member(user).Quest()
            if userquest:
                qtitle = f'get_{item.id}'
                if userquest['id'].startswith(qtitle):
                    await self.update_quest(user, userquest['id'], qte)
            
            await spawn.edit(embed=post_em)
            await spawn.remove_reaction(goodemoji, self.bot.user)
            await spawn.delete(delay=15)
            
    
    async def simple_gift_spawn(self, channel: discord.TextChannel):
        guild = channel.guild
        dests = await self.fill_destinations(guild)
        dest = random.choice(dests[3:])
        city = self.countries[dest]
        emcolor = XMAS_COLOR()
        
        giftdata = {'gift_id': random.choice(list(self.gifts.keys())), 'tier': random.randint(1, 2), 'destination': dest}
        giftname = self.gifts[giftdata['gift_id']]
        
        text = random.choice((f"Un cadeau pour **{city}** vient de sortir des Ateliers. Prenez-le en premier !",
                              f"Un nouveau cadeau est à livrer à **{city}**, dépêchez-vous !"))
        em = discord.Embed(title="❄️ Jeu des fêtes • Sortie d'ateliers", 
                           description=text,
                           color=emcolor)
        
        emojis = ["⛄","❄️","🧊","🎄","🎁"]
        random.shuffle(emojis)
        emojis = emojis[:3]
        goodemoji = random.choice(emojis)
            
        em.set_footer(text=f"» Cliquez sur {goodemoji} pour obtenir le cadeau pour votre équipe")
        
        spawn = await channel.send(embed=em)
        start_adding_reactions(spawn, emojis)
        try:
            _, user = await self.bot.wait_for("reaction_add",
                                              check=lambda r, u: r.message.id == spawn.id and r.emoji == goodemoji and not u.bot,
                                              timeout=15)
        except asyncio.TimeoutError:
            await spawn.delete()
            return
        else:
            team = await self.check_team(user)
            teaminfo = TEAMS_PRP[team]
            await self.team_add_gift(guild, team, **giftdata)
            wintxt = random.choice((
                f"C'est l'équipe des **{teaminfo['name']}** qui part avec __{giftname} [T{giftdata['tier']}]__ grâce à {user.mention} !",
                f"L'équipe des **{teaminfo['name']}** remporte __{giftname} [T{giftdata['tier']}]__ grâce à {user.mention} !",
                f"{user.mention} fait gagner __{giftname} [T{giftdata['tier']}]__ à son équipe, les **{teaminfo['name']}** !",
            ))
            post_em = discord.Embed(title="❄️ Jeu des fêtes • Sortie d'ateliers", 
                                    description=wintxt,
                                    color=emcolor)
            
            if random.randint(0, 2) == 0:
                cqte = random.randint(2, 6)
                await self.coal_add(guild, team, cqte)
                post_em.add_field(name="BONUS Réussite critique", value=f"**+{cqte} Charbon**")
            
            post_em.set_footer(text="Astuce · " + random.choice(_ASTUCES))
            
            userpts = await self.config.member(user).Points()
            await self.config.member(user).Points.set(userpts + 5)
            
            await spawn.edit(embed=post_em)
            await spawn.remove_reaction(goodemoji, self.bot.user)
            await spawn.delete(delay=20)
    
    
    async def group_item_spawn(self, channel: discord.TextChannel):
        rdm_items = random.sample(list(self.items.keys()), k=random.randint(2, 3))
        items = [self.get_item(i) for i in rdm_items]
        text = random.choice(("Les ateliers organisent une distribution générale ! Piochez dedans :",
                              "Les ateliers ont du rabe, prenez :",
                              "Ces items se trouvaient au fond d'un sac dans l'entrepôt du Père Noël :"))
        text += '\n'
        text += '\n'.join([f"- **{i}**" for i in items])
        emcolor = XMAS_COLOR()
        em = discord.Embed(title="❄️ Jeu des fêtes • Grande distribution", 
                           description=text,
                           color=emcolor)
        em.set_footer(text="» Cliquez sur ❄️ pour obtenir un item (au hasard)")

        spawn = await channel.send(embed=em)
        start_adding_reactions(spawn, ["❄️"])
        
        cache = self.get_cache(channel.guild)
        cache['EventUsers'] = {}
        cache['EventType'] = 'item_spawn'
        cache['EventItems'] = items
        cache['EventMsg'] = spawn.id
        
        userlist = []
        timeout = time.time() + 30
        while time.time() < timeout and len(cache["EventUsers"]) < (len(rdm_items) * 2):
            if list(cache["EventUsers"].keys()) != userlist:
                userlist = list(cache["EventUsers"].keys())
                tabl = []
                for uid, gain in cache["EventUsers"].items():
                    gtxt = gain.name
                    tabl.append((channel.guild.get_member(uid).name, gtxt))
                nem = discord.Embed(title="❄️ Jeu des fêtes • Grande distribution",
                                    description=text,
                                    color=emcolor)
                nem.set_footer(text="» Cliquez sur ❄️ pour obtenir un item (au hasard)")
                nem.add_field(name="Résultats", value=box(tabulate(tabl, headers=["Membre", "Objet"])))
                await spawn.edit(embed=nem)
            await asyncio.sleep(1)
        
        if time.time() >= timeout:
            end_msg = random.choice(["Fin de la distribution d'items, retour au travail !",
                                     "Temps écoulé, à plus tard !",
                                     "Trop tard, l'atelier à d'autres choses à faire !"])
        else:
            end_msg = random.choice(["Il n'y a plus rien à distribuer, terminé !",
                                     "Terminé, les stocks sont vides pour le moment.",
                                     "Plus rien à donner, c'est terminé pour le moment."])
            
        cache['EventType'] = ''
            
        await spawn.remove_reaction("❄️", self.bot.user)
        if cache["EventUsers"]:
            tabl = []
            for uid, gain in cache["EventUsers"].items():
                gtxt = gain.name
                tabl.append((channel.guild.get_member(uid).name, gtxt))
            end_em = discord.Embed(title="❄️ Jeu des fêtes • Grande distribution",
                                description=end_msg,
                                color=emcolor)
            end_em.set_footer(text="Astuce · " + random.choice(_ASTUCES))
            end_em.add_field(name="Résultats", value=box(tabulate(tabl, headers=["Membre", "Objet"])))
        else:
            end_em = discord.Embed(title="❄️ Jeu des fêtes • Grande distribution",
                                   description=end_msg,
                                   color=emcolor)
            end_em.set_footer(text="Astuce · " + random.choice(_ASTUCES))
            end_em.add_field(name="Résultats", value=box("Personne n'a participé à cette distribution", lang='fix'))
        await spawn.edit(embed=end_em)
        await spawn.delete(delay=25)
        
        
    def normalize(self, texte: str):
        """Normalise le texte en retirant accents, majuscules et tirets"""
        texte = texte.lower()
        norm = [l for l in "neeecaaaiiuuoo   "]
        modif = [l for l in "ñéêèçàâäîïûùöô-'."]
        fin_texte = texte
        for char in texte:
            if char in modif:
                ind = modif.index(char)
                fin_texte = fin_texte.replace(char, norm[ind])
        return fin_texte
        
    
    async def question_capital(self, channel: discord.TextChannel): # Trouver la capitale à partir du pays
        guild = channel.guild
        dests = await self.fill_destinations(guild)
        dest = random.choice(dests[3:])
        emcolor = XMAS_COLOR()
        
        giftdata = {'gift_id': random.choice(list(self.gifts.keys())), 'tier': 3, 'destination': dest}
        giftname = self.gifts[giftdata['gift_id']]
        country = random.choice(list(self.countries.keys()))
        
        rdm_capitals = random.sample(list({c: self.countries[c] for c in self.countries if c != country}.values()), k=3)
        good_capital = self.countries[country]
        all_capitals = rdm_capitals + [good_capital]
        random.shuffle(all_capitals)
        
        em = discord.Embed(title=f"❄️ Jeu des fêtes • Soucis de GPS", color=emcolor)
        introtext = random.choice((
            "Un lutin s'est perdu, si vous l'aidez vous obtiendrez un **Cadeau Tier 3**",
            "Le GPS est tombé en panne. Un lutin vous propose un **Cadeau Tier 3** si vous l'aidez à retrouver son chemin.",
            "Un **Cadeau Tier 3** est promis à celui qui trouvera la solution au problème d'une équipe de lutins de l'Atelier."
        ))
        question = random.choice((
            f"Quelle est la capitale de {country} ?",
            f"Trouvez la capitale de {country}."
        ))
        em.description = f"{introtext}"
        
        spawn = await channel.send(embed=em)
        await asyncio.sleep(2)
        
        cache = self.get_cache(guild)
        cache['EventWinner'] = None
        cache['EventAnswer'] = good_capital
        cache['EventType'] = 'question_capital'
        em.add_field(name="Question", value=box(question, lang='css'))
        em.set_footer(text="» Répondez dans le tchat pour tenter d'obtenir un cadeau pour votre équipe")
        await spawn.edit(embed=em)
        
        timeout = time.time() + 25
        counter = 0
        while time.time() < timeout and not cache["EventWinner"]:
            counter += 1
            if counter == 25:
                helptxt = "\n".join([f'• {i}' for i in all_capitals])
                em.add_field(name="Aide", value=box(helptxt, lang='fix'), inline=False)
                await spawn.edit(embed=em)
            await asyncio.sleep(0.2)
            
        if not cache['EventWinner']:
            em.description = "Personne n'a pu répondre à la question ! Tant pis."
            await spawn.edit(embed=em)
            return await spawn.delete(delay=15)
        
        winner = guild.get_member(cache['EventWinner'])
        team = await self.check_team(winner)
        teaminfo = TEAMS_PRP[team]
        await spawn.delete()
        
        await self.team_add_gift(guild, team, **giftdata)
        
        userpts = await self.config.member(winner).Points()
        await self.config.member(winner).Points.set(userpts + 5)
        
        await self.update_quest(winner, 'event_question')
        await self.update_quest(winner, 'event_questionhard')
        
        newem = discord.Embed(title=f"❄️ Jeu des fêtes • Soucis de GPS", color=emcolor)
        newem.description = random.choice((
            f"C'est l'équipe des **{teaminfo['name']}** qui remporte __{giftname} [Tier 3]__ grâce à {winner.mention} !",
            f"L'équipe des **{teaminfo['name']}** remporte __{giftname} [Tier 3]__ grâce à {winner.mention} !",
            f"{winner.mention} fait gagner __{giftname} [Tier 3]__ à son équipe, les **{teaminfo['name']}** !",
            ))
        newem.set_footer(text="Astuce · " + random.choice(_ASTUCES))
        await channel.send(embed=newem, delete_after=30)
        
    async def question_country(self, channel: discord.TextChannel): # Trouver le pays à partir de la capitale
        guild = channel.guild
        dests = await self.fill_destinations(guild)
        dest = random.choice(dests[3:])
        emcolor = XMAS_COLOR()
        
        giftdata = {'gift_id': random.choice(list(self.gifts.keys())), 'tier': 3, 'destination': dest}
        giftname = self.gifts[giftdata['gift_id']]
        capital = random.choice(list(self.countries.values()))
        
        rdm_countries = random.sample(list({c: self.countries[c] for c in self.countries if self.countries[c] != capital}.keys()), k=3)
        good_country = [c for c in self.countries if  self.countries[c] == capital][0]
        all_countries = rdm_countries + [good_country]
        random.shuffle(all_countries)
        
        em = discord.Embed(title=f"❄️ Jeu des fêtes • Soucis de GPS", color=emcolor)
        introtext = random.choice((
            "Un lutin s'est perdu, si vous l'aidez vous obtiendrez un **Cadeau Tier 3**",
            "Le GPS est tombé en panne. Un lutin vous propose un **Cadeau Tier 3** si vous l'aidez à retrouver son chemin.",
            "Un **Cadeau Tier 3** est promis à celui qui trouvera la solution au problème d'une équipe de lutins de l'Atelier."
        ))
        question = random.choice((
            f"Quel pays a pour capitale {capital} ?",
            f"Trouvez le pays dont la capitale est {capital}."
        ))
        em.description = f"{introtext}"
        
        spawn = await channel.send(embed=em)
        await asyncio.sleep(2)
        
        cache = self.get_cache(guild)
        cache['EventWinner'] = None
        cache['EventAnswer'] = good_country
        cache['EventType'] = 'question_country'
        em.add_field(name="Question", value=box(question, lang='css'))
        em.set_footer(text="» Répondez dans le tchat pour tenter d'obtenir un cadeau pour votre équipe")
        await spawn.edit(embed=em)
        
        timeout = time.time() + 25
        counter = 0
        while time.time() < timeout and not cache["EventWinner"]:
            counter += 1
            if counter == 25:
                helptxt = "\n".join([f'• {i}' for i in all_countries])
                em.add_field(name="Aide", value=box(helptxt, lang='fix'), inline=False)
                await spawn.edit(embed=em)
            await asyncio.sleep(0.2)
            
        if not cache['EventWinner']:
            em.description = "Personne n'a pu répondre à la question ! Tant pis."
            await spawn.edit(embed=em)
            return await spawn.delete(delay=15)
        
        winner = guild.get_member(cache['EventWinner'])
        team = await self.check_team(winner)
        teaminfo = TEAMS_PRP[team]
        await spawn.delete()
        
        await self.team_add_gift(guild, team, **giftdata)
        
        userpts = await self.config.member(winner).Points()
        await self.config.member(winner).Points.set(userpts + 5)
        
        await self.update_quest(winner, 'event_question')
        await self.update_quest(winner, 'event_questionhard')
        
        newem = discord.Embed(title=f"❄️ Jeu des fêtes • Soucis de GPS", color=emcolor)
        newem.description = random.choice((
            f"C'est l'équipe des **{teaminfo['name']}** qui remporte __{giftname} [Tier 3]__ grâce à {winner.mention} !",
            f"L'équipe des **{teaminfo['name']}** remporte __{giftname} [Tier 3]__ grâce à {winner.mention} !",
            f"{winner.mention} fait gagner __{giftname} [Tier 3]__ à son équipe, les **{teaminfo['name']}** !",
            ))
        newem.set_footer(text="Astuce · " + random.choice(_ASTUCES))
        await channel.send(embed=newem, delete_after=30)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            if message.author.bot:
                return 
            
            guild = message.guild
            settings = await self.config.guild(guild).Settings()
            cache = self.get_cache(guild)
            
            if cache['EventType'].startswith('question') and cache['EventAnswer']:
                if self.normalize(message.content) == self.normalize(cache['EventAnswer']):
                    if not cache['EventWinner']:
                        cache['EventWinner'] = message.author.id
                
            
            cache['last_message'] = time.time()
            cache['counter'] += random.randint(0, 1)
            if cache['counter'] > cache['trigger']:
                if cache['last_spawn'] < time.time() - 900 and not cache['CurrentEvent']:
                    logger.info("Lancement Event")
                    cache['counter'] = 0
                    cache['CurrentEvent'] = True
                    channel = guild.get_channel(settings['event_channel'])
                    
                    await asyncio.sleep(random.randint(2, 4))
                    events_poss = {
                        'simple_item_spawn': 1.0,
                        'group_item_spawn': 1.0,
                        'simple_gift_spawn': 0.80,
                        'question_capital': 0.50,
                        'question_country': 0.50          
                    }
                    event = random.choices(list(events_poss.keys()), weights=list(events_poss.values()), k=1)[0]
                    if event == 'simple_item_spawn':
                        await self.simple_item_spawn(channel)
                        logger.info("Launch. Simple Item Spawn")
                    elif event == 'group_item_spawn':
                        await self.group_item_spawn(channel)
                        logger.info("Launch. Group Item Spawn")
                    elif event == 'simple_gift_spawn':
                        await self.simple_gift_spawn(channel)
                        logger.info("Launch. Simple Gift Spawn")
                    elif event == 'question_capital':
                        await self.question_capital(channel)
                        logger.info("Launch. Question Capitale")
                    else:
                        await self.question_country(channel)
                        logger.info("Launch. Question Country")
                    
                    cache['CurrentEvent'] = False
                    cache['EventType'] = ''
                    cache['last_spawn'] = time.time()
                    cache['trigger'] = random.randint(30, 50)
                    
                    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        message = reaction.message
        if message.guild:
            cache = self.get_cache(message.guild)
            if not user.bot:
                if message.id == cache["EventMsg"]:
                    if cache["EventType"] == 'item_spawn' and reaction.emoji == "❄️":
                        if user.id not in cache["EventUsers"]:
                            item = random.choice(cache["EventItems"])
                            try:
                                await self.inventory_add(user, item, 1)
                            except:
                                cache["EventUsers"][user.id] = False
                            else:
                                cache["EventUsers"][user.id] = item
                                
                            userquest = await self.config.member(user).Quest()
                            if userquest:
                                qtitle = f'get_{item.id}'
                                if userquest['id'].startswith(qtitle):
                                    await self.update_quest(user, userquest['id'])
                    

    @commands.group(name="xmasset")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_messages=True)
    async def xmas_settings(self, ctx):
        """Commandes de gestion de l'event des fêtes de fin d'année"""
        
    @xmas_settings.command(name="trigger")
    async def set_trigger(self, ctx, value: int):
        """Modifier le nombre de msg (+/- aléatoire) avant l'apparition d'un évènement"""
        guild = ctx.guild
        if value >= 1:
            cache = self.get_cache(guild)
            cache['trigger'] = value
            return await ctx.send(f"Valeur modifiée · Le bot tentera de se rapprocher de {value} msgs pour les évènements (pour cette session seulement)")
        await ctx.send(f"Impossible · La valeur doit être supérieure ou égale à 1 msg")
        
    @xmas_settings.command(name="counter")
    async def set_counter(self, ctx, value: int):
        """Modifier la valeur actuelle du counter de l'apparition d'un évènement"""
        guild = ctx.guild
        if value >= 1:
            cache = self.get_cache(guild)
            cache['counter'] = value
            return await ctx.send(f"Valeur modifiée · Le counter est réglé à {value} msgs")
        await ctx.send(f"Impossible · La valeur doit être supérieure ou égale à 1")
        
    @xmas_settings.command(name="channels")
    async def set_channels(self, ctx, event_channel: discord.TextChannel = None, alert_channel: discord.TextChannel = None):
        """Configure les salons où peuvent apparaître les évènements"""
        guild = ctx.guild
        if event_channel:
            await self.config.guild(guild).Settings.set_raw('event_channel', value=event_channel.id)
            await ctx.send(f"Salon EVENT ajouté · Salon des évènements réglé sur {event_channel.mention}.")
        else:
            await self.config.guild(guild).Settings.clear_raw('event_channel')
            await ctx.send(f"Salon EVENT retiré · Salon des évènements supprimé.")
        if alert_channel:
            await self.config.guild(guild).Settings.set_raw('alert_channel', value=alert_channel.id)
            await ctx.send(f"Salon ALERTE ajouté · Salon des alertes réglé sur {alert_channel.mention}.")
        else:
            await self.config.guild(guild).Settings.clear_raw('alert_channel')
            await ctx.send(f"Salon ALERTE retiré · Salon des alertes supprimé.")
        
    @xmas_settings.command(name="teamset")
    async def set_user_team(self, ctx, user: discord.Member, teamname: str):
        """Modifier la team d'un membre
        
        __Noms normalisés des guildes :__
        `red`= Lutins Rouges
        `green` = Lutins Verts"""
        teamname = teamname.lower()
        if teamname not in list(TEAMS_PRP.keys()):
            return await ctx.send(f"Nom de team invalide · Voyez l'aide de la commande pour voir les noms normalisés des teams.")

        await self.config.member(user).Team.set(teamname)
        await ctx.send(f"Team modifiée · {user.mention} a rejoint la team des ***{TEAMS_PRP[teamname]['name']}***.")
            
            
    @xmas_settings.command(name="roles")
    async def set_event_roles(self, ctx, red_role: discord.Role = None, green_role: discord.Role = None):
        """Modifier les rôles utilisés pour l'event"""
        guild = ctx.guild
        if red_role:
            await self.config.guild(guild).Settings.set_raw('red_role', value=red_role.id)
            await ctx.send(f"Rôle rouge ajouté · Rôle réglé sur {red_role.name}.")
        else:
            await self.config.guild(guild).Settings.clear_raw('red_role')
            await ctx.send(f"Rôle rouge retiré · Rôle supprimé.")
        if green_role:
            await self.config.guild(guild).Settings.set_raw('green_role', value=green_role.id)
            await ctx.send(f"Rôle vert ajouté · Rôle réglé sur {green_role.name}.")
        else:
            await self.config.guild(guild).Settings.clear_raw('green_role')
            await ctx.send(f"Rôle vert retiré · Rôle supprimé.")


    @xmas_settings.command(name="resetdata")
    async def reset_members_team_data(self, ctx):
        """Reset les données des membres et des équipes
        
        Action irréversible"""
        await self.config.clear_all_members(ctx.guild)
        await self.config.guild(ctx.guild).clear_raw('Teams')
        await ctx.send(f"Données reset · Les données des membres et des équipes ont été supprimées avec succès.")
