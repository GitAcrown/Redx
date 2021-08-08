import asyncio
import logging
import random
import time
from copy import copy

import discord
from discord import channel
from discord.errors import DiscordException
from typing import Union, List, Literal

from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate
from redbot.core.data_manager import cog_data_path, bundled_data_path

RoyaleColor = 0xFFC107

IA_NAMES = ['Aphrodite', 'Apollon', 'Artemis', 'Athena', 'Charon', 'Eris', 'Gaia', 'Hades', 'Hephaistos', 'Hermes', 'Morphee', 'Persephone', 'Ploutos', 'Zeus']

PASSIVES = {
    'simp': ('Simp', "Regagne 15% de ses PV à chaque action de coopération avec un autre champion"),
    'survivor' : ('Survivor', "Double la probabilité que votre Champion se batte plutôt qu'une autre action"),
    'diamond' : ('Diamond', "A chaque fin de journée survécue : +10 pts d'Armure"),
    'disco': ('Disco', "Immunisé contre les attaques à distance des autres champions"),
    'king': ('King', "Double toutes les stats du Champion lorsqu'il ne reste plus qu'un seul autre concurrent en vie"),
    'queen': ('Queen', "Commence la partie avec 150 PV (à la place de 100)")
}


class RoyalePlayer:
    def __init__(self, user: discord.Member, champion_data: dict):
        self.user, self.guild = user, user.guild
        self.data = champion_data
        
        self.status = 1
        self.hp = 100 if self.passive != 'queen' else 150
        self.armor = 0
        
        self.atk = 1
        
        self.last_action = None
                
    def __str__(self):
        return f'**{self.user.display_name}**'
    
    @property
    def passive(self):
        return self.data['passive']
    
    
class RoyaleIA:
    def __init__(self, guild: discord.Guild, name: str):
        self.guild = guild
        self.name = name
        self.data = self.generate_data(name.lower())
        self.user = None
        
        self.status = 1
        self.hp = 100 if self.passive != 'queen' else 150
        self.armor = 0
        
        self.atk = 1
        
        self.last_action = None
                
    def __str__(self):
        return f'**{self.name} [IA]**'
    
    def generate_data(self, seed: str):
        rng = random.Random(seed)
        data = {
            'passive': rng.choice(list(PASSIVES.keys()))
        }
        return data
    
    @property
    def passive(self):
        return self.data['passive']


