import logging
import random

import discord

from redbot.core import commands

logger = logging.getLogger("red.RedX.Toolkit")


class Toolkit(commands.Cog):
    """Set d'outils utiles pour une communauté"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        
    @commands.command(name="dice", aliases=['die'])
    async def random_numbers(self, ctx, *dice):
        """Lance un ou plusieurs dés
        
        Si vous voulez lancer plusieurs dés, vous pouvez séparer les instructions par un espace, ex. `;dice 10 20 50-100` lancera un d10, d20 et un dé entre 50 et 100
        
        **__Formatage des dés :__**
        `X` = Lancer un dé comprenant les nombres entre 0 et X, ex. `;dice 20`
        `W:X` = Lancer un dé comprenant les nombres entre entre W et X, ex. `;dice 10:99`
        `[...]*P` = Définir le pas du dé qui précède `*`, ex. `;dice 100*5`
        `N![...]` = Lancer N fois le dé après `!`, ex. `;dice 3!20` `;dice 2!10:60`
        
        **Exemples de commandes**
        `;dice 2!20 100` lancera deux d20 et un d100
        `;dice 20:40*10` lancera un d[20-40] avec un pas de 10 (ne peut donner que les valeurs 20/30/40)
        `;dice 10 10 10 | ;dice 3!10` lancera trois d10
        `;dice 5!10:90*5` lancera un d[10-90] avec un pas de 5"""
        text = []
        for die in dice:
            if die.count('!') > 1 or die.count('*') > 1 or die.count(':') > 1:
                text.append(f'`{die}` · ???')
                continue
            
            n, p = 1, 1
            start, end = 0, 10
            if '!' in die:
                n, die = die.split('!', 1)
            
            if n > 1:
                sn = n
                while n >= 1:
                    if '*' in die:
                        die, p = die.split('*', 1)
                    if ':' in die:
                        start, end = die.split(':', 1)
                    
                    try:
                        start, end = int(start), int(end)
                    except:
                        text.append(f'`{die}` #{sn-n+1} · ???')
                        continue
                    
                    if not p:
                        result = random.randint(start, end)
                    else:
                        result = random.choice(range(start, end, p))
                    text.append(f'`{die}` #{sn-n+1} · {result}')
                    n -= 1
            else:
                if '*' in die:
                    die, p = die.split('*', 1)
                if ':' in die:
                    start, end = die.split(':', 1)
                
                try:
                    start, end = int(start), int(end)
                except:
                    text.append(f'`{die}` · ???')
                    continue
                
                if not p:
                    result = random.randint(start, end)
                else:
                    result = random.choice(range(start, end, p))
                text.append(f'`{die}` · {result}')
            
        if not text:
            return await ctx.reply("Vos dés sont invalides ou n'ont pu être lancés", mention_author=False)
        
        em = discord.Embed(description='\n'.join(text), color=ctx.author.color)
        return await ctx.reply(embed=em, mention_author=False)