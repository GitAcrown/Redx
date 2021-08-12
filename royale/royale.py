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
    'ragequit': ('Ragequit', "A sa mort, empoisonne son tueur (sauf renvoi de dégats)"),
    'survivor' : ('Survivor', "Double la probabilité que votre Champion se batte plutôt qu'une autre action"),
    'gold' : ('Gold', "A chaque fin de journée survécue : +10 pts d'Armure"),
    'house': ('House', "Ne peut être attaqué lorsqu'il est dans une action de repos"),
    'king': ('King', "Double les stats d'attaque et de défense de base du Champion lorsqu'il ne reste plus qu'un seul autre concurrent en vie")
}

COMMENTATEURS = ('***Caligula***', '***Auguste***')

class RoyalePlayer:
    def __init__(self, user: discord.Member, champion_data: dict):
        self.user, self.guild = user, user.guild
        self.data = champion_data
        
        self.status = 1
        self.hp = 100
        self.armor = 0
        
        self.base_atk = 1
        self.bonus_atk = 0
        self.base_dfs = 1
        self.bonus_dfs = 0
        
        self.last_action = None
        self.passive_status = 0
                
    def __str__(self):
        return f'**{self.user.display_name}**'
    
    @property
    def passive(self):
        return self.data['passive']
    
    @property
    def atk(self):
        return self.base_atk + self.bonus_atk
    
    @property
    def dfs(self):
        return self.base_dfs + self.bonus_dfs
    
    def get_damaged(self, dmg: Union[float, int]):
        dmg = round(dmg)
        if self.armor <= dmg:
            dmg -= self.armor
            self.armor = 0
        elif self.armor > dmg:
            self.armor -= dmg
            dmg = 0
            
        if dmg:
            self.hp -= min(self.hp, dmg)
        
        if self.hp == 0:
            self.status = 0
        
        return dmg
    
    
class RoyaleIA:
    def __init__(self, guild: discord.Guild, name: str):
        self.guild = guild
        self.name = name
        self.data = self.generate_data(name.lower())
        self.user = None
        
        self.status = 1
        self.hp = 100
        self.armor = 0
        
        self.base_atk = 1
        self.bonus_atk = 0
        self.base_dfs = 1
        self.bonus_dfs = 0
        
        self.last_action = None
        self.passive_status = 0
                
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
    
    @property
    def atk(self):
        return self.base_atk + self.bonus_atk
    
    @property
    def dfs(self):
        return self.base_dfs + self.bonus_dfs
    
    def get_damaged(self, dmg: Union[float, int]):
        dmg = round(dmg)
        if self.armor <= dmg:
            dmg -= self.armor
            self.armor = 0
        elif self.armor > dmg:
            self.armor -= dmg
            dmg = 0
            
        if dmg:
            self.hp -= min(self.hp, dmg)
        
        if self.hp == 0:
            self.status = 0
        
        return dmg


