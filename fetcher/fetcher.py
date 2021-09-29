import logging
import random
import requests
from requests.utils import quote

import discord
from datetime import datetime

from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS

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
        
        
# MUGSHOTS ==============================================================    
    
    def jailbase_sources(self):
        sources = "https://www.jailbase.com/api/1/sources/"
        data = requests.get(sources)
        if data.status_code == 200:
            records = data.json()['records']
            return [r['source_id'] for r in records]
        return None
        
    @commands.group(name='mugshot', invoke_without_command=True)
    async def mugshots(self, ctx, source: str = None, lastname: str = None):
        """Obtenir des mugshots de réels prisonniers américain (par défaut cherche dans les plus récents)
        
        Données provenant de JailBase.com"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.get_mugshot, source=source)

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
                em.set_thumbnail(url=ms['mugshot'])
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
            getms = requests.get(f"https://www.jailbase.com/api/1/search/?source_id={source}&last_name={lastname}")
                
            if getms.status_code != 200:
                return await ctx.reply(f"**Source hors-ligne** · Il est impossible de récupérer de mugshots de `{source}`, réessayez plus tard")
            try:
                data = getms.json()
            except:
                return await ctx.reply("**Aucun Mugshot disponible** · La recherche n'a rien donné")
            
            if data['status'] != 1:
                return await ctx.reply("**Aucun Mugshot disponible** · La recherche n'a rien donné")
            
            mugshots = data['records']
            n = 1
            for ms in mugshots:
                em = discord.Embed(title=f"{ms['name']}", color=await ctx.embed_color())
                date = datetime.now().strptime(ms['book_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                em.set_thumbnail(url=ms['mugshot'])
                em.add_field(name="Enregistré le", value=box(date))
                if ms['charges']:
                    charges = '\n'.join([f"{ms['charges'].index(c) + 1}. {c}" for c in ms['charges']])
                    em.add_field(name="Inculpé.e de [EN]", value=box(charges))
                else:
                    em.add_field(name="Inculpé.e de [EN]", value=box('Vide'))
                if ms['details']:
                    details = '\n'.join([f"{c[0].upper()} : {c[1]}" for c in ms['details']])
                    em.add_field(name="Détails [EN]", value=box(details))
                em.set_footer(text=f"{n}/{len(mugshots)} · {ms['countystate']} ({source})")
                n += 1
                embeds.append(em)
            
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply("**Aucun Mugshot disponible** · La recherche n'a rien donné")
            
    @mugshots.command(name='sources')
    async def sources_mugshot(self, ctx):
        """Obtenir la liste des sources de mugshots"""
        await ctx.reply(f"**Liste des sources de mugshot disponibles** · <https://www.jailbase.com/api/#sources_list>")
        
    @commands.command(name='webscreen')
    async def screenshot_website(self, ctx, url: str):
        """Renvoie un screen de la page web demandée
        
        Limité à 100 pages par mois et 2 par minute"""
        key = await self.config.ScreenShotLayerKey()
        encoded = quote(url, safe='')
        r = f"http://api.screenshotlayer.com/api/capture?access_key={key}&url={encoded}&viewport=1440x900&fullpage=1"
        async with ctx.typing():
            getdata = requests.get(r)
        if str(getdata.content).startswith("b'{"):
            error = getdata.json()['error']['type']
            return await ctx.reply(f"**Erreur avec l'API** · `{error}`")
        
        em = discord.Embed(description=f'Screenshot de `{url}`', timestamp=ctx.message.created_at)
        em.set_image(url=r)
        await ctx.reply(embed=em, mention_author=False)
        
    @commands.group(name="fetcherset")
    @checks.is_owner()
    async def fetcher_settings(self, ctx):
        """Paramètres de propriétaire Fetcher"""
        
    @fetcher_settings.command(name="screenapikey")
    async def set_screenshot_api_key(self, ctx, key: str):
        """Change la clef utilisée pour l'api ScreenShotLayer"""
        await self.config.ScreenShotLayerKey.set(key)
        await ctx.send("**Clef modifiée** · La clef donnée sera désormais utilisée pour l'API de ScreenshotLayer")
            