class Royale(commands.Cog):
    """Battle Royale sur Discord"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {
            'Champion': {
                'img': None,
                'rang': 0,
                
                'passive': None
            },
            'xp': 0,
            'next_unlock': 100,
            'unlocked_passives': []
        }

        default_guild = {
            'MaxPlayers' : 8,
            'TimeoutDelay' : 120,
            'TicketPrice' : 50
        }
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

        self.cache = {}
        
        
    # Parties    
        
    def get_cache(self, guild: discord.Guild):
        if guild.id not in self.cache:
            self.cache[guild.id] = {
                'status': 0,
                'players': [],
                'register_msg': None
            }
        return self.cache[guild.id]
    
    def clear_cache(self, guild: discord.Guild):
        try:
            del self.cache[guild.id]
        except KeyError:
            pass
        
    async def add_player(self, user: discord.Member):
        guild = user.guild
        cache = self.get_cache(guild)
        if not cache['status'] == 1:
            raise ValueError("La valeur de statut du cache lors de l'inscription doit être 1")
        if cache['players']:
            if user.id in [p.user.id for p in cache['players']]:
                return
        champ_data = await self.config.member(user).Champion()
        player = RoyalePlayer(user, champ_data)
        cache['players'].append(player)
        
    def add_ia_players(self, guild: discord.Guild, limit: int = 4):
        cache = self.get_cache(guild)
        if not cache['status'] == 1:
            raise ValueError("La valeur de statut du cache lors de l'inscription doit être 1")
        if 2 <= len(cache['players']) < limit: 
            names = random.choices(IA_NAMES, k = limit - len(cache['players']))
            for n in names:
                ia = RoyaleIA(guild, n)
                cache['players'].append(ia)

    def get_actions_weights(self, player: Union[RoyalePlayer, RoyaleIA]):
        if not player.last_action:
            return ()

    @commands.command(name="royale")
    async def start_royale(self, ctx):
        """Démarrer une partie de Battle Royale"""
        guild = ctx.guild
        author = ctx.author
        
        cache = self.get_cache(guild)
        settings = await self.config.guild(guild).all()
        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        
        if cache['status'] == 1:
            return await ctx.send("**Inscriptions déjà en cours** — Des inscriptions pour une partie ont déjà été lancées sur ce serveur. Cliquez sur 🎫 sous le message d'inscription pour rejoindre la partie.")
        elif cache['status'] == 2:
            return await ctx.send("**Partie en cours** — Une partie de BR est déjà en cours sur ce serveur. Attendez qu'elle finisse pour en lancer une autre.")
        
        
        if not await eco.check_balance(author, settings['TicketPrice']):
            return await ctx.reply(f"**Impossible de lancer une partie** — Votre solde ne permet pas d'acheter votre propre ticket ({settings['TicketPrice']}{currency})", 
                                    mention_author=False)
            
        cache['status'] = 1
        timeout = time.time() + settings['TimeoutDelay']
        
        await self.add_player(author)
        players_cache = []
        msg = None
        
        while len(cache['players']) < settings['MaxPlayers'] \
            and time.time() <= timeout \
                and cache['status'] == 1:
                    
            if players_cache != cache['players']:
                desc = '\n'.join((f'• {p}' for p in cache['players']))
                em = discord.Embed(title=f"Battle Royale — Inscriptions ({len(cache['players'])}/{settings['MaxPlayers']})", description=desc, color=RoyaleColor)
                em.set_footer(text=f"Cliquez sur 🎫 pour s'inscrire ({settings['TicketPrice']}{currency})")
                if not msg:
                    msg = await ctx.send(embed=em)
                    await msg.add_reaction('🎫')
                    cache['register_msg'] = msg.id
                else:
                    await msg.edit(embed=em)
                players_cache = cache['players']
            await asyncio.sleep(1)
            
        if len(cache['players']) < 2:
            self.clear_cache(guild)
            em = discord.Embed(title="Battle Royale — Inscriptions", 
                                description= "**Inscriptions annulées** : Manque de joueurs (min. 2)", 
                                color=RoyaleColor)
            em.set_footer(text=f"Aucune somme n'a été prélevée sur le compte des inscrits")
            return await msg.edit(embed=em)
        
        await msg.clear_reactions()
        em.set_footer(text=f"Vérification des soldes & paiements ···")
        await msg.edit(embed=em)
        
        newcache = copy(cache['players'])
        for p in cache['players']:
            try:
                await eco.withdraw_credits(p.user, settings['TicketPrice'], desc='Participation à une partie BR')
            except ValueError:
                newcache.remove(p)
                await ctx.send(f"**Correction** — {p.user.mention} a été kick de la partie par manque de fonds", delete_after=10)
                await asyncio.sleep(1)
        
        cache['players'] = newcache
        await asyncio.sleep(3)
        await msg.delete()
        cache['status'] = 2
        
        desc = '\n'.join((f'• {p}' for p in cache['players']))
        em = discord.Embed(title="Battle Royale — Joueurs", 
                                description=desc, 
                                color=RoyaleColor)
        
        if len(cache['players']) < 4:
            em.set_footer(text=f"Ajout d'IA ···")
            msg = await ctx.send(embed=em)
            self.add_ia_players(guild)
            await asyncio.sleep(3)
            
            desc = '\n'.join((f'• {p}' for p in cache['players']))
            em = discord.Embed(title="Battle Royale — Joueurs", description=desc, color=RoyaleColor)
            em.set_footer(text=f"La partie va bientôt commencer ···")
            await msg.edit(embed=em)
        else:
            em.set_footer(text=f"La partie va bientôt commencer ···")
            msg = await ctx.send(embed=em)
        await asyncio.sleep(5)

        ACTIONS = ('neutral', 'atk', 'coop_2', 'coop_3', 'explo', 'find_obj', 'find_place')
        while len([p for p in cache['players'] if p.status != 0]) > 1 and cache['status'] == 2:
            for player in [q for q in cache['players'] if q.status != 0]:
                
                actions = random.choices(ACTIONS, act_weights, k=1)[0]
                
        
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        channel = self.bot.get_channel(payload.channel_id)
        emoji = payload.emoji
        if hasattr(channel, "guild"):
            guild = channel.guild
            if emoji == '🎫':
                message = await channel.fetch_message(payload.message_id)
                user = guild.get_member(payload.user_id)
                cache = self.get_cache(guild)
                if message.id != cache['registrer_msg']:
                    return
                if cache['players']:
                    if user.id in [p.user.id for p in cache['players']]:
                        return
                
                settings = await self.config.guild(guild).all()
                eco = self.bot.get_cog('AltEco')
                currency = await eco.get_currency(guild)
                if not await eco.check_balance(user, settings['TicketPrice']):
                    await message.remove_reaction('🎫', user)
                    await channel.send(f"{user.mention} — Votre solde est insuffisant pour participer à cette partie ({settings['TicketPrice']}{currency})",
                                       delete_after=15)
                
                await self.add_player(user)
                