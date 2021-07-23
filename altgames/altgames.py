import asyncio
import logging
import random

import discord

from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate

logger = logging.getLogger("red.RedX.AltGames")

class AltGames(commands.Cog):
    """Mini-jeux d'origine de l'économie virtuelle AltEco"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {}

        default_guild = {}
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        
    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def slot(self, ctx, mise: int = None):
        """Jouer à la machine à sous (3 niveaux)

        `Niv. 1` : 5 - 100 crédits
        `Niv. 2` : 101 - 500 crédits
        `Niv. 3` : 501 - 1000 crédits"""
        author = ctx.author
        eco = self.bot.get_cog("AltEco")
        curr = await eco.get_currency(ctx.guild)

        if not mise:
            tbl = [[("🍒", "x2", "Mise + 50"),
                   ("🍒", "x3", "Mise x3"),
                   ("🍀", "x2", "Mise + 200"),
                   ("🍀", "x3", "Mise x5"),
                   ("💎", "x2", "Mise x10"),
                   ("💎", "x3", "Mise x20"),
                   ("⚡", "<3", "Mise perdue"),
                   ("⚡", "x3", "Mise x30")],
                   
                   [("🍒", "x3", "Mise + 250"),
                   ("🍒", "x4", "Mise x5"),
                   ("🍀", "x3", "Mise + 1000"),
                   ("🍀", "x4", "Mise x10"),
                   ("💎", "x3", "Mise x15"),
                   ("💎", "x4", "Mise x30"),
                   ("⚡", "<4", "Mise perdue"),
                   ("⚡", "x4", "Mise x60")],
                   
                   [("🍒", "x3", "Mise + 500"),
                   ("🍒", "x4", "Mise x5"),
                   ("🍒", "x5", "Mise x10"),
                   ("🍀", "x3", "Mise + 5000"),
                   ("🍀", "x4", "Mise x10"),
                   ("🍀", "x5", "Mise x20"),
                   ("💎", "x4", "Mise x25"),
                   ("💎", "x5", "Mise x50"),
                   ("⚡", "<5", "Mise perdue"),
                   ("⚡", "x5", "Mise x100")]]
            em = discord.Embed(title="Tableau des gains",
                               color=await ctx.embed_color(), inline=False)
            em.add_field(name="Niveau 1 (5 - 100 crédits)", value=box(tabulate(tbl[0], headers=("Emoji", "Nb.", "Gain"))), inline=False)
            em.add_field(name="Niveau 2 (101 - 500 crédits)", value=box(tabulate(tbl[1])), inline=False)
            em.add_field(name="Niveau 3 (501 - 1000 crédits)", value=box(tabulate(tbl[2])), inline=False)
            em.set_footer(text=f"🍒 = Même fruit")
            return await ctx.send(embed=em)
        
        if not await eco.check_balance(author, mise):
            return await ctx.reply("**Solde insuffisant** • Vous n'avez pas cette somme sur votre compte")
        
        if 5 <= mise <= 100:
            async with ctx.channel.typing():
                delta = 0

                col = ["🍎", "🍊", "🍋", "🍒", "🍉", "⚡", "💎", "🍀"]
                fruits = ["🍎", "🍊", "🍋", "🍒", "🍉"]
                col = col[-3:] + col + col[:3]
                cols = []
                mid = []
                for i in range(3):
                    n = random.randint(3, 10)
                    cols.append((col[n-1], col[n], col[n+1]))
                    mid.append(col[n])

                aff = "{a[0]}|{b[0]}|{c[0]}\n" \
                        "{a[1]}|{b[1]}|{c[1]} <= \n" \
                        "{a[2]}|{b[2]}|{c[2]}".format(a=cols[0], b=cols[1], c=cols[2])

                count = lambda e: mid.count(e)

                def fruitcount():
                    for f in fruits:
                        if count(f) >= 2:
                            return count(f)
                    return 0

                if count("⚡") == 3:
                    delta = mise * 30
                    txt = "3x ⚡ · Vous gagnez {}"
                elif count("⚡") in (1, 2):
                    txt = "Zap ⚡ · Vous perdez votre mise"
                elif count("💎") == 3:
                    delta = mise * 20
                    txt = "3x 💎 · Vous gagnez {}"
                elif count("💎") == 2:
                    delta = mise * 10
                    txt = "2x 💎 · Vous gagnez {}"
                elif count("🍀") == 3:
                    delta = mise * 5
                    txt = "3x 🍀 · Vous gagnez {}"
                elif count("🍀") == 2:
                    delta = mise + 200
                    txt = "2x 🍀 · Vous gagnez {}"
                elif fruitcount() == 3:
                    delta = mise * 3
                    txt = "3x fruit · Vous gagnez {}"
                elif fruitcount() == 2:
                    delta = mise + 50
                    txt = "2x fruit · Vous gagnez {}"
                else:
                    txt = "Rien · Vous perdez votre mise"

                await asyncio.sleep(1)

                ope = delta - mise
                if ope > 0:
                    await eco.deposit_credits(author, ope, reason="Gain à la Machine à sous")
                elif ope < 0:
                    await eco.withdraw_credits(author, mise, reason="Perte à la Machine à sous")

            em = discord.Embed(description=f"**Mise :** {mise}{curr}\n" + box(aff), color=author.color)
            em.set_author(name="🎰 N1 · " + str(author), icon_url=author.avatar_url)
            em.set_footer(text=txt.format(f"{delta} {curr}"))
            await ctx.send(embed=em)
            
        elif 101 <= mise <= 500:
            async with ctx.channel.typing():
                delta = 0

                col = ["🍎", "🍊", "🍋", "🍒", "🍉", "⚡", "💎", "🍀"]
                fruits = ["🍎", "🍊", "🍋", "🍒", "🍉"]
                col = col[-3:] + col + col[:3]
                cols = []
                mid = []
                for i in range(4):
                    n = random.randint(3, 10)
                    cols.append((col[n-1], col[n], col[n+1]))
                    mid.append(col[n])

                aff = "{a[0]}|{b[0]}|{c[0]}|{d[0]}\n" \
                        "{a[1]}|{b[1]}|{c[1]}|{d[1]} <= \n" \
                        "{a[2]}|{b[2]}|{c[2]}|{d[2]}".format(a=cols[0], b=cols[1], c=cols[2], d=cols[3])

                count = lambda e: mid.count(e)

                def fruitcount():
                    for f in fruits:
                        if count(f) >= 2:
                            return count(f)
                    return 0

                if count("⚡") == 4:
                    delta = mise * 60
                    txt = "4x ⚡ · Vous gagnez {}"
                elif count("⚡") in (1, 2, 3):
                    txt = "Zap ⚡ · Vous perdez votre mise"
                elif count("💎") == 4:
                    delta = mise * 30
                    txt = "4x 💎 · Vous gagnez {}"
                elif count("💎") == 3:
                    delta = mise * 15
                    txt = "3x 💎 · Vous gagnez {}"
                elif count("🍀") == 4:
                    delta = mise * 10
                    txt = "4x 🍀 · Vous gagnez {}"
                elif count("🍀") == 3:
                    delta = mise + 1000
                    txt = "3x 🍀 · Vous gagnez {}"
                elif fruitcount() == 4:
                    delta = mise * 5
                    txt = "4x fruit · Vous gagnez {}"
                elif fruitcount() == 3:
                    delta = mise + 250
                    txt = "3x fruit · Vous gagnez {}"
                else:
                    txt = "Rien · Vous perdez votre mise"

                await asyncio.sleep(1)

                ope = delta - mise
                if ope > 0:
                    await eco.deposit_credits(author, ope, reason="Gain à la Machine à sous")
                elif ope < 0:
                    await eco.withdraw_credits(author, mise, reason="Perte à la Machine à sous")

            em = discord.Embed(description=f"**Mise :** {mise}{curr}\n" + box(aff), color=author.color)
            em.set_author(name="🎰 N2 · " + str(author), icon_url=author.avatar_url)
            em.set_footer(text=txt.format(f"{delta} {curr}"))
            await ctx.send(embed=em)
            
        elif 501 <= mise <= 1000:
            async with ctx.channel.typing():
                delta = 0

                col = ["🍎", "🍊", "🍋", "🍒", "🍉", "⚡", "💎", "🍀"]
                fruits = ["🍎", "🍊", "🍋", "🍒", "🍉"]
                col = col[-3:] + col + col[:3]
                cols = []
                mid = []
                for i in range(5):
                    n = random.randint(3, 10)
                    cols.append((col[n-1], col[n], col[n+1]))
                    mid.append(col[n])

                aff = "{a[0]}|{b[0]}|{c[0]}|{d[0]}|{e[0]}\n" \
                        "{a[1]}|{b[1]}|{c[1]}|{d[1]}|{e[1]} <= \n" \
                        "{a[2]}|{b[2]}|{c[2]}|{d[2]}|{e[2]}".format(a=cols[0], b=cols[1], c=cols[2], d=cols[3], e=cols[4])

                count = lambda e: mid.count(e)

                def fruitcount():
                    for f in fruits:
                        if count(f) >= 2:
                            return count(f)
                    return 0

                if count("⚡") == 5:
                    delta = mise * 100
                    txt = "5x ⚡ · Vous gagnez {}"
                elif count("⚡") in (1, 2, 3, 4):
                    txt = "Zap ⚡ · Vous perdez votre mise"
                elif count("💎") == 5:
                    delta = mise * 50
                    txt = "5x 💎 · Vous gagnez {}"
                elif count("💎") == 4:
                    delta = mise * 25
                    txt = "4x 💎 · Vous gagnez {}"
                elif count("🍀") == 5:
                    delta = mise * 20
                    txt = "5x 🍀 · Vous gagnez {}"
                elif count("🍀") == 4:
                    delta = mise * 10
                    txt = "4x 🍀 · Vous gagnez {}"
                elif count("🍀") == 3:
                    delta = mise + 5000
                    txt = "3x 🍀 · Vous gagnez {}"
                elif fruitcount() == 5:
                    delta = mise * 10
                    txt = "5x fruit · Vous gagnez {}"
                elif fruitcount() == 4:
                    delta = mise * 5
                    txt = "4x fruit · Vous gagnez {}"
                elif fruitcount() == 3:
                    delta = mise + 500
                    txt = "3x fruit · Vous gagnez {}"
                else:
                    txt = "Rien · Vous perdez votre mise"

                await asyncio.sleep(1)

                ope = delta - mise
                if ope > 0:
                    await eco.deposit_credits(author, ope, reason="Gain à la Machine à sous")
                elif ope < 0:
                    await eco.withdraw_credits(author, mise, reason="Perte à la Machine à sous")

            em = discord.Embed(description=f"**Mise :** {mise}{curr}\n" + box(aff), color=author.color)
            em.set_author(name="🎰 N3 · " + str(author), icon_url=author.avatar_url)
            em.set_footer(text=txt.format(f"{delta} {curr}"))
            await ctx.send(embed=em)
        else:
            await ctx.send(f"**Mise invalide** • Elle doit être comprise entre 5 et 1000{curr} (en fonction du niveau désiré)")
    
    @commands.command(aliases=["des"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def dices(self, ctx, mise: int):
        """Avez vous plus ou moins que la somme des dés tirés ?

        Vous devez deviner si vous aurez plus ou moins en additionnant vos deux lancés.
        Si les scores sont identiques avec le bot, vous êtes remboursé.

        Mise minimale de 10 crédits et maximale de 200"""
        author = ctx.author
        eco = self.bot.get_cog("AltEco")
        curr = await eco.get_currency(ctx.guild)

        if 10 <= mise <= 200:
            if await eco.check_balance(author, mise):

                def affem(userval, botval, footer):
                    em = discord.Embed(color=author.color)
                    em.set_author(name="🎲 · " + str(author), icon_url=author.avatar_url)
                    em.add_field(name="Vous", value=userval)
                    em.add_field(name=self.bot.user.name, value=botval)
                    em.set_footer(text=footer)
                    return em

                async with ctx.channel.typing():
                    user_dices = [random.randint(1, 6), random.randint(1, 6)]
                    bot_dices = [random.randint(1, 6), random.randint(1, 6)]
                    await asyncio.sleep(1.5)

                    before = affem(box(f"🎲 {user_dices[0]} "), box(f"🎲 {bot_dices[0]} "),
                                   "Allez-vous avoir plus ou moins que moi avec le prochain lancé ?")

                msg = await ctx.send(embed=before)
                emojis = ["➕", "➖"]

                start_adding_reactions(msg, emojis)
                try:
                    react, user = await self.bot.wait_for("reaction_add",
                                                          check=lambda r, u: u == ctx.author and r.message.id == msg.id,
                                                          timeout=30)
                except asyncio.TimeoutError:
                    emoji = random.choice(emojis)
                else:
                    emoji = react.emoji

                if sum(user_dices) == sum(bot_dices):
                    after = affem(box(f"🎲 {user_dices[0]}, {user_dices[1]} "),
                                  box(f"🎲 {bot_dices[0]}, {bot_dices[1]} "),
                                  "Egalité ! Vous ne perdez pas votre mise")
                    return await msg.edit(embed=after)

                if emoji == "➕":
                    if sum(user_dices) > sum(bot_dices):
                        mise = round(mise/2)
                        await eco.deposit_credits(author, mise, reason="Gain aux dés")
                        after = affem(box(f"🎲 {user_dices[0]}, {user_dices[1]} "),
                                  box(f"🎲 {bot_dices[0]}, {bot_dices[1]} "),
                                      f"Gagné ! Vous gagnez {mise} {curr}")
                        await msg.edit(embed=after)
                    else:
                        await eco.withdraw_credits(author, mise, reason="Perte aux dés")
                        after = affem(box(f"🎲 {user_dices[0]}, {user_dices[1]} "),
                                  box(f"🎲 {bot_dices[0]}, {bot_dices[1]} "),
                                      f"Perdu ! Vous avez perdu votre mise")
                        await msg.edit(embed=after)
                else:
                    if sum(user_dices) < sum(bot_dices):
                        mise = round(mise / 2)
                        await eco.deposit_credits(author, mise, reason="Gain aux dés")
                        after = affem(box(f"🎲 {user_dices[0]}, {user_dices[1]} "),
                                  box(f"🎲 {bot_dices[0]}, {bot_dices[1]} "),
                                      f"Gagné ! Vous gagnez {mise} {curr}")
                        await msg.edit(embed=after)
                    else:
                        await eco.withdraw_credits(author, mise, reason="Perte aux dés")
                        after = affem(box(f"🎲 {user_dices[0]}, {user_dices[1]} "),
                                  box(f"🎲 {bot_dices[0]}, {bot_dices[1]} "),
                                      f"Perdu ! Vous avez perdu votre mise")
                        await msg.edit(embed=after)
            else:
                await ctx.send("**Fonds insuffisants** • Vous n'avez pas cette somme sur votre compte")
        else:
            await ctx.send(f"**Mise invalide** • Elle doit être comprise entre 10 et 200 {curr}")

