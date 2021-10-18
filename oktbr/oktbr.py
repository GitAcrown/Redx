import json
import logging
import operator
from os import truncate
from pickle import NONE
import random
import time
import asyncio
from datetime import datetime
from typing import List, Tuple, Union, Optional
from copy import copy
from typing_extensions import ParamSpecKwargs

import discord
from discord.ext.commands import Greedy
from fuzzywuzzy import process
from redbot.core import commands, Config, checks
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, start_adding_reactions
from redbot.core.utils.chat_formatting import box, humanize_timedelta
from tabulate import tabulate
    

logger = logging.getLogger("red.RedX.Oktbr")

HALLOWEEN_COLOR = lambda: random.choice([0x5E32BA, 0xEB6123, 0x18181A, 0x96C457])

_TRANSLATIONS = {
    'magic': "Magie",
    'physical': "Atq. Physique",
    'escape': "Fuite",
    'none': "Aucun",
    'sorcerer': "Sorcier",
    'werewolf': "Loup-Garou",
    'vampire': "Vampire"
}

_GUILDS = {
    'sorcerer': {
        'name': "Sorciers",
        'icon': "https://i.imgur.com/FA43v58.png",
        'color': 0x7f16f0,
        'passive': "Production de sucre accrue",
        'weakvs': 'vampire',
        'atkvalues': {
            'magic': 2.0,
            'physical': 0.5}
        },
    'werewolf': {
        'name': "Loups-Garous",
        'icon': "https://i.imgur.com/tnJDQhJ.png",
        'color': 0x87592b,
        'passive': "Immunisé contre les maladies",
        'weakvs': 'sorcerer',
        'atkvalues': {
            'magic': 0.5,
            'physical': 2}
        },
    'vampire': {
        'name': "Vampires",
        'icon': "https://i.imgur.com/1LJfMqZ.png",
        'color': 0xf0162f,
        'passive': "Perte de sanité réduite en combat et regain dans le temps",
        'weakvs': 'werewolf',
        'atkvalues': {
            'magic': 1.25,
            'physical': 1.25}
        }
}

_FOES = {
    'venumag': {
        'name': "Venu Magicien",
        'icon': "",
        'dialogues': [
            "Je suis __venu__ vous jouer de mauvais tours !",
            "Péter, pisser, chier et venir vous rendre fous."],
        'weakdef': 'physical'
    },
    'vampalcool': {
        'name': "Vampire Alcoolisé",
        'icon': "https://i.imgur.com/1DrDA10.png",
        'dialogues': [
            "Vos bonbons ? Vous voulez dire, NOS bonbons.",
            "N'êtes-vous pas un peu trop âgés pour manger des sucreries ?"
        ],
        'weakdef': 'none'
    },
    'dogghost': {
        'name': "Dogghost",
        'icon': "https://i.imgur.com/o4CSMJ2.png",
        'dialogues': [
            "Bouhouh ! Vous avez eu peur ? J'espère.",
            "Un peu de sucre ? Et si je dis s'il-vous-plaît ?"
        ],
        'weakdef': 'magic'
    },
    'bebezomb': {
        'name': "Bébé Zombie",
        'icon': "",
        'dialogues': [
            "ARGHOUAGH... ARGHZABOING OUARGHOUARGH",
            "OUARGHHHHH LE SUCRE, DONNEZ"
        ],
        'weakdef': 'physical'
    },
    'alphaghoule': {
        'name': "Ghoule Alpha",
        'icon': "",
        'dialogues': [
            "Je sens... oui... du sucre... en quantité (et du sel).",
            "Et après ça... Un petit quiz de Culture G ?"
        ],
        'weakdef': 'magic'
    }
}

_BANNERS = {
    0: ("B0", 0),
    15: ("B1", 25),
    30: ("B2", 50),
    50: ("B3", 75),
    75: ("B4", 100),
    100: ("B5", 200)
}

_ASTUCES = (
    "Faire don d'items à votre guilde vous permet de débloquer des bannières qui offrent des points supplémentaires !",
    "Attention à la surconsommation de sucre lorsque vous en mangez beaucoup... Sauf si vous êtes loup-garou.",
    "Chaque guilde possède un passif qui vous assure un avantage dans la chasse aux bonbons. Vous pouvez le voir avec ;guildes",
    "Avant d'essayer de voler quelqu'un, faîtes attention que votre guilde soit forte contre la sienne !",
    "Le système de guilde fonctionne comme un jeu de Pierre, Feuille, Ciseaux : les vampires sont forts contre les sorciers, qui le sont contre les loups-garous, qui le sont contre les vampires.",
    "Vous ne pouvez pas voler un membre de votre propre guilde. Ce n'est pas poli.",
    "Il est important de soutenir sa guilde mais n'oubliez pas de jouer aussi pour vous !",
    "Plus vous utilisez de sucre pour le recyclage, plus vous avez de chance d'obtenir des bonbons.",
    "Mettre trop peu de sucre lors du recyclage vous expose à un plus grand risque d'échec.",
    "Si vous avez posté sur le serveur juste avant l'apparition d'un hostile et que vous voulez pas perdre de sanité en cas d'échec, n'oubliez pas de fuir !",
    "La fuite est le seul moyen de s'assurer de ne pas perdre de sanité, mais en cas de victoire vous ne remportez rien.",
    "Les hostiles sont parfois sensibles contre un type d'attaque et si vous êtes en plus dans une guilde avec un bonus d'attaque dans ce type alors battez-vous !",
    "Si votre sanité tombe en dessous de 25%, vous perdrez du sucre au fil du temps.",
    "Assurez-vous de garder votre sanité au delà de 25% pour éviter de perdre du sucre...",
    "Chaque niveau de bannière pour un item rapporte 25 points de guilde supplémentaires (B1 = 25, B2 = 50 etc.)",
    "Gardez bien en tête dans quel type d'attaque que votre guilde excelle, afin de bien choisir le type d'attaque quand un hostile apparaît !",
    "Vous pouvez récupérer du sucre en écrasant (;crush) vos bonbons. Vous pouvez ensuite le recycler avec ;recycle suivi de la qté de sucre à utiliser.",
    "Vous pouvez faire ';help' devant n'importe quelle commande pour obtenir de l'aide !",
    "Vous pouvez consulter un top complet de votre guilde avec ';guildtop' !")


class OktbrError(Exception):
    """Classe de base pour les erreurs spécifiques à Oktbr"""
    
class PocketSlotsError(OktbrError):
    """La capacité des poches ne permet pas de faire l'opération"""
    


class Item:
    def __init__(self, cog, item_id: str):
        self._cog = cog
        self._raw = cog.items[item_id]

        self.id = item_id
        self.tier = self._raw.get('tier', 1)
        self.default_config = self._raw.get('default_config', {})
        
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


