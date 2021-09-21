import logging
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import discord
from redbot.core import commands
from redbot.core.data_manager import cog_data_path

logger = logging.getLogger("red.RedX.Soundwave")

class ConversionError(Exception):
    """Problème lors de la conversion de l'audio vers la vidéo"""

class Soundwave(commands.Cog):
    """Convertisseur Audio vers Video"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        
        self.temp = cog_data_path(self) / "temp"
        self.temp.mkdir(exist_ok=True, parents=True)
        
    def download_mp3(self, url: str, filename: str) -> Path:
        path = self.temp / f"{filename}.mp3"
        try:
            urllib.request.urlretrieve(url, path)
        except:
            raise
        return str(path)
    
    async def download_attachment(self, msg: discord.Message):
        path = str(self.temp)
        seed = str(int(time.time()))
        if msg.attachments[0].size <= 1e7:
            filename = "{}_{}".format(seed, msg.attachments[0].filename)
            filepath = "{}/{}".format(str(path), filename)
            await msg.attachments[0].save(filepath)
            return filepath
        else:
            return None
    
    async def audio_to_video(self, audio_path: str, image_path: str, output_path: str):
        com = ['ffmpeg', '-loop', '1', '-i', f'{image_path}', '-i', f'{audio_path}', '-c:v', 'libx264', '-tune', 'stillimage', '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', '-shortest', f'{output_path}.mp4']
        pr = subprocess.Popen(com, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = pr.communicate()
        if pr.returncode != 0:
            raise ConversionError(f"Erreur lors de la conversion : {pr.returncode} {output} {error}")
        return output_path
            
    @commands.command(name="soundwave")
    async def convert_audio(self, ctx, url = None):
        """Convertir un audio en vidéo"""
        if url:
            if self._get_file_type(url) != 'audio':
                return await ctx.send(f"**Fichier invalide** • L'URL doit contenir un fichier audio (MP3)")
            
            urlkey = url.split("/")[-1]
            try:
                audiopath = self.download_mp3(url, urlkey)
            except Exception as e:
                return await ctx.send(f"**Erreur de téléchargement** : `{e}`")
        elif ctx.message.attachments:
            audiopath = await self.download_attachment(ctx.message)
            if not audiopath:
                return await ctx.send(f"**Aucun fichier valide** • Aucun fichier vidéo attaché au message")
        
        path = str(self.temp)
        imagepath = path + "/avatar_{}.jpg".format(ctx.author)
        await ctx.author.avatar_url.save(imagepath)
        
        outputpath = path + f'/{int(time.time())}_{urlkey}'
        
        await self.audio_to_video(audiopath, imagepath, outputpath)
        file = discord.File(outputpath)
        try:
            await ctx.reply(file=file, mention_author=False)
        except Exception as e:
            await ctx.send(f"**Impossible** • Je n'ai pas réussi à upload le résultat de votre demandé\n`{e}`")
        
        for f in (audiopath, imagepath, outputpath):
            os.remove(f)
    