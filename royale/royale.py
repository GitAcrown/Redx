import asyncio
import logging
import random
import time
from io import BytesIO

import discord
from discord.errors import DiscordException
import aiohttp
from PIL import Image, ImageSequence, ImageOps
import wand
import wand.color
import wand.drawing

from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate
from redbot.core.data_manager import cog_data_path, bundled_data_path

logger = logging.getLogger("red.RedX.Royale")

RoyaleColor = 0xFFC107

class RoyalePlayer:
    def __init__(self, user: discord.Member, champion_data: dict):
        self.user, self.guild = user, user.guild
        self.data = champion_data
        
        self.status = 1
        self.hp = 100
        self.armor = 0
                
    def __str__(self):
        return f'**{self.user.display_name}**'

class Royale(commands.Cog):
    """Battle Royale sur Discord"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {
            'Champion': {}
        }

        default_guild = {
            'MaxPlayers' : 8,
            'TimeoutDelay' : 120,
            'TicketPrice' : 50
        }
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

        self.cache = {}
        self.image_mimes = ["image/png", "image/pjpeg", "image/jpeg", "image/x-icon"]
        self.gif_mimes = ["image/gif"]
        
        
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
        
        
    # Avatars Mods
    
    async def bytes_download(self, url: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        mime = resp.headers.get("Content-type", "").lower()
                        b = BytesIO(data)
                        b.seek(0)
                        return b, mime
                    else:
                        return False, False
        except asyncio.TimeoutError:
            return False, False
        except Exception:
            logger.error(
                "Impossible de télécharger en bytes-like", exc_info=True)
            return False, False
        
    def apply_layer(self, b, layer_path, wm_gif=False):
        final = BytesIO()
        rscale = 100
        x, y = 0, 0
        transparency = 0
        
        with wand.image.Image(file=b) as img:
            is_gif = len(getattr(img, "sequence")) > 1
            if not is_gif and not wm_gif:
                logger.debug("Aucun gif")
                with img.clone() as new_img:
                    new_img.transform(resize="250000@")
                    with wand.image.Image(filename=layer_path) as wm:
                        wm.transform(resize=f"{round(new_img.width * rscale)}x{round(new_img.height * rscale)}")
                        new_img.watermark(
                            image=wm, left=x, top=y
                        )
                    new_img.save(file=final)

            elif is_gif and not wm_gif:
                logger.debug("L'image de base est un gif")
                    
                with wand.image.Image(filename=layer_path) as wm:
                    with wand.image.Image() as new_image:
                        with img.clone() as new_img:
                            wm.transform(
                                resize=f"{round(new_img.height * rscale)}x{round(new_img.width * rscale)}")
                            for frame in new_img.sequence:
                                frame.transform(resize="90000@")
                                final_x = int(frame.height * (x * 0.01))
                                final_y = int(frame.width * (y * 0.01))
                                frame.watermark(
                                    image=wm,
                                    left=final_x,
                                    top=final_y,
                                    transparency=transparency,
                                )
                                new_image.sequence.append(frame)
                        new_image.save(file=final)
            else:
                logger.debug("Le layer est un gif")
                with wand.image.Image() as new_image:
                    with wand.image.Image(filename=layer_path) as new_img:
                        new_img.transform(
                            resize=f"{round(new_img.height * rscale)}x{round(new_img.width * rscale)}")
                        
                        for frame in new_img.sequence:
                            with img.clone() as clone:
                                if is_gif:
                                    clone = clone.sequence[0]
                                else:
                                    clone = clone.convert("gif")

                                clone.transform(resize="90000@")
                                final_x = int(
                                    clone.height * (x * 0.01))
                                final_y = int(clone.width * (y * 0.01))
                                clone.watermark(
                                    image=frame,
                                    left=final_x,
                                    top=final_y,
                                    transparency=transparency,
                                )
                                new_image.sequence.append(clone)
                                new_image.dispose = "background"
                                with new_image.sequence[-1] as new_frame:
                                    new_frame.delay = frame.delay

                    new_image.save(file=final)

        size = final.tell()
        final.seek(0)
        filename = f"{random.randint(0, 99999)}.{'gif' if is_gif or wm_gif else 'png'}"

        file = discord.File(final, filename=filename)
        final.close()
        return file, size
    
    @commands.command()
    async def avatartest(self, ctx, filename: str = 'crown_test.png'):
        url = ctx.author.avatar_url
        b, mime = await self.bytes_download(url)
        if mime not in self.image_mimes + self.gif_mimes and not isinstance(
            url, discord.Asset
        ):
            return await ctx.reply("Ce n'est pas une image valide.", mention_author=False)
        layerpath = bundled_data_path(self) / f'avatar_layer/{filename}' 
        try:
            task = ctx.bot.loop.run_in_executor(
                None, self.apply_layer, b, layerpath, True if layerpath.endswith('.gif') else False
            )
            file, file_size = await asyncio.wait_for(task, timeout=120)
        except asyncio.TimeoutError:
            return await ctx.reply("L'image a mis trop de temps à être traitée.", mention_author=False)
        try:
            await ctx.send(file=file)
        except:
             return await ctx.reply("L'image ne peut pas être upload (trop lourde).", mention_author=False)
        
    @commands.command(name="royale")
    async def start_royale(self, ctx):
        """Démarrer une partie de Battle Royale"""
        guild = ctx.guild
        author = ctx.author
        
        cache = self.get_cache(guild)
        settings = await self.config.guild(guild).all()
        eco = self.bot.get_cog('AltEco')
        currency = await eco.get_currency(guild)
        
        if cache['status'] == 0:
            if not await eco.check_balance(author, settings['TicketPrice']):
                return await ctx.reply(f"**Impossible de lancer une partie** — Votre solde ne permet pas d'acheter votre propre ticket ({settings['TicketPrice']}{currency})", 
                                       mention_author=False)
                
            cache['status'] = 1
            timeout = time.time() + settings['TimeoutDelay']
            
            await self.add_player(author)
            pcache = []
            msg = None
            
            while len(cache['players']) < settings['MaxPlayers'] \
                and time.time() <= timeout \
                    and cache['status'] == 1:
                        
                if pcache != cache['players']:
                    desc = '\n'.join((f'• {p}' for p in cache['players']))
                    em = discord.Embed(title="Battle Royale — Inscriptions", description=desc, color=RoyaleColor)
                    em.set_footer(text=f"Cliquez sur 🎫 pour s'inscrire ({settings['TicketPrice']}{currency})")
                    if not msg:
                        msg = await ctx.send(embed=em)
                        await msg.add_reaction('🎫')
                        cache['register_msg'] = msg.id
                    else:
                        await msg.edit(embed=em)
                    pcache = cache['players']
                await asyncio.sleep(1)
                
            if len(cache['players']) < 4:
                self.clear_cache(guild)
                em = discord.Embed(title="Battle Royale — Inscriptions", 
                                   description= "**Inscriptions annulées** : Manque de joueurs (min. 4)", 
                                   color=RoyaleColor)
                em.set_footer(text=f"Aucune somme n'a été prélevée sur le compte des inscrits")
                return await msg.edit(embed=em)
            
            
        
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
                