class Oktbr(commands.Cog):
    """Evènement d'Halloween 2021 (Appart)"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {
            'Pocket': {},
            'Guild': None,
            'Sugar': 0,
            'Sanity': 100,
            'Points': 0,
            'Status': {},
            
            'Steal': {
                'LastTry': 0,
                'LastTarget': 0
            }
        }
        
        default_guild = {
            'Guilds': {
                'sorcerer': {},
                'werewolf':  {},
                'vampire':  {}},
            'Events': {
                'channels': [],
                'counter_threshold': 50
            }
        }
        
        default_global = {
            'PocketSlots': 50
        }
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        self.cache = {}
        

# DONNEES -----------------------------------------

    # Se charge avec __init__.py au chargement du module
    def _load_bundled_data(self):
        items_path = bundled_data_path(self) / 'items.json'
        with items_path.open() as json_data:
            self.items = json.load(json_data)
        logger.info("Chargement des items Oktbr")
        

# CACHE ----------------------------------------

    def get_cache(self, guild: discord.Guild):
        if guild.id not in self.cache:
            self.cache[guild.id] = {
                'UserActivity': {},
                'SanityLossCD': {},
                'SickUser': {},
                'SanityVamp': {},
                
                'EventMsg': None,
                'EventType': '',
                'EventUsers': {},
                'EventItems': [],
                'EventFoe': {},
                
                'EventCounter': 0,
                'EventCounterThreshold': 25,
                'EventCD': time.time() - 600,
                'EventCurrent': False
            }
        
        return self.cache[guild.id]
        
        
# ITEMS ---------------------------------------

    def get_item(self, item_id: str):
        if item_id not in self.items:
            raise KeyError(f"L'item {item_id} n'existe pas")
        return Item(self, item_id)
    
    def fetch_item(self, text: str, custom_list: List[str] = None, *, fuzzy_cutoff: int = 80):
        items = self.items if not custom_list else {i: self.items[i] for i in custom_list if i in self.items}
        text = text.lower()
        
        if text in items:
            return self.get_item(text)
        
        by_name = [i for i in items if text == items[i]['name'].lower()]
        if by_name:
            return self.get_item(by_name[0])
        
        fuzzy_name = process.extractOne(text, [items[n]['name'].lower() for n in items], score_cutoff=fuzzy_cutoff)
        if fuzzy_name:
            return self.get_item([n for n in items if items[n]['name'].lower() == fuzzy_name[0]][0])

        fuzzy_id = process.extractOne(text, list(items.keys()), score_cutoff=fuzzy_cutoff)
        if fuzzy_id:
            return self.get_item(fuzzy_id[0])

        return None
    
    def parse_item_amount(self, text: str, default_amount: int = 1) -> Tuple[Item, int]:
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


# POCHES -------------------------------------

    async def pocket_check(self, user: discord.Member, item: Item, qte: int) -> bool:
        pck = await self.config.member(user).Pocket()
        if qte > 0:
            maxcap = await self.config.PocketSlots()
            pcksum = sum([pck[i] for i in pck])
            return pcksum + qte <= maxcap
        elif qte < 0:
            return pck.get(item.id, 0) >= qte
        return True

    async def pocket_set(self, user: discord.Member, item: Item, qte: int) -> int:
        if qte < 0:
            raise ValueError("La quantité d'un item ne peut être négative")
        
        await self.check_user_guild(user)
        
        if qte != 0:
            await self.config.member(user).Pocket.set_raw(item.id, value=qte)
        else:
            try:
                await self.config.member(user).Pocket.clear_raw(item.id)
            except KeyError:
                pass
        return qte
        
    async def pocket_add(self, user: discord.Member, item: Item, qte: int) -> int:
        if qte < 0:
            raise ValueError("Impossible d'ajouter une quantité négative d'items")
        
        if not await self.pocket_check(user, item, +qte):
            raise PocketSlotsError("Il n'y a pas assez de slots dans les poches pour faire cette opération")
        
        curpts = await self.config.member(user).Points()
        await self.config.member(user).Points.set(curpts + qte)
        
        pck = await self.config.member(user).Pocket()
        return await self.pocket_set(user, item, qte + pck.get(item.id, 0))
    
    async def pocket_remove(self, user: discord.Member, item: Item, qte: int) -> int:
        qte = abs(qte)
        
        if not await self.pocket_check(user, item, -qte):
            raise PocketSlotsError("Le membre ne possède pas cette quantité d'items")
        
        pck = await self.config.member(user).Pocket()
        return await self.pocket_set(user, item, pck.get(item.id, 0) - qte)
    
    async def pocket_get(self, user: discord.Member, item: Item = None) -> Union[dict, int]:
        pck = await self.config.member(user).Pocket()
        if item:
            return pck.get(item.id, 0)
        return pck
        
    async def pocket_items(self, user: discord.Member) -> Tuple[Item, int]:
        pck = await self.config.member(user).Pocket()
        return [(self.get_item(p), pck[p]) for p in pck if p in self.items]
    
# STATUS --------------------------------------

    async def add_status(self, user: discord.Member, status_name: str, duration: int):
        ustatus = await self.config.member(user).Status()
        if status_name in ustatus:
            new = ustatus[status_name] + duration
            await self.config.member(user).Status.set_raw(status_name, value=new)
        else:
            await self.config.member(user).Status.set_raw(status_name, value=time.time() + duration)
    
    async def delete_status(self, user: discord.Member, status_name: str):
        ustatus = await self.config.member(user).Status()
        if status_name not in ustatus:
            return ValueError(f"Le statut {status_name} n'est pas appliqué à {user}")
        await self.config.member(user).Status.clear_raw(status_name)
    
    async def get_status(self, user: discord.Member, status_name: str):
        ustatus = await self.config.member(user).Status()
        if status_name not in ustatus:
            return ValueError(f"Le statut {status_name} n'est pas appliqué à {user}")
        return ustatus[status_name]
    
    
# GUILDES ---------------------------------------

    async def check_user_guild(self, user: discord.Guild):
        guilde = await self.config.member(user).Guild()
        if not guilde:
            lowest_nb = 0
            lowest_name = ''
            for gn in _GUILDS:
                guildnum = len(await self.get_guild_members(user.guild, gn))
                if lowest_nb == 0 or lowest_nb > guildnum:
                    lowest_nb = guildnum
                    lowest_name = gn
            
            await self.config.member(user).Guild.set(lowest_name)
            return lowest_name
        return guilde

    async def get_guild_members(self, guild: discord.Guild, guildname: str):
        members = await self.config.all_members(guild)
        return [guild.get_member(i) for i in members if members[i]['Guild'] == guildname]

    async def get_guild_points(self, guild: discord.Guild, guildname: str):
        members = await self.config.all_members(guild)
        guildmembers = [i for i in members if members[i]['Guild'] == guildname]
        return sum([members[gm]['Points'] for gm in guildmembers])
    
    async def get_banners(self, guild: discord.Guild, guildname: str):
        guildinv = await self.config.guild(guild).Guilds.get_raw(guildname)
        banners = {}
        for i in guildinv:
            lvl = 0
            for b in _BANNERS:
                if guildinv[i] >= b:
                    lvl = b
            banners[i] = lvl
        return banners
    
    async def get_banners_points(self, guild: discord.Guild, guildname: str):
        banners = await self.get_banners(guild, guildname)
        total = 0
        for itemban in banners:
            total += _BANNERS[banners[itemban]][1]
        return total
    
# FOES ---------------------------------------------

    def get_foe(self):
        foeid = random.choice(list(_FOES.keys()))
        return _FOES[foeid]
        
    
# COMMANDES +++++++++++++++++++++++++++++++++++++++++

    @commands.command(name='pocket', aliases=['pck', 'poches'])
    async def show_pocket(self, ctx, user: discord.Member = None):
        """Afficher son inventaire d'Halloween ou celui d'un autre membre
        
        Affiche aussi diverses informations utiles sur le membre"""
        user = user if user else ctx.author
        
        await self.check_user_guild(user)
        
        data = await self.config.member(user).all()
        userguild = data['Guild']
        teaminfo = _GUILDS[userguild]
        
        em = discord.Embed(color=teaminfo['color'])
        em.set_author(name=f"{user.name}", icon_url=user.avatar_url)
        
        desc = f"**Sucre** · {data['Sugar']}\n"
        desc += f"**Sanité** · {data['Sanity']}%\n"
        desc += f"**Points rapportés** · {data['Points']}"
        em.description = desc
        
        ustatus = await self.config.member(user).Status()
        statxt = ' '.join([f'`{e.title()}`' for e in ustatus if ustatus[e] >= time.time()])
        if statxt:
            em.add_field(name="Effets actifs", value=statxt)
        
        items = await self.pocket_items(user)
        maxcap = await self.config.PocketSlots()
        items_table = [(f"{item.name}{'ᵘ' if item.on_use else ''}", qte) for item, qte in items]
        if items_table:
            pcksum = sum([qte for _, qte in items])
            em.add_field(name=f"Poches ({pcksum}/{maxcap})", value=box(tabulate(items_table, headers=('Item', 'Qte')), lang='fix'))
        else:
            em.add_field(name=f"Poches (0/{maxcap})", value=box("Inventaire vide", lang='fix'))
        
        em.set_footer(text=f"Guilde des {teaminfo['name']}", icon_url=teaminfo['icon'])
        await ctx.reply(embed=em, mention_author=False)
        
    @commands.command(name='guilds', aliases=['guildes'])
    async def show_guild(self, ctx):
        """Affiche des informations sur les guildes d'Halloween"""
        guild = ctx.guild
        
        await self.check_user_guild(ctx.author)

        embeds = []
        data = await self.config.guild(guild).Guilds()
        for g in data:
            teaminfo = _GUILDS[g]
            contrib = await self.get_guild_members(guild, g)
            em = discord.Embed(title=f"**Guilde des *{teaminfo['name']}***", color=teaminfo['color'])
            em.set_thumbnail(url=teaminfo['icon'])
            
            guildpts = await self.get_guild_points(guild, g) + await self.get_banners_points(guild, g)
            
            desc = f"**Points de Guilde** · {guildpts}\n"
            desc += f"**Nb. de membres** · {len(contrib)}"
            em.description = desc
            
            em.add_field(name="Avantage de guilde", value=f"*{teaminfo['passive']}*")
            em.add_field(name="Vulnérables contre", value=f"**{_GUILDS[teaminfo['weakvs']]['name']}**")
            
            bonusatk = f"🗡️ **Atq. Physique** · x{teaminfo['atkvalues']['physical']}\n"
            bonusatk += f"🔮 **Magie** · x{teaminfo['atkvalues']['magic']}"
            em.add_field(name="Bonus/Malus d'Attaque", value=bonusatk)
            
            gmpts = []
            for gm in contrib:
                gmpts.append((gm.name, await self.config.member(gm).Points()))
            best = sorted(gmpts, key=operator.itemgetter(1), reverse=True)
            besttabl = tabulate(best[:5], headers=('Membre', 'Points'))
            if best:
                em.add_field(name="Top 5 contributeurs", value=box(besttabl + "\n-----------------\n› Voir ';guildtop'"), inline=False)
            else:
                em.add_field(name="Top 5 contributeurs", value=box("Aucun contributeur pour le moment"))
            
            banners = await self.get_banners(guild, g)
            guildinv = await self.config.guild(guild).Guilds.get_raw(g)
            if banners:
                banntabl = [(self.get_item(bi), f"{_BANNERS[banners[bi]][0]}", f"{guildinv[bi]}") for bi in banners]
                btabl = tabulate(banntabl, headers=('Item', 'Niveau', 'Qte'))
                em.add_field(name="Bannières d'items", value=box(btabl), inline=False)
            else:
                em.add_field(name="Bannières d'items", value=box("Aucune bannière d'item débloquée"))
                
            embeds.append(em)
            
        await menu(ctx, embeds, DEFAULT_CONTROLS)
        
    @commands.command(name='guildtop', aliases=['guildetop'])
    async def show_guild_top(self, ctx, top: Optional[int] = 20, guilde: str = None):
        """Affiche un top des contributeurs de votre guilde
        
        Changez le paramètre [top] pour obtenir un top plus ou moins complet
        Vous pouvez rentrer un nom de guilde pour consulter une autre guilde que la votre"""
        guild = ctx.guild
        
        if guilde:
            guilde = guilde.lower()
            if guilde not in list(_GUILDS.keys()):
                isname = [g for g in _GUILDS if _GUILDS[g]['name'].lower() == guilde]
                if isname:
                    guilde = isname[0]
                else:
                    return await ctx.reply(f"**Nom invalide** · Ce nom ne correspond à aucune guilde existante.",mention_author=False)
        else:
            guilde = await self.check_user_guild(ctx.author)
            
        guildinfo = _GUILDS[guilde]
        members = await self.get_guild_members(guild, guilde)
        members_data = await self.config.all_members(guild)
        mscore = [(m.name, members_data[m.id]['Points']) for m in members]
        msort = sorted(mscore, key=operator.itemgetter(1), reverse=True)
        
        em = discord.Embed(color=guildinfo['color'])
        em.set_author(name=f"Guilde des {guildinfo['name']}", icon_url=guildinfo['icon'])
        em.description = box(tabulate(msort[:top], headers=['Membre', 'Points']))
        pts = await self.get_guild_points(guild, guilde) + await self.get_banners_points(guild, guilde)
        em.set_footer(text=f"Points de guilde : {pts}")
        
        try:
            await ctx.reply(embed=em, mention_author=False)
        except:
            await ctx.reply(f"**Top trop grand** · Impossible d'afficher une liste aussi longue. Réduisez le nombre au paramètre [top].",
                                   mention_author=False)
        
        
    @commands.command(name='donation', aliases=['dono'])
    @commands.cooldown(1, 60, commands.BucketType.member)
    async def guild_donation(self, ctx, *, item_qte):
        """Faire don d'items à la guilde pour contribuer à l'obtention de bannières
        
        Les bannières d'items permettent d'obtenir des points supplémentaires pour la guilde"""
        author = ctx.author
        await self.check_user_guild(author)
        item, qte = self.parse_item_amount(item_qte)
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        if not item:
            return await ctx.reply(f"{cross} **Item inconnu** · Vérifiez le nom de l'item ou fournissez directement son ID.",
                                   mention_author=False)
            
        if not await self.pocket_check(author, item, -qte):
            return await ctx.reply(f"{cross} **Nombre d'items insuffisant** · Vous n'avez pas {item.famount(qte)} dans votre inventaire.",
                                   mention_author=False)
        
        try:
            await self.pocket_remove(author, item, qte)
        except:
            return await ctx.reply(f"{cross} **Don impossible** · Le don n'a pas pu être fait en raison d'une erreur inconnue.",
                                   mention_author=False)
        
        authorguild = await self.config.member(author).Guild()
        guildinv = await self.config.guild(ctx.guild).Guilds.get_raw(authorguild)
        await self.config.guild(ctx.guild).Guilds.set_raw(authorguild, item.id, value=guildinv.get(item.id, 0) + qte)
        await ctx.reply(f"{check} **Don réalisé avec succès** · Vous avez fait don de **{item.famount(qte)}** à votre guilde, les ***{_GUILDS[authorguild]['name']}***.",
                                   mention_author=False)
        
    @commands.command(name='use')
    async def use_item(self, ctx, *, itemname: str):
        """Consommer un item
        
        Les items qui sont consommables sont annotés d'un ᵘ dans votre inventaire"""
        author = ctx.author
        await self.check_user_guild(author)
        item = self.fetch_item(itemname)
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        cache = self.get_cache(ctx.guild)
        
        if cache['SickUser'].get(author.id, 0) + 3600 > time.time():
            new = (cache['SickUser'][author.id] + 3600) - time.time()
            return await ctx.reply(f"{cross} **Maladie** · Vous êtes malade. Vous ne pourrez pas reconsommer d'item avant *{humanize_timedelta(seconds=new)}*.",
                                   mention_author=False)
        
        if not item:
            return await ctx.reply(f"{cross} **Item inconnu** · Vérifiez le nom de l'item ou fournissez directement son ID.",
                                   mention_author=False)
            
        if not await self.pocket_check(author, item, -1):
            return await ctx.reply(f"{cross} **Item non possédé** · Cet item ne se trouve pas dans votre inventaire.",
                                   mention_author=False)
        
        if not item.on_use:
            return await ctx.reply(f"{cross} **Item non-consommable** · Cet item n'a aucun effet à son utilisation.\nSeuls les items annotés d'un 'ᵘ' dans votre inventaire sont utilisables.",
                                   mention_author=False)
            
        em = discord.Embed(color=author.color)
        em.set_author(name=f"{author.name}", icon_url=author.avatar_url)
        em.set_footer(text=f"Consommer un item")
        em.description = f"Êtes-vous certain de vouloir consommer **{item}** ?"
        
        details = '\n'.join(item.info) if item.info else ''
        if details:
            em.add_field(name="Effets attendus", value=details)
                
        if item.icon:
            em.set_thumbnail(url=item.icon)
        
        msg = await ctx.reply(embed=em, mention_author=False)
        start_adding_reactions(msg, [check, cross])
        try:
            react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id, timeout=30)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"{cross} **Annulé** · L'item n'a pas été utilisé.", mention_author=False)
        if react.emoji == cross:
            await msg.delete(delay=5)
            return await ctx.reply(f"{cross} **Annulé** · L'item n'a pas été utilisé.", mention_author=False)
        
        try:
            await self.pocket_remove(author, item, 1)
        except:
            return await ctx.reply(f"**Erreur** · Impossible de retirer l'item de votre inventaire.", mention_author=False)
            
        sick = random.randint(0, 4) == 0
        if await self.config.member(author).Guild() == 'werewolf':
            sick = False
            
        applied = []
        for name, value in item.on_use.items():
            if name == 'random_sanity':
                name = random.choice(('restore_sanity', 'withdraw_sanity'))
            
            if name == 'restore_sanity':
                current = await self.config.member(author).Sanity()
                new = min(100, current + value)
                await self.config.member(author).Sanity.set(new)
                applied.append(f"***Sanité restaurée*** · **+{value}** (={new})")
                
            elif name == 'withdraw_sanity':
                current = await self.config.member(author).Sanity()
                new = max(0, current - value)
                await self.config.member(author).Sanity.set(new)
                applied.append(f"***Sanité réduite*** · **-{value}** (={new})")
                
        em = discord.Embed(color=author.color)
        em.set_author(name=f"{author.name}", icon_url=author.avatar_url)
        em.set_footer(text=f"Consommer un item")
        em.description = f"{check} Vous avez consommé **{item}**"
        em.add_field(name="Effets", value='\n'.join(applied))
        
        if sick:
            sanitymal = random.randint(3, 10)
            current = await self.config.member(author).Sanity()
            new = max(0, current - sanitymal)
            await self.config.member(author).Sanity.set(new)
            em.add_field(name="Malus", value=f"Vous êtes tombé malade ! Vous ne pouvez plus consommer d'items pendant **une heure** et vous perdez **-{sanitymal} Sanité**.")
            cache['SickUser'][author.id] = time.time()
            
        await msg.clear_reactions()
        await msg.edit(embed=em)
        
        
    @commands.command(name='crush')
    async def crush_items(self, ctx, *, item_qte):
        """Ecraser des items pour en extraire du sucre qui pourra être recyclé
        
        Vous pouvez ensuite utiliser la commande `;recycle` pour transformer votre sucre en d'autres items"""  
        author = ctx.author 
        await self.check_user_guild(author)
        item, qte = self.parse_item_amount(item_qte)
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        if not item:
            return await ctx.reply(f"{cross} **Item inconnu** · Vérifiez le nom de l'item ou fournissez directement son ID.",
                                   mention_author=False)
            
        if not await self.pocket_check(author, item, -qte):
            return await ctx.reply(f"{cross} **Nombre d'items insuffisant** · Vous n'avez pas {item.famount(qte)} dans votre inventaire.",
                                   mention_author=False)
        
        if not item.sugar:
            return await ctx.reply(f"{cross} **Item non-recyclable** · Cet item ne peut être écrasé pour en obtenir du sucre.",
                                   mention_author=False)
        
        try:
            await self.pocket_remove(author, item, qte)
        except:
            return await ctx.reply(f"{cross} **Opération échouée** · Impossible de vous retirer l'item visé.",
                                   mention_author=False)
        else:
            authorguild = await self.config.member(author).Guild()
            if authorguild == 'sorcerer':
                sugar = random.randint(item.sugar, item.sugar + 3) * qte
                await ctx.reply(f"{check} **Opération réussie** · Vous avez obtenu **{sugar}x Sucre** en recyclant ***{item.famount(qte)}*** [Bonus de Guilde].",
                                   mention_author=False)
            else:
                sugar = random.randint(item.sugar - 2, item.sugar + 2) * qte
                await ctx.reply(f"{check} **Opération réussie** · Vous avez obtenu **{sugar}x Sucre** en recyclant ***{item.famount(qte)}***.",
                                   mention_author=False)
            current = await self.config.member(author).Sugar()
            await self.config.member(author).Sugar.set(current + sugar)
    
    @commands.command(name='recycle')
    async def recycle_sugar(self, ctx, qte: int = None):
        """Recycler votre sucre pour obtenir de nouveaux items
        
        La quantité de sucre utilisée détermine votre chance d'obtenir des items et lesquels
        Si vous ne précisez pas de qté de sucre, vous donnera le sucre actuellement possédé"""
        author = ctx.author
        authorguild = await self.check_user_guild(author)
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        if not qte:
            usugar = await self.config.member(author).Sugar()
            em = discord.Embed(description=f"Vous avez **{usugar}x Sucre**", color=author.color)
            em.set_footer(text="La quantité de sucre utilisée détermine votre chance d'obtenir un item et son type")
            return await ctx.reply(embed=em, mention_author=False)
        
        cache = self.get_cache(ctx.guild)
        if cache['SickUser'].get(author.id, 0) + 3600 > time.time():
            new = (cache['SickUser'][author.id] + 3600) - time.time()
            return await ctx.reply(f"{cross} **Maladie** · Vous êtes malade. Vous ne pouvez pas réaliser cette action avant *{humanize_timedelta(seconds=new)}*.",
                                   mention_author=False)
        
        current = await self.config.member(author).Sugar()
        if qte > current:
            return await ctx.reply(f"{cross} **Quantité de sucre insuffisante** · Vous n'avez pas *{qte}x Sucre*.",
                                   mention_author=False)
        
        if qte < 10:
            return await ctx.reply(f"{cross} **Impossible** · La qté minimale de sucre qui doit être utilisée est de 10x.", mention_author=False)
        
        
        notif = None
        if qte > 100:
            qte = 100
            notif = await ctx.reply(f"**Info** · J'ai réajusté votre quantité de sucre rentrée car il est inutile d'en mettre plus que 100.", mention_author=False)
        
        async with ctx.typing():
            if 10 <= qte <= 30:
                success = random.randint(0, 3) == 0
            elif 30 < qte <= 50:
                success = random.randint(0, 2) == 0
            elif 50 < qte <= 75:
                success = random.randint(0, 2) < 2
            elif 75 < qte < 100:
                success = random.randint(0, 3) < 3
            else:
                success = True
            wait = 2.5 if success else 1.5
            await asyncio.sleep(wait)
        
        if notif: 
            await notif.delete(delay=4)
        await self.config.member(author).Sugar.set(max(0, current - qte))
        
        if not success:
            return await ctx.reply(f"{cross} **Echec** · Vous perdez **{qte}x Sucre** sans obtenir de bonbons.",
                                   mention_author=False)
            
        if random.randint(0, 4) == 0 and authorguild != 'werewolf':
            sanitymal = random.randint(10, 20)
            current = await self.config.member(author).Sanity()
            new = max(0, current - sanitymal)
            await self.config.member(author).Sanity.set(new)
            cache['SickUser'][author.id] = time.time()
            return await ctx.reply(f"{cross} **Vous êtes tombé malade** · Vous ne pouvez plus recycler d'items pendant **une heure** et vous perdez **-{sanitymal} Sanité**.\nVotre sucre a été perdu.",
                                   mention_author=False)
            
        itemsw = {i: 1 - (self.items[i]['sugar'] / 100) for i in self.items if 'sugar' in self.items[i]}
        itemid = random.choices(list(itemsw.keys()), list(itemsw.values()), k=1)[0]
        item = self.get_item(itemid)
        itemqte = random.randint(max(1, round(qte/20)), max(5, round(qte/15)))
        
        try:
            await self.pocket_add(ctx.author, item, itemqte)
        except:
            return await ctx.reply(f"{cross} **Inventaire plein** · Vous avez réussi à créer des bonbons mais... votre inventaire est plein. C'est bête. Vous perdez **{qte}x Sucre** pour rien.",
                                   mention_author=False)
        else:
            await ctx.reply(f"{check} **Sucre recyclé avec succès** · Vous obtenez **{item.famount(itemqte)}** en utilisant {qte} de sucre.",
                            mention_author=False)
    
    
    @commands.command(name='steal')
    @commands.cooldown(1, 10, commands.BucketType.member)
    async def steal_user(self, ctx, user: discord.Member = None):
        """Tenter de voler un autre membre
        
        Vous ne pouvez voler qu'un membre qui n'est pas de votre guilde
        Vos chances de réussite dépendent de vos guildes respectives, votre sanité ainsi que la présence récente du membre visé ou non
        Cette action est limitée dans le temps
        
        Faire la commande sans mention vous donne une liste de cibles potentielles"""
        author = ctx.author
        authorguild = await self.check_user_guild(author)
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        
        if not user:
            all_members = await self.config.all_members(ctx.guild)
            targlist = []
            for m in all_members:
                if all_members[m]['Guild'] != authorguild:
                    if all_members[m]['Sugar'] or all_members[m]['Pocket']:
                        if all_members[m]['Steal'].get('LastTarget', "") != datetime.now().strftime('%d.%m.%Y'):
                            targlist.append((ctx.guild.get_member(m).name, _GUILDS[all_members[m]['Guild']]['name']))
            if targlist:
                em = discord.Embed(title="Potentielles cibles de vol", description=box(tabulate(targlist[:10], headers=["Membre", "Guilde"])),
                                   color=HALLOWEEN_COLOR())
                em.set_footer(text="Vous pouvez tenter de voler quelqu'un avec ';steal <pseudo>'")
                return await ctx.reply(embed=em, mention_author=False)
            else:
                em = discord.Embed(title="Potentielles cibles de vol", description=box("Aucune cible n'a été trouvée"),
                                   color=HALLOWEEN_COLOR())
                em.set_footer(text="ASTUCE · " + random.choice(_ASTUCES))
                return await ctx.reply(embed=em, mention_author=False)
        
        if not user:
            return await ctx.reply(f"{cross} **Choisissez un membre** · Vous devez mentionner un membre à voler avec la commande.", mention_author=False)
    
        await self.check_user_guild(user)
        authordata, userdata = await self.config.member(author).all(), await self.config.member(user).all()
        
        if authordata['Steal']['LastTry'] >= time.time() - 21600:
            newtry = (authordata['Steal']['LastTry'] + 21600) - time.time()
            return await ctx.reply(f"{cross} **Vol impossible** · Vous avez déjà tenté de voler quelqu'un il y a moins de 6h. Réessayez dans *{humanize_timedelta(seconds=newtry)}*.", mention_author=False)
        
        if userdata['Steal'].get('LastTarget', '') == datetime.now().strftime('%d.%m.%Y'):
            return await ctx.reply(f"{cross} **Vol impossible** · Ce membre a déjà été visé par un vol aujourd'hui. Réessayez demain.", mention_author=False)
        
        if authordata['Guild'] == userdata['Guild']:
            return await ctx.reply(f"{cross} **Même guilde** · Vous venez tous les deux de la même guilde. On ne vole pas les gens de sa propre équipe.", mention_author=False)
        
        await self.config.member(user).Steal.set_raw('LastTarget', value=datetime.now().strftime('%d.%m.%Y'))
        await self.config.member(author).Steal.set_raw('LastTry', value=time.time())
        
        async with ctx.typing():
            luck = 0.20
            if authordata['Sanity'] > userdata['Sanity']:
                luck += 0.10
            else:
                luck -= 0.05
                
            userguild = _GUILDS[userdata['Guild']]
            if userguild['weakvs'] == authordata['Guild']:
                luck *= 2
            
            cache = self.get_cache(ctx.guild)
            if cache['UserActivity'].get(user.id, 0) < time.time() - 300:
                luck /= 2
                
            await asyncio.sleep(random.randint(2, 4))
            
        if random.uniform(0, 1) > luck:
            if random.randint(0, 1) == 0 and authordata['Sugar']:
                sugar = random.randint(round(authordata['Sugar'] / 4), round(authordata['Sugar'] / 2))
                await self.config.member(author).Sugar.set(authordata['Sugar'] - sugar)
                await self.config.member(user).Sugar.set(userdata['Sugar'] + sugar)
                return await ctx.reply(f"{cross}🍬 **Echec critique du vol** · {user.mention} vous a attrapé la main dans le sac. Vous perdez **x{sugar} Sucre**, qui sont transférés à la victime.", mention_author=False)
            else:
                return await ctx.reply(f"{cross}🍬 **Echec du vol** · Vous n'avez pas réussi à voler ***{user.name}***, mais heureusement pour vous il/elle ne vous a pas attrapé.", mention_author=False)
        
        if userdata['Pocket']:
            itemid = random.choice(list(userdata['Pocket'].keys()))
            item = self.get_item(itemid)
            qte = random.randint(1, max(1, userdata['Pocket'][itemid] / 3))
            
            try:
                await self.pocket_remove(user, item, qte)
            except:
                return await ctx.reply(f"{cross}🍬 **Echec du vol** · Vous n'avez pas réussi à voler **{user.name}**, mais heureusement pour vous il/elle ne vous a pas attrapé.", mention_author=False)
            else:
                await self.pocket_add(author, item, qte)
            
            em = discord.Embed(color=HALLOWEEN_COLOR())
            em.set_author(name=author.name, icon_url=author.avatar_url)
            em.description = f"{check} Vous avez volé {user.mention} avec succès et obtenu {item.famount(qte)} !"
            await ctx.reply(embed=em, mention_author=False)
            
        elif userdata['Sugar']:
            sugar = random.randint(round(userdata['Sugar'] / 5), round(userdata['Sugar'] / 3))
            await self.config.member(user).Sugar.set(userdata['Sugar'] - sugar)
            await self.config.member(author).Sugar.set(authordata['Sugar'] + sugar)
            em = discord.Embed(color=HALLOWEEN_COLOR())
            em.set_author(name=author.name, icon_url=author.avatar_url)
            em.description = f"{check} Vous avez volé {user.mention} avec succès et obtenu **x{sugar} Sucre** !"
            await ctx.reply(embed=em, mention_author=False)
        
        else:
            return await ctx.reply(f"{cross}🍬 **Echec du vol** · Vous n'avez pas réussi à voler **{user.name}**, mais heureusement pour vous il/elle ne vous a pas attrapé.", mention_author=False)
    