class Royale(commands.Cog):
    """Battle Royale sur Discord"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {
            'Champion': {
                'img': None,
                'stats': [0, 0],
                
                'passive': None
            },
            'xp': 0,
            'next_unlock': 100,
            'unlocked_passives': []
        }

        default_guild = {
            'SeasonNb': 1,
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

    def get_actions_weights(self, player: Union[RoyalePlayer, RoyaleIA], hour: int, *, starting: dict = None) -> dict:
        if not starting:
            ACTIONS = {
                'neutral': 1,
                'atk':  1,
                'coop_2': 0.5,
                'coop_3': 0.3,
                'explo': 1,
                'find_obj': 0.5,
                'find_place': 0.5,
                'rest': 0.25
            }
        else:
            ACTIONS = starting
            
        if hour <= 2:
            ACTIONS['atk'] *= 1.5
        
        if player.passive == 'survivor':
            ACTIONS['atk'] *= 2
            
        if player.last_action == 'explo':
            ACTIONS['find_obj'] *= 3
            ACTIONS['find_place'] *= 3
        elif player.last_action == 'coop_2':
            ACTIONS['coop_3'] /= 2
        elif player.last_action == 'coop_3':
            ACTIONS['coop_2'] /= 2
        elif player.last_action == 'atk':
            ACTIONS['rest'] *= 2

        ACTIONS[player.last_action] /= 2
        return ACTIONS
        

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
    
        # ===== BOUCLES JOURS =====
        Hour = 1
        season = settings['SeasonNb']
        get_comment = lambda x: random.sample(COMMENTATEURS, k=x)
        
        while len([p for p in cache['players'] if p.status != 0]) > 1 and cache['status'] == 2:
            alive = [p for p in cache['players'] if p.status != 0]
            random.shuffle(alive)
            
            if Hour == 1:
                begintxt = f"{get_comment(1)} : La saison {season} du Battle Royale de {ctx.guild.name} commence !\nQue le sort vous soit favorable et __bonne chance__ !"
            else:
                com = get_comment(2)
                rdm_player = random.choice(alive)
                begintxt = random.choice((f"{com[0]} : Il semblerait que certains joueurs s'en sortent mieux que d'autres mon cher {com[1]} !\n{com[1]} : Oui je vois bien ça {com[0]} ! Allez courage vous tous.",
                                          f"{com[0]} : Eh bien, il ne reste déjà plus que {len(alive)} concurrents !\n{com[1]} : Je pense que ça ne va pas assez vite, vous ne trouvez pas {com[0]} ?\n{com[0]} : Si.",
                                          f"{com[0]} : Dis donc, il ne reste déjà plus que {len(alive)} concurrents !\n{com[1]} : Je trouve que ça ne va pas assez vite, ne trouvez-vous pas {com[0]} ?\n{com[0]} : Plus ça dure, mieux c'est !",
                                          f"{com[0]} : On s'ennuie un peu là, non ?\n{com[1]} : Mais voyons, c'est que la {Hour}e heure ! Soyez patient.",
                                          f"{com[0]} : Sommes-nous payés pour ce job, {com[1]} ?\n{com[1]} : Non {com[0]}, nous ne sommes même pas réels, c'est {self.bot.user.name} qui simule des commentateurs sportifs...\n{com[0]} : Pardon ?! On m'avait pas prévenu.",
                                          f"{com[0]} : On va commander à manger je pense qu'on a le temps.\n{com[1]} : Il ne se passe pas grand chose d'intéressant en effet.\n{com[0]} : Mettez la caméra de {rdm_player}, les autres on s'en fout.",
                                          f"{com[0]} : Vous avez vu l'action incroyable de {rdm_player} ?\n{com[1]} : Non j'ai pas vu, il s'est passé quoi ?\n{com[0]} : Rien de fou.\n{com[1]} : Ah.",
                                          f"{com[0]} : C'est lequel votre favori pour l'instant, {com[1]} ?\n{com[1]} : Je sais pas trop. Vous c'est lequel ?\n{com[0]} : C'est {rdm_player}.\n{com[1]} : Ah. Choix intéressant j'imagine.",
                                          f"{com[0]} : C'est lequel votre favori là, {com[1]} ?\n{com[1]} : Je dirais sans hésiter {rdm_player}.\n{com[0]} : Moi aussi tiens. Vous avez bon goût mon cher {com[1]} !",
                                          f"{com[0]} : C'est lequel votre favori pour l'instant, {com[1]} ?\n{com[1]} : Je ne sais pas. Vous diriez lequel vous ?\n{com[0]} : C'est {rdm_player} mon petit préféré, évidemment.\n{com[1]} : J'aime ce choix, intéressant.",
                                          f"{com[0]} : C'est lequel votre préféré dans nos concurrents actuellement, {com[1]} ?\n{com[1]} : Je ne vais pas vous le dire, ça pourrait lui porter malchance. Vous ?\n{com[0]} : J'aurais dis {rdm_player}.\n{com[1]} : Euh, ok pourquoi pas."))
            em = discord.Embed(title=f"Battle Royale S{season} — Heure {Hour}", description=begintxt, color=RoyaleColor)
            
            for player in alive: # === BOUCLE JOUEURS / JOUR ===
                txts = []
                if Hour == 1:
                    if player.passive == 'survivor':
                        txts.append(f"🥊 SURVIVOR : {player} est enragé (2x plus de chance d'attaquer plutôt que faire une autre action)")
                
                actions = self.get_actions_weights(player, Hour)
                other_players = [q for q in alive if q != player]
                
                if len(other_players) == 1:
                    if player.passive == 'king' and player.passive_status == 0:
                        player.passive_status = 1
                        player.base_atk *= 2
                        player.base_dfs *= 2
                        txts.append(f"👑 KING : {player} veut en finir (Stats d'attaque et de défense de base multipliés par 2)")
                
                if alive < 3:
                    actions.update({'coop_2': 0, 'coop_3': 0})
                    actions['atk'] *= 1.5
                elif alive < 4:
                    actions.update({'coop_3': 0})
                    actions['coop_2'] /= 2
                    
                event = random.choices(list(actions.keys()), list(actions.values()), k=1)[0]
                
                if event == 'neutral': # ---- EVENEMENT NEUTRE
                    other_player = random.choice(other_players)
                    options = (f"{player} se met à observer de loin l'arène",
                               f"{player} décide d'observer les alentours avant de faire quelque chose",
                               f"{player} refait ses lacets...",
                               f"{player} se met à fixer le ciel avec des pensées suicidaires...",
                               f"{player} se met à se masturber furieusement sur {other_player}",
                               f"{player} décide de s'asseoir et se reposer un peu",
                               f"{player} se décide à suivre {other_player} discrètement")
                    txts.append(random.choice(options))
                    
                elif event == 'atk': # ---- ATTAQUER (SOLO)
                    possibles_targets = [p for p in other_players if not (p.passive == 'house' and p.last_action == 'rest')]
                    if not possibles_targets:
                        options = (f"{player} se préparait à attaquer mais sa cible a disparue...",
                                   f"{player} voulait attaquer un autre concurrent mais s'est pris les pieds dans une racine",
                                   f"{player} abandonne sa cible lâchement",
                                   f"{player} perd toute envie de se battre")
                        txts.append(random.choice(options))
                        
                    else:
                        target = random.choice(possibles_targets)
                        
                        is_crit = random.randint(0, 5)
                        if is_crit == 0:
                            player_atk = random.randint(20, 60)
                        else:
                            player_atk = random.randint(5, 20)
                        player_atk *= player.atk
                        subtxt = []
                        subtxt.append(random.choice((f"> {player} se lance violemment sur {target} !",
                                                     f"> {player} tombe soudainement sur {target} et décide de l'attaquer !",
                                                     f"> {target} voit {player} lui tomber dessus violemment !",
                                                     f"> {player} se décide à attaquer {target} !\n")))
                        
                        dmg = round(player_atk / target.dfs)
                        subtxt += f"> ⚔️ {player} inflige **{dmg} DMGs** à {target}\n"
                        return_dmg = random.randint(0, 5)
                        if return_dmg == 0:
                            returned = dmg / 3
                            dmg -= returned
                            subtxt.append(f"> 🛡️ {target} se défend et renvoie **{returned} DMGs** à {player}")
                        
                        player.get_damaged(returned)
                        if player.status == 0:
                            subtxt += f"> ☠️ {player} __{random.choice(('est décédé', 'est mort', 'a succombé'))}__"
                            
                        target.get_damaged(dmg)
                        if target.status == 0:
                            subtxt += f"> ☠️ {target} __{random.choice(('est décédé', 'est mort', 'a succombé'))}__"
                            if player.status != 0 and target.passive == 'ragequit':
                                player.status = 2
                                subtxt += f"> 🧪 RAGEQUIT de {target} : {player} est désormais __empoisonné__ (-5% de PV chaque heure)"
                        
                        txts.append('\n'.join(subtxt))
                        
                        
                        

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
                
