import asyncio
import logging
import random
import requests

import discord
import json
from datetime import datetime

from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS

logger = logging.getLogger("red.RedX.Fetcher")

class Fetcher(commands.Cog):
    """Diverses API pour le fun"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_global = {}
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
    async def get_mugshot(self, ctx, source: str = None):
        """Obtenir des mugshots de réels prisonniers américain (par défaut cherche dans les plus récents)
        
        Données provenant de JailBase.com"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.recent_mugshot, source=source)

    @get_mugshot.command(name='recent')
    async def recent_mugshot(self, ctx, source: str = None):
        """Obtenir les mugshots des prisonniers récents provenant d'une source donnée
        
        Si aucune source n'est sélectionnée, vous obtiendrez des mugshots d'une source au hasard"""
        sources = self.jailbase_sources()
        if not sources:
            return await ctx.reply("**API Hors-ligne** · Il est impossible de récupérer les sources de mugshot, réessayez plus tard")
        if source:
            source = source.lower()
            if source not in sources:
                return await ctx.reply("**Source invalide** · Utilisez `;mugshot sources` pour avoir une liste des sources de mugshot disponibles")
        else:
            source = random.choice(sources)
        
        embeds = []
        async with ctx.typing():
            getms = requests.get(f"http://www.jailbase.com/api/1/recent/?source_id={source}")
            if getms.status_code != 200:
                await ctx.reply(f"**Source hors-ligne** · Il est impossible de récupérer de mugshots de `{source}`, réessayez plus tard")
            data = getms.json()
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
            
    @get_mugshot.command(name='sources')
    async def sources_mugshot(self, ctx):
        """Obtenir la liste des sources de mugshots"""
        await ctx.reply(f"**Liste des sources de mugshot disponibles** · <https://www.jailbase.com/api/#sources_list>")