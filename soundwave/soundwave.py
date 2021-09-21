import asyncio
import logging
import os
import subprocess
import time

import aiohttp
import re
import discord
import requests
from redbot.core import commands
from redbot.core.data_manager import cog_data_path

logger = logging.getLogger("red.RedX.Soundwave")

AUDIO_LINKS = re.compile(
    r"(https?:\/\/[^\"\'\s]*\.(?:mp3|ogg|wav|flac)(\?size=[0-9]*)?)", flags=re.I
)

class ConversionError(Exception):
    """Problème lors de la conversion de l'audio vers la vidéo"""

class Soundwave(commands.Cog):
    """Convertisseur Audio vers Video"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        
        self.temp = cog_data_path(self) / "temp"
        self.temp.mkdir(exist_ok=True, parents=True)
        
    def _get_file_type(self, url):
        h = requests.head(url, allow_redirects=True)
        header = h.headers
        content_type = header.get('content-type')
        return content_type.split("/")[0]
    
    async def download_from_url(self, url: str, path: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        with open(path, "wb") as f:
                            f.write(data)
                        return resp.headers.get("Content-type", "").lower()
        except asyncio.TimeoutError:
            return False
    
    async def download_attachment(self, msg: discord.Message):
        path = str(self.temp)
        seed = str(int(time.time()))
        if msg.attachments[0].size <= 2e6:
            if msg.attachments[0].url.split('.')[-1] in ('mp3', 'wav', 'ogg', 'flac'):
                filename = "{}_{}".format(seed, msg.attachments[0].filename)
                filepath = "{}/{}".format(str(path), filename)
                await msg.attachments[0].save(filepath)
                return filepath
        return None
    
    async def search_for_audio_messages(self, ctx):
        audios = []
        async for message in ctx.channel.history(limit=10):
            if message.attachments:
                for attachment in message.attachments:
                    if AUDIO_LINKS.match(attachment.url):
                        audios.append(message)
        return audios
    
    async def audio_to_video(self, audio_path: str, image_path: str, output_path: str):
        com = ['ffmpeg', '-loop', '1', '-i', f'{image_path}', '-i', f'{audio_path}', '-c:v', 'libx264', '-tune', 'stillimage', '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', '-shortest', '-vf', 'scale=360:-1', f'{output_path}.mp4']
        pr = subprocess.Popen(com, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = pr.communicate()
        if pr.returncode != 0:
            raise ConversionError(f"Erreur lors de la conversion : {pr.returncode} {output} {error}")
        return output_path
            
    @commands.command(name="soundwave", aliases=['getvid'])
    async def convert_audio(self, ctx, image_url = None):
        """Convertir un audio en vidéo
        
        L'audio (max. 2 Mo) doit être uploadé avec la commande, ou la commande doit être utilisée en réponse à un message contenant de l'audio
        
        L'image de la vidéo peut être personnalisé en donnant un URL d'image"""
        path = str(self.temp)
        audiopath = None
        imagepath = None
        
        user = ctx.author
        message = ctx.message
        if ctx.message.reference:
            message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            user = message.author
            if message.author == self.bot.user and message.reference:
                refmsg_ref = await ctx.channel.fetch_message(message.reference.message_id)
                user = refmsg_ref.author
        
        if image_url:
            if 'http' not in image_url or self._get_file_type(image_url) != 'image':
                return await ctx.send(f"**Fichier image invalide** • L'URL doit contenir un fichier d'image (png, jpeg etc.)")
            
            urlkey = image_url.split("/")[-1]
            try:
                await self.download_from_url(image_url, path + f'/{urlkey}')
                imagepath = path + f'/{urlkey}'
            except Exception as e:
                return await ctx.send(f"**Erreur de téléchargement de l'image** : `{e}`")
        
        if message.attachments:
            audiopath = await self.download_attachment(message)
        else:
            audiopath = await self.download_attachment(await self.search_for_audio_messages(ctx)[0])
            
        if not audiopath:
            return await ctx.send(f"**Aucun fichier valide** • Aucun fichier audio attaché au message ou fichier trop lourd")
        
        if not imagepath:
            imagepath = path + "/avatar_{}.jpg".format(user.id)
            await user.avatar_url.save(imagepath)
            
        notif = await ctx.send("⏳ Veuillez patienter pendant la création de votre fichier vidéo...")
        async with ctx.channel.typing():
            prepath = path + f'/{int(time.time())}'
            output = await self.audio_to_video(audiopath, imagepath, prepath)
            outputpath = output + '.mp4'
        
        file = discord.File(outputpath)
        try:
            await ctx.reply(file=file, mention_author=False)
        except Exception as e:
            await ctx.send(f"**Impossible** • Je n'ai pas réussi à upload le résultat de votre demandé\n`{e}`")
        
        await notif.delete()
        
        for f in (audiopath, imagepath, outputpath):
            os.remove(f)
    