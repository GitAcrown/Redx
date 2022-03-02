import logging
import random
import requests
from requests.utils import quote
from fuzzywuzzy import process, fuzz

import discord
from datetime import datetime

from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from tabulate import tabulate

import aiohttp
import whapi

logger = logging.getLogger("red.RedX.Fetcher")

class Fetcher(commands.Cog):
    """Diverses API pour le fun"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_global = {
            'ScreenShotLayerKey': ''
        }
        self.config.register_global(**default_global)
        
        self.session = aiohttp.ClientSession()
        
        
# MUGSHOTS ==============================================================    
    
    def jailbase_sources(self):
        sources = "https://www.jailbase.com/api/1/sources/"
        data = requests.get(sources)
        if data.status_code == 200:
            records = data.json()['records']
            return [r['source_id'] for r in records]
        return None
        
    @commands.group(name='mugshot', invoke_without_command=True)
    async def mugshots(self, ctx, source: str = None):
        """Obtenir des mugshots de réels prisonniers américain (par défaut cherche dans les plus récents)
        
        Données provenant de JailBase.com"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.recent_mugshot, source=source)

    @mugshots.command(name='recent')
    async def recent_mugshot(self, ctx, source: str = None):
        """Obtenir les mugshots récents des prisonniers provenant d'une source donnée
        
        Si aucune source n'est sélectionnée, vous obtiendrez des mugshots d'une source au hasard"""
        sources = self.jailbase_sources()
        if not sources:
            return await ctx.reply("**API Hors-ligne** · Il est impossible de récupérer les sources de mugshot, réessayez plus tard")
        
        if not source or source == '':
            source = random.choice(sources)
        else:
            source = source.lower()
            if source not in sources:
                return await ctx.reply("**Source invalide** · Utilisez `;mugshot sources` pour avoir une liste des sources de mugshot disponibles")
            
        embeds = []
        async with ctx.typing():
            getms = requests.get(f"http://www.jailbase.com/api/1/recent/?source_id={source}")
                
            if getms.status_code != 200:
                return await ctx.reply(f"**Source hors-ligne** · Il est impossible de récupérer de mugshots de `{source}`, réessayez plus tard")
            try:
                data = getms.json()
            except:
                return await ctx.reply("**Aucun Mugshot disponible** · Cette source n'offre pas de mugshot récent actuellement")
            
            if data['status'] != 1:
                return await ctx.reply("**Aucun Mugshot disponible** · Cette source n'offre pas de mugshot récent actuellement")
            
            mugshots = data['records']
            n = 1
            for ms in mugshots:
                em = discord.Embed(title=f"{ms['name']}", color=await ctx.embed_color())
                date = datetime.now().strptime(ms['book_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                em.set_image(url=ms['mugshot'])
                em.add_field(name="Enregistré le", value=box(date))
                if ms['charges']:
                    charges = '\n'.join([f"{ms['charges'].index(c) + 1}. {c}" for c in ms['charges']])
                    em.add_field(name="Inculpé.e de [EN]", value=box(charges))
                else:
                    em.add_field(name="Inculpé.e de [EN]", value=box('Vide'))
                em.set_footer(text=f"{n}/{len(mugshots)} · {data['jail']['city']}, {data['jail']['state']} ({source})")
                n += 1
                embeds.append(em)
            
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply("**Aucun Mugshot disponible** · Cette source n'offre pas de mugshot récent actuellement")
        
    @mugshots.command(name='search')
    async def search_mugshot(self, ctx, lastname: str, source: str = None):
        """Rechercher un nom dans la source désirée
        
        Si aucune source n'est sélectionnée, vous obtiendrez des mugshots d'une source au hasard"""
        sources = self.jailbase_sources()
        if not sources:
            return await ctx.reply("**API Hors-ligne** · Il est impossible de récupérer les sources de mugshot, réessayez plus tard")
        
        if not source or source == '':
            source = random.choice(sources)
        else:
            source = source.lower()
            if source not in sources:
                return await ctx.reply("**Source invalide** · Utilisez `;mugshot sources` pour avoir une liste des sources de mugshot disponibles")
            
        embeds = []
        async with ctx.typing():
            getms = requests.get(f"https://www.jailbase.com/api/1/search/?source_id={source}&last_name={lastname}")
                
            if getms.status_code != 200:
                return await ctx.reply(f"**Source hors-ligne** · Il est impossible de récupérer de mugshots de `{source}`, réessayez plus tard")
            try:
                data = getms.json()
            except:
                return await ctx.reply(f"**Aucun Mugshot disponible** · La recherche n'a rien donné pour la source `{source}`")
            
            if data['status'] != 1:
                return await ctx.reply(f"**Aucun Mugshot disponible** · La recherche n'a rien donné pour la source `{source}`")
            
            mugshots = data['records']
            n = 1
            for ms in mugshots:
                em = discord.Embed(title=f"{ms['name']}", color=await ctx.embed_color())
                date = datetime.now().strptime(ms['book_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                em.set_image(url=ms['mugshot'])
                em.add_field(name="Enregistré le", value=box(date))
                if ms['charges']:
                    charges = '\n'.join([f"{ms['charges'].index(c) + 1}. {c}" for c in ms['charges']])
                    em.add_field(name="Inculpé.e de [EN]", value=box(charges))
                else:
                    em.add_field(name="Inculpé.e de [EN]", value=box('Vide'))
                if ms['details']:
                    details = '\n'.join([f"{c[0].upper()} : {c[1]}" for c in ms['details']])
                    em.add_field(name="Détails [EN]", value=box(details))
                em.set_footer(text=f"{n}/{len(mugshots)} · {ms['county_state']} ({source})")
                n += 1
                embeds.append(em)
            
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply(f"**Aucun Mugshot disponible** · La recherche n'a rien donné pour la source `{source}`")
            
    @mugshots.command(name='sources')
    async def sources_mugshot(self, ctx, *, search: str = None):
        """Obtenir ou effectuer une recherche dans la liste des sources de mugshots"""
        if not search:
            return await ctx.reply(f"**Liste des sources de mugshot disponibles** · <https://www.jailbase.com/api/#sources_list>")
        
        url = "https://www.jailbase.com/api/1/sources/"
        data = requests.get(url)
        if data.status_code != 200:
            return await ctx.reply(f"**Sources indisponibles** · Impossible de récupérer une liste à jour des sources disponibles")
        try:
            sources = data.json()['records']
        except:
            return await ctx.reply(f"**Sources indisponibles** · Impossible d'extraire une liste à jour des sources disponibles")
        
        async with ctx.typing():
            norm_sources = []
            for s in sources:
                city = s.get('city', '')
                state = s.get('state_full', '')
                county = s.get('name', '')
                norm_sources.append((s['source_id'], f"{city + ', ' if city else ''}{county}{' (' + state + ')'}"))
        
        output = process.extractBests(search, [i[1] for i in norm_sources], limit=10, scorer=fuzz.partial_token_sort_ratio)
        if not output:
            return await ctx.reply(f"**Aucun résultats** · La recherche dans les sources n'a pas donné de résultats")
        
        tabl = []
        for src in norm_sources:
            if src[1] in [o[0] for o in output]:
                tabl.append(src)
        
        if tabl:
            txt = box('\n'.join([f"{t[0]} · {t[1]}" for t in tabl[::-1]]))
            em = discord.Embed(title=f"Recherche dans les sources · *{search}*", description=txt, color=await ctx.embed_color())
            em.set_footer(text="Utilisez l'ID désiré avec votre commande pour consulter la source correspondante")
            await ctx.reply(embed=em, mention_author=False)
        else:
            await ctx.reply(f"**Aucun résultats** · La recherche dans les sources n'a pas donné de résultats")

    
    @commands.command(name="quote")
    @commands.cooldown(1, 900, commands.BucketType.member)
    async def inspirobot_quote(self, ctx):
        """Obtenir une citation générée par l'IA d'Inspirobot.me
        
        Vous devez attendre 15m entre deux demandes"""
        async def fetch_inspirobot_quote():
            try:
                async with self.session.request("GET", "http://inspirobot.me/api?generate=true") as page:
                    pic = await page.text(encoding="utf-8")
                    return pic
            except Exception as e:
                return None
            
        img = await fetch_inspirobot_quote()
        if not img:
            return await ctx.reply("**Erreur** · Impossible d'obtenir une citation depuis Inspirobot")
        em = discord.Embed(color=ctx.author.color)
        em.set_image(url=img)
        em.set_footer(text="Inspirobot.me", icon_url='https://inspirobot.me/website/images/inspirobot-dark-green.png')
        await ctx.reply(embed=em, mention_author=False)
        
    
    @commands.group(name='wikihow', aliases=['wh'], invoke_without_command=True)
    async def wikihow_commands(self, ctx):
        """Commandes exploitant les données du site WikiHow"""
        
    @wikihow_commands.command(name="shuffle")
    @commands.cooldown(1, 900, commands.BucketType.member)
    async def wikihow_suffle(self, ctx):
        """Obtenir un mélange d'un titre d'un article avec une image aléatoire issue de WikiHow
        
        Vous devez attendre 15m entre deux demandes"""
        async with ctx.typing():
            secu = 1
            while True:
                f1, f2 = whapi.random_article(2)
                hwtitle = '**How to** ' + whapi.return_details(f1)['title']
                try:
                    images = whapi.get_images(f2)
                    break
                except:
                    secu += 1
                    if secu == 3:
                        return await ctx.reply("**Erreur** · Impossible d'obtenir les données depuis WikiHow")
                
            em = discord.Embed(title=hwtitle, color=ctx.author.color)
            em.set_image(url=random.choice(images))
            em.set_footer(text="Shuffle · wikiHow", icon_url=self.bot.user.avatar_url)
        await ctx.reply(embed=em, mention_author=False)
            
    @wikihow_commands.command(name="random")
    @commands.cooldown(1, 900, commands.BucketType.member)
    async def wikihow_random_article(self, ctx):
        """Obtenir un article aléatoire WikiHow
        
        Vous devez attendre 15m entre deux demandes"""
        async with ctx.typing():
            artid = whapi.random_article()
            details = whapi.return_details(artid)
            
            em = discord.Embed(title='**How to** ' + details['title'], url=details['url'], color=ctx.author.color)
            em.description = whapi.parse_intro(artid)
            em.set_footer(text="Random · wikiHow", icon_url=self.bot.user.avatar_url)
            
            try:
                images = whapi.get_images(artid)
                if images:
                    em.set_image(url=images[0])
            except:
                pass
            
        await ctx.reply(embed=em, mention_author=False)
            