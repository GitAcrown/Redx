import logging
import asyncio
import random
from os import name
import time
from datetime import datetime
from operator import itemgetter
from copy import copy

import discord
from typing import Callable, List, Union
from discord.channel import TextChannel

import json
from redbot.core import Config, commands, checks
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box, humanize_number
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate

logger = logging.getLogger("red.RedX.WordleX")


class WordleX(commands.Cog):
    """Algorithme de résolution de Wordle"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)
        
        default_user = {
            "Solver": {}
        }
        
        self.config.register_user(**default_user)
        
    
    def _load_bundled_data(self):
        path = bundled_data_path(self) / 'words.json'
        with path.open() as json_data:
            self.words = json.load(json_data)
            
        logger.info("Chargement des mots Wordle effectué avec succès")
    
    
    def most_used_letters(self, lang: str) -> dict:
        """Renvoie les lettres les plus utilisées dans les mots possédés de la langue selectionnée"""
        try:
            wordlist = self.words[lang.lower()]
        except:
            raise KeyError(f"La langue '{lang}' n'est pas disponible")
        
        lscore = {}
        for w in wordlist:
            for l in w:
                lscore[l] = lscore.get(l, 0) + 1
        
        return lscore

    def score_words(self, lang: str, wordlist: list = None, first: bool = False) -> dict:
        """Calcule un score des mots disponibles en fonction de l'apparition des lettres dans la langue séléctionnée"""
        if not wordlist:
            try:
                wordlist = self.words[lang.lower()]
            except:
                raise KeyError(f"La langue '{lang}' n'est pas disponible")
        
        lscore = self.most_used_letters(lang)
        wscore = {}
        for w in wordlist:
            wscore[w] = sum([lscore[l] for l in list(set(w))]) if first else sum([lscore[l] for l in w])
        
        return wscore
    
    def score_words_advanced(self, lang: str, tries: list, wrong_letters: list) -> dict:
        """Calcule un score des mots disponibles en prenant en compte l'avancement actuel de la session"""
        try:
            wordlist = self.words[lang.lower()]
        except:
            raise KeyError(f"La langue '{lang}' n'est pas disponible")
        if not tries:
            raise IndexError("La liste des essais est vide")
        
        combi_try = ['-', '-', '-', '-', '-']
        for t in tries:
            i = 0
            for l in t:
                if l.isupper() and combi_try[i] == '-':
                    combi_try[i] = l
                i += 1
                    
        wordlist = [w for w in wordlist if not [l for l in w if l in wrong_letters]]
                    
        wlcache = copy(wordlist)
        for w in wlcache: # Lettres majs
            for x, y in zip(w, combi_try):
                if y == '-':
                    pass
                elif x.upper() != y:
                    wordlist.remove(w)
                    break
        
        wlcache = copy(wordlist)
        for tr in [t for t in tries if [l for l in t if l.islower()]]: # Lettres minuscules
            for w in wlcache: 
                for x, y in zip(w, tr):
                    if y == '-' or y.isupper():
                        pass
                    elif x.lower() == y:
                        wordlist.remove(w)
                        break
        
        wlcache = copy(wordlist)
        lower_letters = [l for wl in tries for l in wl if l.islower()]
        for ll in lower_letters:
            for w in wlcache:
                if ll not in w:
                    wordlist.remove(w)
                    break
                    
        return self.score_words(lang, wordlist)
    

    @commands.group(name="wordle")
    async def wordle_solver(self, ctx):
        """Commandes du résolveur de Wordle"""
        
    @wordle_solver.command(name="start")
    async def start_solver(self, ctx, lang: str = 'en'):
        """Démarrer un résolveur de Wordle (personnel)
        
        ATTENTION : Démarrer un résolveur effacera toute session passée !"""
        user = ctx.author
        
        if lang.lower() not in self.words:
            return await ctx.reply(f"**Erreur** · La langue '{lang}' n'est pas disponible (pour le moment)", mention_author=False)
        
        await self.config.user(user).Solver.clear()
        solver = {
            'lang': lang,
            'tries': [],
            'wrong': []
        }
        
        start_words = self.score_words(lang, first=True)
        sorted_words = sorted([(w, start_words[w]) for w in start_words], key=itemgetter(1), reverse=True)
        best_words = [w[0].upper() for w in sorted_words][:5]
        
        await self.config.user(user).Solver.set(solver)
        
        em = discord.Embed(title="**Wordle** · Suggestions de mot de départ", description=f"Voici les mots optimaux pour commencer : `{', '.join(best_words)}`")
        em.set_footer(text="Utilisez la commande 'wordle next' pour poursuivre")
        await ctx.reply(embed=em, mention_author=False)
        
    @wordle_solver.command(name="next")
    async def next_solver(self, ctx):
        """Ajouter des mots au résolveur de Wordle (personnel)
        
        A faire après `wordle start` !"""
        user = ctx.author
        
        solver = await self.config.user(user).Solver()
        if not solver:
            return await ctx.reply(f"**Erreur** · Vous devez d'abord démarrer une session avec `wordle start` !", mention_author=False)
    
        wnum = len(solver['tries']) + 1
        if wnum == 1:
            em = discord.Embed(title="**Wordle** · Mot de départ", description=f"Quel mot de départ avez-vous choisi ?")
            em.set_footer(text="» Indiquez ci-dessous le mot choisi :")
        else:
            em = discord.Embed(title="**Wordle** · Tentative #{wnum}", description=f"Quel mot avez-vous choisi ?")
            em.set_footer(text="» Indiquez ci-dessous le mot choisi :")
            
        msg = await ctx.reply(embed=em, mention_author=False)
        
        try:
            wordrep = await self.bot.wait_for('message', timeout=30, check=lambda m: m.author == user and len(m.content) == 5)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"**Session expirée** · Relancez la commande quand vous voudrez soumettre vos choix et résultats Wordle", mention_author=False)
        
        word = wordrep.content.lower()
        
        em = discord.Embed(title="**Wordle** · Résultat de #{wnum}", description=f"Indiquez le résultat de cette tentative : **{word.upper()}**" + "\n\n" + f"`{word[0].lower()}` Lettre minuscule si lettre en mauvaise position (orange)" + "\n"+ f"`{word[0].upper()}` Lettre majuscule si lettre en bonne position (vert)" + "\n" + "`-` Si mauvaise lettre (gris)")
        em.set_footer(text="» Indiquez ci-dessous le résultat :")
            
        msg = await ctx.reply(embed=em, mention_author=False)
        
        try:
            resultrep = await self.bot.wait_for('message', timeout=120, check=lambda m: m.author == user and len(m.content) == 5)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"**Session expirée** · Relancez la commande quand vous voudrez soumettre vos choix et résultats Wordle", mention_author=False)
        
        result = resultrep.content
        
        old_combi_try = ['-', '-', '-', '-', '-']
        for t in solver['tries']:
            i = 0
            for l in t:
                if l.isupper() and old_combi_try[i] == '-':
                    old_combi_try[i] = l
                i += 1
        
        wtry = [w for w in word.upper()]
        wsave = []
        i = 0
        for r in result:
            if r == '-':
                wsave.append('-')
                if wtry[i].lower() not in solver['wrong']:
                    if wtry[i].upper() not in old_combi_try and wtry[i].upper() not in result.upper():
                        solver['wrong'].append(wtry[i].lower())
            elif r == wtry[i].upper():
                wsave.append(r)
            elif r == wtry[i].lower():
                wsave.append(r)
            i += 1
                
        solver['tries'].append(wsave)
        
        # Calcul de la prochaine proposition
        lang = solver['lang']
        optimum = self.score_words_advanced(lang, solver['tries'], solver['wrong'])
        sorted_words = sorted([(w, optimum[w]) for w in optimum], key=itemgetter(1), reverse=True)
        best_word = [w[0].upper() for w in sorted_words][0]
        
        if '-' not in solver['tries'][-1]:
            em = discord.Embed(title="**Wordle** · Fin", description=f"Vous avez réussi, bravo ! Le mot était ainsi `{word.upper()}` !")
            await self.config.user(user).Solver.clear()
            return await ctx.reply(embed=em, mention_author=False)
        
        if wnum < 6:
            em = discord.Embed(title="**Wordle** · Prise en compte de #{wnum}", description=f"Tentative enregistrée !" + "\n" + f"D'après mes calculs, la meilleure proposition pour la prochaine tentative est `{best_word}`")
            em.set_footer(text="Utilisez 'wordle next' pour rentrer la prochaine étape !")
            await self.config.user(user).Solver.set(solver)
            return await ctx.reply(embed=em, mention_author=False)
        else:
            em = discord.Embed(title="**Wordle** · Fin", description=f"Dommage ! Il semblerait que la partie se soit terminée avec un échec. A la prochaine !")
            em.set_footer(text="Utilisez 'wordle start' pour retenter la prochaine fois !")
            await self.config.user(user).Solver.clear()
            return await ctx.reply(embed=em, mention_author=False)