# EVENTS >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>    
        
    async def simple_item_spawn(self, channel: discord.TextChannel):
        rdm_item = random.choice(list(self.items.keys()))
        item = self.get_item(rdm_item)
        qte = random.randint(1, 3)
        emcolor = HALLOWEEN_COLOR()
        text = random.choice((f"Je donne **{item.famount(qte)}** au plus rapide ! Dépêchez-vous !",
                              f"Voici **{item.famount(qte)}** ! Premier arrivé, premier servi.",
                              f"*Lance **{item.famount(qte)}** sur le salon*",
                              f"Nouvelle livraison de **{item.famount(qte)}** ! Cliquez vite."))
        em = discord.Embed(title="🍬 Jeu d'Halloween • Trouvaille", 
                           description=text,
                           color=emcolor)
        if item.icon:
            em.set_thumbnail(url=item.icon)
        
        emojis = ['🍬','🍭','🍫','🍪']
        random.shuffle(emojis)
        emojis = emojis[:3]
        goodemoji = random.choice(emojis)
            
        em.set_footer(text=f"Cliquez en premier sur {goodemoji}")
        
        spawn = await channel.send(embed=em)
        start_adding_reactions(spawn, emojis)
        try:
            _, user = await self.bot.wait_for("reaction_add",
                                              check=lambda r, u: r.message.id == spawn.id and r.emoji == goodemoji and not u.bot,
                                              timeout=20)
        except asyncio.TimeoutError:
            await spawn.delete()
            return
        else:
            await self.check_user_guild(user)
            try:
                await self.pocket_add(user, item, qte)
            except:
                sugar = int(item.sugar / 1.5) * qte
                current = await self.config.member(user).Sugar()
                await self.config.member(user).Sugar.set(current + sugar)
                wintxt = random.choice((f"{user.mention} gagne **{item.famount(qte)}**, transformé en **{sugar}x Sucre** par manque de place dans l'inventaire",
                                        f"{user.mention} remporte **{item.famount(qte)}**, recyclé en **{sugar}x Sucre** par manque de place dans l'inventaire",
                                        f"{user.mention} empoche **{item.famount(qte)}** mais l'inventaire étant plein, ils ont été recyclés en **{sugar}x Sucre**"))
            else:
                wintxt = random.choice((f"{user.mention} empoche **{item.famount(qte)}** avec succès !",
                                        f"C'est {user.mention} qui partira donc avec **{item.famount(qte)}** !",
                                        f"{user.mention} a été le/la plus rapide, repartant avec **{item.famount(qte)}**.",
                                        f"Bien joué {user.mention} ! Tu pars avec **{item.famount(qte)}**.",
                                        f"Bravo à {user.mention} qui repart avec **{item.famount(qte)}**."
                                        ))
            post_em = discord.Embed(title="🍬 Jeu d'Halloween • Trouvaille", 
                                    description=wintxt,
                                    color=emcolor)
            if item.icon:
                post_em.set_thumbnail(url=item.icon)
            post_em.set_footer(text="ASTUCE · " + random.choice(_ASTUCES))
            
            await spawn.edit(embed=post_em)
            await spawn.remove_reaction(goodemoji, self.bot.user)
            await spawn.delete(delay=16)
        
        
    async def group_item_spawn(self, channel: discord.TextChannel):
        rdm_items = random.sample(list(self.items.keys()), k=random.randint(2, 4))
        items = [self.get_item(i) for i in rdm_items]
        text = random.choice(("Distribution générale ! Je donne :",
                              "Vous pouvez piocher là-dedans :",
                              "Hop, voilà ce que je donne :",
                              "Des bonbons ? Je vous en donne :"))
        text += '\n'
        text += '\n'.join([f"- **{i}**" for i in items])
        emcolor = HALLOWEEN_COLOR()
        em = discord.Embed(title="🍬 Jeu d'Halloween • Distribution générale", 
                           description=text,
                           color=emcolor)
        em.set_footer(text="Cliquez sur 🍬 pour obtenir un bonbon (au hasard)")

        spawn = await channel.send(embed=em)
        start_adding_reactions(spawn, ["🍬"])
        
        cache = self.get_cache(channel.guild)
        cache['EventUsers'] = {}
        cache['EventType'] = 'item_spawn'
        cache['EventItems'] = items
        cache['EventMsg'] = spawn.id
        
        userlist = []
        timeout = time.time() + 45
        while time.time() < timeout and len(cache["EventUsers"]) < (len(rdm_items) * 2):
            if list(cache["EventUsers"].keys()) != userlist:
                userlist = list(cache["EventUsers"].keys())
                tabl = []
                for uid, gain in cache["EventUsers"].items():
                    gtxt = gain.name if gain else 'Inv. Plein'
                    tabl.append((channel.guild.get_member(uid).name, gtxt))
                nem = discord.Embed(title="🍬 Jeu d'Halloween • Distribution générale",
                                    description=text,
                                    color=emcolor)
                nem.set_footer(text="Cliquez sur 🍬 pour obtenir un bonbon (au hasard)")
                nem.add_field(name="Bonbons obtenus", value=box(tabulate(tabl, headers=["Membre", "Bonbon"])))
                await spawn.edit(embed=nem)
            await asyncio.sleep(0.75)
        
        if time.time() >= timeout:
            end_msg = random.choice(["Distribution terminée, à la prochaine !",
                                     "Temps écoulé, au revoir !",
                                     "Trop tard pour les lents à la détente, à bientôt !"])
        else:
            end_msg = random.choice(["Je n'ai plus de bonbons à vous donner, ça se termine là !",
                                     "Terminé, je n'ai plus rien à vous donner.",
                                     "Je n'ai plus de bonbons à vous donner, à bientôt !",
                                     "Plus rien à donner, c'est fini."])
            
        await spawn.remove_reaction("🍬", self.bot.user)
        if cache["EventUsers"]:
            tabl = []
            for uid, gain in cache["EventUsers"].items():
                gtxt = gtxt = gain.name if gain else 'Inv. Plein'
                tabl.append((channel.guild.get_member(uid).name, gtxt))
            end_em = discord.Embed(title="🍬 Jeu d'Halloween • Distribution générale",
                                description=end_msg,
                                color=emcolor)
            end_em.set_footer(text="ASTUCE · " + random.choice(_ASTUCES))
            end_em.add_field(name="Bonbons obtenus", value=box(tabulate(tabl, headers=["Membre", "Bonbon"])))
        else:
            end_em = discord.Embed(title="🍬 Jeu d'Halloween • Distribution générale",
                                   description=end_msg,
                                   color=emcolor)
            end_em.set_footer(text="ASTUCE · " + random.choice(_ASTUCES))
            end_em.add_field(name="Bonbons obtenus", value=box("Personne n'a participé à la distribution", lang='fix'))
        await spawn.edit(embed=end_em)
        await spawn.delete(delay=30)
        
        
    async def foe_spawn(self, channel: discord.TextChannel):
        foe = self.get_foe()
        diag = random.choice(foe['dialogues'])
        emcolor = HALLOWEEN_COLOR()
        
        if 7 <= datetime.now().hour <= 21:
            foe_pv = random.randint(75, 250)
            sugar = random.randint(10, 30)
            boosted = False
        else:
            foe_pv = random.randint(100, 350)
            sugar = random.randint(15, 35)
            boosted = True
        sanity = round(sugar / 1.5)
            
        foe['pv'] = foe_pv
        
        em = discord.Embed(title=f"🍬 Jeu d'Halloween • COMBAT vs. ***{foe['name']}***", color=emcolor)
        em.set_thumbnail(url=foe['icon'])
        em.description = f'*{diag}*'
        em.add_field(name="Points de vie", value=box(foe_pv if not boosted else f'{foe_pv}ᴮ', lang='css'))
        em.add_field(name="Faible VS", value=box(_TRANSLATIONS[foe['weakdef']], lang='fix'))
        em.set_footer(text="🗡️ Atq. Physique | 🔮 Magie | 💨 Fuir")
        
        spawn = await channel.send(embed=em)
        start_adding_reactions(spawn, ["🗡️", "🔮", "💨"])
        
        cache = self.get_cache(channel.guild)
        cache['EventUsers'] = {}
        cache['EventType'] = 'foe_spawn'
        cache['EventFoe'] = foe
        cache['EventMsg'] = spawn.id
        
        userlist = []
        timeout = time.time() + 45
        while time.time() < timeout and cache['EventFoe']['pv'] > 0:
            if list(cache["EventUsers"].keys()) != userlist:
                userlist = list(cache["EventUsers"].keys())
                tabl = []
                for uid, result in cache["EventUsers"].items():
                    action, dmg = result[0], result[1]
                    tabl.append((channel.guild.get_member(uid).name, _TRANSLATIONS[action], dmg if dmg else '--'))
                
                nem = discord.Embed(title=f"🍬 Jeu d'Halloween • COMBAT vs. ***{foe['name']}***", color=emcolor)
                nem.set_thumbnail(url=foe['icon'])
                nem.description = f'*{diag}*'
                nem.add_field(name="Points de vie", value=box(cache['EventFoe']['pv'] if not boosted else f"{cache['EventFoe']['pv']}ᴮ", lang='css'))
                nem.add_field(name="Faible VS", value=box(_TRANSLATIONS[foe['weakdef']], lang='fix'))
                nem.set_footer(text="🗡️ Atq. Physique | 🔮 Magie | 💨 Fuir")
                nem.add_field(name="Actions", value=box(tabulate(tabl, headers=["Membre", "Action", "Dommages"])), inline=False)
                await spawn.edit(embed=nem)
            await asyncio.sleep(0.75)
        
        if cache['EventFoe']['pv'] <= 0:
            userlist = list(cache["EventUsers"].keys())
            tabl = []
            for uid, result in cache["EventUsers"].items():
                action, dmg = result[0], result[1]
                tabl.append((channel.guild.get_member(uid).name, _TRANSLATIONS[action], dmg if dmg else '--'))
            
            endem = discord.Embed(title=f"🍬 Jeu d'Halloween • VICTOIRE vs. ***{foe['name']}***", color=emcolor)
            endem.set_thumbnail(url=foe['icon'])
            endem.description = f'*{diag}*'
            endem.add_field(name="Points de vie", value=box(cache['EventFoe']['pv'] if not boosted else f"{cache['EventFoe']['pv']}ᴮ", lang='css'))
            endem.set_footer(text="ASTUCE · " + random.choice(_ASTUCES))
            endem.add_field(name="Actions", value=box(tabulate(tabl, headers=["Membre", "Action", "Dommages"])), inline=False)
            endem.add_field(name="Gains (Victoire)", value=f"- **Sucre +{sugar}**\n- **Points +2**\n› Pour tous les participants au combat (fuyards exclus)")
            
            all_members = await self.config.all_members(channel.guild)
            for u in [m for m in cache["EventUsers"] if cache["EventUsers"][m][0] != 'escape']:
                if u not in all_members:
                    continue
                member = channel.guild.get_member(u)
                current = all_members[u]['Sugar']
                await self.config.member(member).Sugar.set(current + sugar)
                
                pts = await self.config.member(member).Points()
                await self.config.member(member).Points.set(pts + 2)

        elif cache['EventUsers']:
            userlist = list(cache["EventUsers"].keys())
            tabl = []
            for uid, result in cache["EventUsers"].items():
                action, dmg = result[0], result[1]
                tabl.append((channel.guild.get_member(uid).name, _TRANSLATIONS[action], dmg if dmg else '--'))
            
            endem = discord.Embed(title=f"🍬 Jeu d'Halloween • DEFAITE vs. ***{foe['name']}***", color=emcolor)
            endem.set_thumbnail(url=foe['icon'])
            endem.description = f'*{diag}*'
            endem.add_field(name="Points de vie", value=box(cache['EventFoe']['pv'] if not boosted else f"{cache['EventFoe']['pv']}ᴮ", lang='css'))
            endem.set_footer(text="ASTUCE · " + random.choice(_ASTUCES))
            endem.add_field(name="Actions", value=box(tabulate(tabl, headers=["Membre", "Action", "Dommages"])), inline=False)
            endem.add_field(name="Perte (Défaite)", value=f"**Sanité -{sanity}** [**-{round(sanity / 3)}** pour les Vampires]\n› Pour tous les membres présents récemment (fuyards exclus)")
            
            interact = [m for m in cache["UserActivity"] if cache['UserActivity'][m] >= time.time() - 300]
            for m in cache['EventUsers']:
                if m not in interact:
                    interact.append(m)
            
            all_members = await self.config.all_members(channel.guild)
            for u in [m for m in interact if cache["EventUsers"].get(m, ['none', 0])[0] != 'escape']:
                if u not in all_members:
                    continue
                member = channel.guild.get_member(u)
                mguild = await self.check_user_guild(member)
                current = all_members[u]['Sanity']
                if mguild == 'vampire':
                    await self.config.member(member).Sanity.set(max(0, current - round(sanity / 3)))
                else:
                    await self.config.member(member).Sanity.set(max(0, current - sanity))
                
        else:
            sanity -= round(sanity * 0.33)
            endem = discord.Embed(title=f"🍬 Jeu d'Halloween • DEFAITE vs. ***{foe['name']}***", color=emcolor)
            endem.set_thumbnail(url=foe['icon'])
            endem.description = f'*{diag}*'
            endem.add_field(name="Points de vie", value=box(cache['EventFoe']['pv'] if not boosted else f"{cache['EventFoe']['pv']}ᴮ", lang='css'))
            endem.set_footer(text="ASTUCE · " + random.choice(_ASTUCES))
            endem.add_field(name="Actions", value=box('Aucun participant', lang='fix'), inline=False)
            endem.add_field(name="Perte (Défaite)", value=f"**Sanité -{sanity}** [**-{round(sanity / 3)}** pour les Vampires]\n› Pour tous les membres présents récemment (fuyards exclus)")
            
            interact = [m for m in cache["UserActivity"] if cache['UserActivity'][m] >= time.time() - 300]
            
            all_members = await self.config.all_members(channel.guild)
            for u in [i for i in interact if i in all_members]:
                if u not in all_members:
                    continue
                member = channel.guild.get_member(u)
                mguild = await self.check_user_guild(member)
                current = all_members[u]['Sanity']
                if mguild == 'vampire':
                    await self.config.member(member).Sanity.set(max(0, current - round(sanity / 3)))
                else:
                    await self.config.member(member).Sanity.set(max(0, current - sanity))
        await spawn.edit(embed=endem)
        await spawn.delete(delay=50)
        
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            guild = message.guild
            user = message.author
            if user.bot:
                return
            
            cache = self.get_cache(guild)
            
            cache['UserActivity'][user.id] = time.time()
            if cache['SanityLossCD'].get(user.id, 0) <= time.time() - 300:
                if await self.config.member(user).Sanity() < 25:
                    if random.randint(0, 2) == 0:
                        currentsug = await self.config.member(user).Sugar()
                        if currentsug:
                            await self.config.member(user).Sugar.set(max(0, currentsug - 5))
                        cache['SanityLossCD'][user.id] = time.time()
                        
            userguild = await self.check_user_guild(user)
            if userguild == 'vampire':
                if cache['SanityVamp'].get(user.id, 0) <= time.time() - 450:
                    if await self.config.member(user).Pocket():
                        if cache['SickUser'].get(user.id, 0) + 3600 > time.time():
                            cache['SanityVamp'][user.id] = time.time()
                            
                            cursan = await self.config.member(user).Sanity()
                            await self.config.member(user).Sanity.set(min(100, cursan + 1))
            
            cache['EventCounter'] += 1
            if cache['EventCounter'] >= cache['EventCounterThreshold']:
                if cache['EventCD'] + 900 < time.time() and not cache['EventCurrent']:
                    cache['EventCounter'] = 0
                    cache['EventCurrent'] = True
                    channels = await self.config.guild(guild).Events.get_raw('channels')
                    if not channels:
                        return
                    channelid = random.choice(channels)
                    channel = guild.get_channel(channelid)
                    
                    await asyncio.sleep(random.randint(1, 5))
                    event = random.choices(('simple_item', 'group_item', 'foe'), weights=(1.0, 0.9, 0.75), k=1)[0]
                    if event == 'simple_item':
                        await self.simple_item_spawn(channel)
                    elif event == 'group_item':
                        await self.group_item_spawn(channel)
                    else:
                        await self.foe_spawn(channel)
                    
                    basecounter = await self.config.guild(guild).Events.get_raw('counter_threshold')
                    if 1 <= datetime.now().hour <= 7:
                        basecounter = round(basecounter * 0.66)
                    cache['EventCounterThreshold'] = random.randint(int(basecounter * 0.90), int(basecounter * 1.10))
                    cache['EventCD'] = time.time()
                    cache['EventCurrent'] = False
    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        message = reaction.message
        if message.guild:
            cache = self.get_cache(message.guild)
            if not user.bot:
                if message.id == cache["EventMsg"]:
                    if cache["EventType"] == 'item_spawn' and reaction.emoji == "🍬":
                        if user.id not in cache["EventUsers"]:
                            item = random.choice(cache["EventItems"])
                            try:
                                await self.pocket_add(user, item, 1)
                            except:
                                cache["EventUsers"][user.id] = False
                            else:
                                cache["EventUsers"][user.id] = item
                    
                    elif cache['EventType'] == "foe_spawn":
                        if user.id not in cache["EventUsers"]:
                            user_guild = await self.check_user_guild(user)
                            foe_weak = cache['EventFoe']['weakdef']
                            atk_values = _GUILDS[user_guild]['atkvalues']
                            
                            dmg = random.randint(15, 50)
                            
                            if reaction.emoji == "🗡️":
                                action = 'physical'
                            elif reaction.emoji == "🔮":
                                action = 'magic'
                            elif reaction.emoji == "💨":
                                action = 'escape'
                            else:
                                action = random.choice(('physical', 'magic'))
                            
                            if action != 'escape':
                                dmg *= atk_values[action]
                                if action == foe_weak:
                                    dmg *= random.uniform(1.5, 2)
                                cache["EventFoe"]['pv'] = max(0, cache["EventFoe"]['pv'] - round(dmg))
                            else:
                                dmg = 0
                                
                            cache["EventUsers"][user.id] = (action, round(dmg))


    @commands.group(name="oktset")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_messages=True)
    async def oktbr_settings(self, ctx):
        """Commandes de gestion de l'event d'Halloween"""
        
    @oktbr_settings.command(name="counter")
    async def set_counter(self, ctx, value: int):
        """Modifier le nombre de cycles (de base) avant l'apparition d'un évènement
        
        1 cycle = 1 msg"""
        guild = ctx.guild
        if value >= 1:
            cache = self.get_cache(guild)
            cache['EventCounterThreshold'] = value
            await self.config.guild(guild).Events.set_raw("counter_threshold", value=value)
            return await ctx.send(f"Valeur modifiée · Le bot tentera de se rapprocher de {value} cycles pour les évènements")
        await ctx.send(f"Impossible · La valeur doit être supérieure ou égale à 1 cycle")
        
    @oktbr_settings.command(name="cooldown")
    async def set_events_cd(self, ctx, value: int):
        """Modifier le cooldown minimal en secondes entre deux events"""
        guild = ctx.guild
        if value >= 60:
            cache = self.get_cache(guild)
            await self.config.guild(guild).Events.set_raw("counter_threshold", value=value)
            return await ctx.send(f"Valeur modifiée · Le bot tentera de se rapprocher de {value}s entre les évènements")
        await ctx.send(f"Impossible · La valeur doit être supérieure ou égale à 1m (60s)")
        
    @oktbr_settings.command(name="channels")
    async def set_channels(self, ctx, channels: Greedy[discord.TextChannel] = None):
        """Configure les salons où peuvent apparaître les évènements"""
        guild = ctx.guild
        if not channels:
            await self.config.guild(guild).Events.clear_raw('channels')
            return await ctx.send(f"Salons retirés · Plus aucun évènement n'apparaîtra sur vos salons écrits.")
        else:
            ids = [c.id for c in channels]
            await self.config.guild(guild).Events.set_raw('channels', value=ids)
            return await ctx.send(f"Salons modifiés · Les évènements pourront apparaître sur les salons donnés.")
        
    @oktbr_settings.command(name="guildset")
    async def set_user_guild(self, ctx, user: discord.Member, guildname: str):
        """Modifier la guilde d'un membre
        
        __Noms normalisés des guildes :__
        `sorcerer` (Sorcier)
        `werewolf` (Loup-Garou)
        `vampire` (Vampire)"""
        guildname = guildname.lower()
        if guildname not in list(_GUILDS.keys()):
            return await ctx.send(f"Nom de guilde invalide · Voyez l'aide de la commande pour voir les noms normalisés des guildes.")

        await self.config.member(user).Guild.set(guildname)
        await ctx.send(f"Guilde modifiée · {user.mention} a rejoint la guilde des ***{_GUILDS[guildname]['name']}***.")
            
    @oktbr_settings.command(name="pocketsize")
    @checks.is_owner()
    async def pocket_size(self, ctx, value: int):
        """Modifier la taille des poches des membres"""
        if value > 10:
            await self.config.PocketSize.set(value)
            return await ctx.send(f"Valeur modifiée · Les membres auront désormais des poches de {value} slots")
        await ctx.send(f"Impossible · La valeur doit être supérieure à 10 slots")
    