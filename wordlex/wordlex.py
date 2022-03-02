import logging
import asyncio
import random
from os import name
import time
from datetime import datetime
from operator import itemgetter
from copy import copy
from io import StringIO

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
            for l in set(w):
                lscore[l] = lscore.get(l, 0) + 1
        
        return lscore

    def score_words(self, lang: str, wordlist: list = None, first: bool = False, letter_balance: dict = None) -> dict:
        """Calcule un score des mots disponibles en fonction de l'apparition des lettres dans la langue séléctionnée"""
        if not wordlist:
            try:
                wordlist = self.words[lang.lower()]
            except:
                raise KeyError(f"La langue '{lang}' n'est pas disponible")
        
        lscore = self.most_used_letters(lang)
        if letter_balance:
            for l in letter_balance:
                if l in lscore:
                    lscore[l] = round(lscore[l] * (0.80 ** letter_balance[l]))
            
        wscore = {}
        for w in wordlist:
            wscore[w] = sum([lscore[l] for l in list(set(w))]) if first else sum([lscore[l] for l in w])
        
        return wscore
    
    def score_words_advanced(self, lang: str, tries: list, wrong_letters: list, words_tested: list) -> dict:
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
        
        wordlist = [w for w in wordlist if w not in words_tested]
        wordlist = [w for w in wordlist if not [l for l in w if l in wrong_letters]]
                    
        wlcache = copy(wordlist)
        for w in wlcache: # Lettres majs
            for x, y in zip(w, combi_try):
                if y == '-':
                    pass
                elif x.upper() != y:
                    wordlist.remove(w)
                    break
        
        for tr in [t for t in tries if [l for l in t if l.islower()]]: # Lettres minuscules
            wlcache = copy(wordlist)
            for w in wlcache: 
                for x, y in zip(w, tr):
                    if y == '-' or y.isupper():
                        pass
                    elif x.lower() == y:
                        wordlist.remove(w)
                        break
        
        lower_letters = set([l for wl in tries for l in wl if l.islower()])
        for ll in lower_letters:
            wlcache = copy(wordlist)
            for w in wlcache:
                if ll not in w:
                    wordlist.remove(w)
                    continue
        
        alltries = [l.lower() for w in tries for l in w if l not in ('-', '.')]
        llcount = {s: alltries.count(s) for s in set(alltries)}
                    
        return self.score_words(lang, wordlist, letter_balance=llcount)
    

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
            'wrong': [],
            'words_tested': []
        }
        
        start_words = self.score_words(lang, first=True)
        sorted_words = sorted([(w, start_words[w]) for w in start_words], key=itemgetter(1), reverse=True)
        best_words = [w[0].upper() for w in sorted_words][:5]
        
        await self.config.user(user).Solver.set(solver)
        
        em = discord.Embed(title="**Wordle** · Suggestions de mot de départ", description=f"Voici les mots optimaux pour commencer : `{', '.join(best_words)}`")
        em.set_footer(text="Utilisez la commande 'wordle next' pour poursuivre")
        await ctx.reply(embed=em, mention_author=False)
        
    @wordle_solver.command(name="next")
    async def next_solver(self, ctx, mot: str = None):
        """Ajouter des mots au résolveur de Wordle (personnel)
        
        A faire après `wordle start` !"""
        user = ctx.author
        
        solver = await self.config.user(user).Solver()
        if not solver:
            return await ctx.reply(f"**Erreur** · Vous devez d'abord démarrer une session avec `wordle start` !", mention_author=False)

        wnum = len(solver['tries']) + 1
        
        if mot:
            if len(mot) != 5:
                mot = None
        
        if not mot:
            if wnum == 1:
                em = discord.Embed(title="**Wordle** · Mot de départ", description=f"Quel mot de départ avez-vous choisi ?")
                em.set_footer(text="» Indiquez ci-dessous le mot choisi :")
            else:
                em = discord.Embed(title=f"**Wordle** · Tentative #{wnum}", description=f"Quel mot avez-vous choisi ?")
                em.set_footer(text="» Indiquez ci-dessous le mot choisi :")
                
            msg = await ctx.reply(embed=em, mention_author=False)
            
            try:
                wordrep = await self.bot.wait_for('message', timeout=30, check=lambda m: m.author == user and len(m.content) == 5)
            except asyncio.TimeoutError:
                await msg.delete(delay=5)
                return await ctx.reply(f"**Session expirée** · Relancez la commande quand vous voudrez soumettre vos choix et résultats Wordle", mention_author=False)
            
            word = wordrep.content.lower()
        else:
            word = mot.lower()
        
        em = discord.Embed(title=f"**Wordle** · Résultat de #{wnum}", description=f"Indiquez le résultat de cette tentative : **{word.upper()}**" + "\n\n" + f"`{word[0].lower()}` Lettre minuscule si lettre en mauvaise position (orange)" + "\n"+ f"`{word[0].upper()}` Lettre majuscule si lettre en bonne position (vert)" + "\n" + "`- ou .` Si mauvaise lettre (gris)")
        em.set_footer(text="» Indiquez ci-dessous le résultat :")
            
        msg = await ctx.reply(embed=em, mention_author=False)
        
        try:
            resultrep = await self.bot.wait_for('message', timeout=120, check=lambda m: m.author == user and len(m.content) == 5)
        except asyncio.TimeoutError:
            await msg.delete(delay=5)
            return await ctx.reply(f"**Session expirée** · Relancez la commande quand vous voudrez soumettre vos choix et résultats Wordle", mention_author=False)
        
        result = resultrep.content
        result = result.replace('.', '-')
        
        for x, y in zip(result, word):
            if x == '-':
                pass
            elif x.lower() != y.lower():
                return await ctx.reply(f"**Erreur** · L'emplacement des lettres indiquées en résultat ne correspondent pas avec celles du mot donné", mention_author=False)
        
        solver['words_tested'].append(word.lower())
        
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
        optimum = self.score_words_advanced(lang, solver['tries'], solver['wrong'], solver['words_tested'])
        sorted_words = sorted([(w, optimum[w]) for w in optimum], key=itemgetter(1), reverse=True)
        best_words = [w[0].upper() for w in sorted_words][:5]
        
        if '-' not in solver['tries'][-1]:
            em = discord.Embed(title="**Wordle** · Fin", description=f"Vous avez réussi, bravo ! Le mot était ainsi `{word.upper()}` !")
            await self.config.user(user).Solver.clear()
            return await ctx.reply(embed=em, mention_author=False)
        
        if wnum < 6:
            em = discord.Embed(title=f"**Wordle** · Prise en compte de #{wnum}", description=f"Tentative enregistrée !" + "\n" + f"D'après mes calculs, les meilleures proposition pour la prochaine tentative sont `{', '.join(best_words)}`")
            em.set_footer(text="Utilisez 'wordle next' pour rentrer la prochaine étape !")
            await self.config.user(user).Solver.set(solver)
            return await ctx.reply(embed=em, mention_author=False)
        else:
            em = discord.Embed(title="**Wordle** · Fin", description=f"Dommage ! Il semblerait que la partie se soit terminée avec un échec. A la prochaine !")
            em.set_footer(text="Utilisez 'wordle start' pour retenter la prochaine fois !")
            await self.config.user(user).Solver.clear()
            return await ctx.reply(embed=em, mention_author=False)
        

    @wordle_solver.command(name="versus")
    @commands.max_concurrency(1, commands.BucketType.user)
    async def play_vs_bot(self, ctx):
        """Jouez contre le bot : il tente de deviner le mot que vous avez en tête (EN)"""
        user = ctx.author
        lang = 'en'
        
        check, cross = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        em = discord.Embed(description="Je ne peux que deviner les mots des listes utilisées par Wordle. Voulez-vous que je vous envoie cette liste ?")
        em.set_footer(text="Recevoir | Passer")
        
        msg = await ctx.reply(embed=em, mention_author=False)
        start_adding_reactions(msg, [check, cross])
        try:
            react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id, timeout=30)
        except asyncio.TimeoutError:
            await msg.delete()
        if react.emoji == cross:
            await msg.delete(delay=2)
        elif react.emoji == check:
            text = '\n'.join(self.words['en'])
            f = StringIO(text)
            await msg.reply(mention_author=False, file=discord.File(f, 'Liste_mots_EN.txt'))
            await msg.delete(delay=10)
        
        em = discord.Embed(description="**__Règles :__**\nJe dois deviner le mot de 5 lettres que vous avez choisi (en anglais) en **6 tentatives**, sinon j'ai perdu. Je compte sur vous pour ne pas tricher et changer de mot en cours de chemin... Sinon...\n" + f"Bref, quand vous aurez choisi votre mot cliquez sur {check} ci-dessous pour démarrer la partie !")
        em.set_footer(text="Cliquez ci-dessous pour continuer (5m)")
        msg = await ctx.reply(embed=em, mention_author=False)
        
        start_adding_reactions(msg, [check])
        try:
            react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id, timeout=300)
        except asyncio.TimeoutError:
            return await ctx.send("**Partie annulée** · Vous avez eu peur de perdre ? Je peux comprendre. A la prochaine !")
        
        propcount = 0
        tries = []
        wrong = []
        words_tested = []
        success = False
        
        def verif_input(result, word):
            for x, y in zip(result, word):
                if x == '-':
                    pass
                elif x.lower() != y.lower():
                    return False
            return True
        
        while propcount <= 6 and not success:
            propcount += 1
            if propcount == 1:
                start_words = self.score_words(lang, first=True)
                sorted_words = sorted([(w, start_words[w]) for w in start_words], key=itemgetter(1), reverse=True)
                best_words = [w[0].upper() for w in sorted_words][:10]
                word = random.choice(best_words)
            else:
                optimum = self.score_words_advanced(lang, tries, wrong, words_tested)
                sorted_words = sorted([(w, optimum[w]) for w in optimum], key=itemgetter(1), reverse=True)
                best_words = [w[0].upper() for w in sorted_words]
                if len(best_words) > 1:
                    word = random.choice(best_words)
                else:
                    word = best_words[0]
                
            prop_ok = False
            while not prop_ok:
                exfmt = ''.join([random.choice((i.upper(), i.lower(), '-')) for i in word])
                rtxt =  f"**Lettre dans le mot + __Bonne place__** = Lettre majuscule `{word[0].upper()}`" + "\n" + f"**Lettre dans le mot + __Mauvaise place__** = Lettre minuscule `{word[0].lower()}`" + "\n" + "**Lettre pas dans le mot** = Tiret ou point (`-` ou `.`)"
                rtxt += "\n" + f"**Exemple :** `{exfmt}`"
                em = discord.Embed(title=f"**Wordle vs. {self.bot.user.name}** · Proposition #{propcount}",
                                description=random.choice((f"Ma proposition est `{word}` !", f"J'ai choisi `{word}` !", f"Partons pour `{word}`.", f"Allons pour `{word}` !")))
                em.add_field(name="Indiquer le résultat", value=rtxt, inline=False)
                em.set_footer(text="» Notez ci-dessous le résultat avec le mot que j'ai donné :")
                
                msg = await ctx.send(embed=em, mention_author=False)
            
                try:
                    resultrep = await self.bot.wait_for('message', timeout=120, check=lambda m: m.author == user and len(m.content) == 5)
                except asyncio.TimeoutError:
                    await msg.delete(delay=5)
                    return await ctx.reply(f"**Session expirée** · Avez-vous abandonné la partie ? Tant pis, à la prochaine !", mention_author=False)
                
                result = resultrep.content
                result = result.replace('.', '-')
                    
                prop_ok = verif_input(result, word)
                if not prop_ok:
                    await resultrep.reply(f"**Erreur** · Les lettres du résultat indiqué ne correspondent pas au mot que j'ai donné, réessayez.", mention_author=False)
                
            words_tested.append(word.lower())
            
            old_combi_try = ['-', '-', '-', '-', '-']
            for t in tries:
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
                    if wtry[i].lower() not in wrong:
                        if wtry[i].upper() not in old_combi_try and wtry[i].upper() not in result.upper():
                            wrong.append(wtry[i].lower())
                elif r == wtry[i].upper():
                    wsave.append(r)
                elif r == wtry[i].lower():
                    wsave.append(r)
                i += 1
                    
            tries.append(wsave)
        
            if word.lower() == result.lower():
                success = True
            else:
                em = discord.Embed(title=f"**Wordle vs. {self.bot.user.name}** · Proposition #{propcount}",
                                    description=random.choice(("Très bien, c'est noté !", "D'accord, je vois...", "Hmm, OK.", "Je vois, je vois...", "Intéressant, je m'attendais pas à ça.")))
                em.set_footer(text="Je réfléchis...")
                await ctx.send(embed=em)
                await asyncio.sleep(random.randint(2, 4))
        
        if propcount > 6:
            em = discord.Embed(title=f"**Wordle vs. {self.bot.user.name}** · Victoire (pour vous)",
                               description="On dirait bien que j'ai perdu... Bien joué. Je ne me laisserai pas faire la prochaine fois !")
        elif success:
            em = discord.Embed(title=f"**Wordle vs. {self.bot.user.name}** · Défaite (pour vous)",
                               description=f"J'ai gagné en **{propcount} propositions** ! Le mot était `{word}` ! Je suis vraiment trop fort. Bon allez, à la prochaine !")
        await ctx.send(embed=em)
        
        